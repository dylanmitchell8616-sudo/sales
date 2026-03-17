#!/usr/bin/env python3
"""File watcher that auto-imports new lead CSVs into Instantly campaigns.

Drop a CSV into leads/incoming/ and walk away. This script will:
  1. Detect the new file
  2. Read and validate the leads (deduplicate by email)
  3. Split leads evenly across three A/B test campaigns
  4. Upload via Instantly API v2
  5. Move the processed CSV to leads/processed/
  6. Log everything

Usage:
    python lead_watcher.py          # foreground
    nohup python lead_watcher.py &  # background

Campaign assignments (A/B test split):
    First third  -> Cost Angle
    Second third -> Time Angle
    Last third   -> Social Proof
"""

import os
import sys
import csv
import time
import json
import shutil
import logging
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv()

from instantly.client import InstantlyClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
INCOMING_DIR = BASE_DIR / "leads" / "incoming"
PROCESSED_DIR = BASE_DIR / "leads" / "processed"
LOG_DIR = BASE_DIR / "logs"
LOG_FILE = LOG_DIR / "lead_watcher.log"

POLL_INTERVAL = 30  # seconds

# A/B test campaigns
CAMPAIGNS = [
    {
        "id": "672fa45d-ed45-463e-9198-6137ee7043d9",
        "name": "Cost Angle",
    },
    {
        "id": "c5d69ff5-357b-42c6-bd3a-f5eff9c8ca22",
        "name": "Time Angle",
    },
    {
        "id": "0571c68e-e187-41c6-9e32-0cf7b8a7d84d",
        "name": "Social Proof",
    },
]

# Column name mapping: common CSV headers -> Instantly variable names
FIELD_MAP = {
    # email
    "email": "email",
    "email address": "email",
    "e-mail": "email",
    "email_address": "email",
    # first name
    "first name": "firstName",
    "first_name": "firstName",
    "firstname": "firstName",
    "fname": "firstName",
    "first": "firstName",
    # last name
    "last name": "lastName",
    "last_name": "lastName",
    "lastname": "lastName",
    "lname": "lastName",
    "last": "lastName",
    # company
    "company": "companyName",
    "company name": "companyName",
    "company_name": "companyName",
    "companyname": "companyName",
    "organization": "companyName",
    "org": "companyName",
    # job title
    "title": "jobTitle",
    "job title": "jobTitle",
    "job_title": "jobTitle",
    "jobtitle": "jobTitle",
    "role": "jobTitle",
    "position": "jobTitle",
    # website
    "website": "website",
    "url": "website",
    "domain": "website",
    # phone
    "phone": "phone",
    "phone number": "phone",
    "phone_number": "phone",
    # linkedin
    "linkedin": "linkedin",
    "linkedin url": "linkedin",
    "linkedin_url": "linkedin",
}

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging() -> logging.Logger:
    """Configure file + console logging."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("lead_watcher")
    logger.setLevel(logging.INFO)

    formatter = logging.Formatter(
        "[%(asctime)s] %(levelname)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(formatter)
    logger.addHandler(ch)

    return logger


log = setup_logging()

# ---------------------------------------------------------------------------
# Lead helpers
# ---------------------------------------------------------------------------


def normalize_field(name: str) -> str:
    """Map a CSV column header to an Instantly variable name."""
    key = name.strip().lower()
    if key in FIELD_MAP:
        return FIELD_MAP[key]
    # Pass through unknown columns as-is (snake_case)
    return key.replace(" ", "_")


def read_and_validate(csv_path: Path) -> list[dict]:
    """Read a CSV file and return deduplicated, validated lead dicts.

    Each lead dict uses Instantly variable names (firstName, lastName, etc.).
    Leads without an email address are discarded.
    Duplicate emails are removed (first occurrence wins).
    """
    leads: list[dict] = []
    seen_emails: set[str] = set()

    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None:
            log.warning("CSV has no headers: %s", csv_path.name)
            return []

        for row in reader:
            lead: dict[str, str] = {}
            for col, val in row.items():
                if col is None or val is None:
                    continue
                mapped = normalize_field(col)
                cleaned = val.strip()
                if cleaned:
                    lead[mapped] = cleaned

            email = lead.get("email", "").lower()
            if not email:
                continue
            if email in seen_emails:
                continue
            seen_emails.add(email)
            lead["email"] = email
            leads.append(lead)

    return leads


def split_leads(leads: list[dict]) -> list[list[dict]]:
    """Split a list of leads into three roughly equal groups.

    Returns a list of three lists corresponding to the three campaigns.
    """
    n = len(leads)
    third = n // 3
    remainder = n % 3

    # Distribute remainder: first groups get one extra lead each
    sizes = [third] * 3
    for i in range(remainder):
        sizes[i] += 1

    chunks: list[list[dict]] = []
    start = 0
    for size in sizes:
        chunks.append(leads[start : start + size])
        start += size

    return chunks


# ---------------------------------------------------------------------------
# Instantly upload
# ---------------------------------------------------------------------------


def upload_leads(client: InstantlyClient, campaign_id: str, leads: list[dict]) -> dict:
    """Upload a batch of leads to a campaign via POST /api/v2/leads.

    Sends in batches of 500 to stay within API limits.
    Returns the API response from the last batch.
    """
    BATCH_SIZE = 500
    result = {}

    for i in range(0, len(leads), BATCH_SIZE):
        batch = leads[i : i + BATCH_SIZE]
        result = client.post("leads", json={
            "campaign_id": campaign_id,
            "leads": batch,
        })

    return result


# ---------------------------------------------------------------------------
# File processing
# ---------------------------------------------------------------------------


def process_file(csv_path: Path, client: InstantlyClient) -> bool:
    """Process a single CSV file: validate, split, upload, move.

    Returns True on success, False on failure.
    """
    log.info("Processing file: %s", csv_path.name)

    # Read and validate
    try:
        leads = read_and_validate(csv_path)
    except Exception as exc:
        log.error("Failed to read %s: %s", csv_path.name, exc)
        return False

    if not leads:
        log.warning("No valid leads found in %s — moving to processed anyway", csv_path.name)
        _move_to_processed(csv_path)
        return True

    log.info("Loaded %d valid leads from %s", len(leads), csv_path.name)

    # Split across campaigns
    chunks = split_leads(leads)

    total_uploaded = 0
    for campaign, chunk in zip(CAMPAIGNS, chunks):
        if not chunk:
            log.info("  %s: 0 leads (skipped)", campaign["name"])
            continue

        try:
            upload_leads(client, campaign["id"], chunk)
            log.info(
                "  %s: %d leads uploaded (campaign %s)",
                campaign["name"],
                len(chunk),
                campaign["id"],
            )
            total_uploaded += len(chunk)
        except Exception as exc:
            log.error(
                "  %s: FAILED to upload %d leads — %s",
                campaign["name"],
                len(chunk),
                exc,
            )

    log.info(
        "Summary for %s: %d/%d leads uploaded across %d campaigns",
        csv_path.name,
        total_uploaded,
        len(leads),
        len(CAMPAIGNS),
    )

    # Move to processed
    _move_to_processed(csv_path)

    return total_uploaded == len(leads)


def _move_to_processed(csv_path: Path) -> None:
    """Move a CSV to the processed directory with a timestamp prefix."""
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = PROCESSED_DIR / f"{timestamp}_{csv_path.name}"

    shutil.move(str(csv_path), str(dest))
    log.info("Moved %s -> %s", csv_path.name, dest.name)


# ---------------------------------------------------------------------------
# Watcher loop
# ---------------------------------------------------------------------------


def get_csv_files(directory: Path) -> list[Path]:
    """Return a sorted list of .csv files in a directory."""
    if not directory.exists():
        return []
    return sorted(directory.glob("*.csv"))


def watch(client: InstantlyClient) -> None:
    """Poll leads/incoming/ for new CSV files and process them."""
    log.info("=" * 60)
    log.info("Lead watcher started")
    log.info("Watching: %s", INCOMING_DIR)
    log.info("Processed: %s", PROCESSED_DIR)
    log.info("Poll interval: %ds", POLL_INTERVAL)
    log.info("Campaigns:")
    for c in CAMPAIGNS:
        log.info("  - %s (%s)", c["name"], c["id"])
    log.info("=" * 60)

    while True:
        try:
            csv_files = get_csv_files(INCOMING_DIR)

            if csv_files:
                log.info("Found %d CSV file(s) to process", len(csv_files))

            for csv_path in csv_files:
                # Skip files still being written (size hasn't stabilized)
                try:
                    size_before = csv_path.stat().st_size
                    time.sleep(1)
                    size_after = csv_path.stat().st_size
                    if size_before != size_after:
                        log.info("File %s still being written, skipping for now", csv_path.name)
                        continue
                except FileNotFoundError:
                    continue

                process_file(csv_path, client)

        except KeyboardInterrupt:
            log.info("Shutting down (keyboard interrupt)")
            break
        except Exception as exc:
            log.error("Unexpected error in watch loop: %s", exc, exc_info=True)

        try:
            time.sleep(POLL_INTERVAL)
        except KeyboardInterrupt:
            log.info("Shutting down (keyboard interrupt)")
            break


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    # Ensure directories exist
    INCOMING_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    # Connect to Instantly
    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        log.error("INSTANTLY_API_KEY not set in environment or .env file")
        sys.exit(1)

    client = InstantlyClient(api_key)

    # Verify connection
    try:
        client.list_campaigns(limit=1)
        log.info("Instantly API connection verified")
    except Exception as exc:
        log.error("Failed to connect to Instantly API: %s", exc)
        sys.exit(1)

    watch(client)


if __name__ == "__main__":
    main()
