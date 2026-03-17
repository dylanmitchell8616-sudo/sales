#!/usr/bin/env python3
"""
ZoomInfo Contact Enricher
==========================
Enriches pipeline leads with real contact emails and phone numbers
using the ZoomInfo API.

Reads CSVs from the output directory, looks up contacts by company domain,
and writes enriched versions back.

Usage:
    python zoominfo_enricher.py --output-dir output
    python zoominfo_enricher.py --output-dir output --dry-run
    python zoominfo_enricher.py --output-dir output --csv prospect_emails.csv
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = str(BASE_DIR / "config.json")

# ZoomInfo API endpoints
ZOOMINFO_AUTH_URL = "https://api.zoominfo.com/authenticate"
ZOOMINFO_SEARCH_URL = "https://api.zoominfo.com/search/contact"
ZOOMINFO_ENRICH_URL = "https://api.zoominfo.com/enrich/contact"
ZOOMINFO_COMPANY_URL = "https://api.zoominfo.com/search/company"

RATE_LIMIT_DELAY = 0.5  # seconds between API calls
MAX_RETRIES = 3

# Target titles for decision-makers at small service businesses
TARGET_TITLES = [
    "owner", "founder", "ceo", "president", "managing director",
    "general manager", "practice manager", "office manager",
    "director of operations", "operations manager",
    "marketing director", "marketing manager",
    "clinic manager", "spa manager", "medical director",
]

# CSVs that contain leads needing enrichment
ENRICHABLE_CSVS = [
    "icp_prospects.csv",
    "prospect_emails.csv",
    "case_study_emails.csv",
    "news_triggered_emails.csv",
    "displacement_emails.csv",
    "social_outreach_emails.csv",
    "job_signal_emails.csv",
    "event_outreach_emails.csv",
]


class ZoomInfoClient:
    """Client for the ZoomInfo API with JWT authentication."""

    def __init__(self, api_key: str = None, username: str = None, password: str = None):
        self.api_key = api_key
        self.username = username
        self.password = password
        self.jwt_token = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })

    def authenticate(self) -> bool:
        """Authenticate with ZoomInfo and get a JWT token."""
        if self.api_key:
            # API key auth (Partner API key)
            self.jwt_token = self.api_key
            self.session.headers["Authorization"] = f"Bearer {self.api_key}"
            # Test the token with a simple request
            try:
                resp = self.session.post(
                    ZOOMINFO_COMPANY_URL,
                    json={"companyName": "test", "rpp": 1},
                    timeout=15,
                )
                if resp.status_code == 401:
                    print("[ERROR] ZoomInfo API key is invalid or expired.")
                    return False
                return True
            except requests.RequestException as e:
                print(f"[ERROR] ZoomInfo auth test failed: {e}")
                return False

        elif self.username and self.password:
            # Username/password auth
            try:
                resp = self.session.post(
                    ZOOMINFO_AUTH_URL,
                    json={"username": self.username, "password": self.password},
                    timeout=15,
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self.jwt_token = data.get("jwt")
                    self.session.headers["Authorization"] = f"Bearer {self.jwt_token}"
                    return True
                else:
                    print(f"[ERROR] ZoomInfo auth failed: {resp.status_code} {resp.text[:200]}")
                    return False
            except requests.RequestException as e:
                print(f"[ERROR] ZoomInfo auth failed: {e}")
                return False
        else:
            print("[ERROR] No ZoomInfo credentials provided.")
            print("  Set zoominfo_api_key or zoominfo_username + zoominfo_password in config.json")
            return False

    def _request(self, url: str, payload: dict, retries: int = MAX_RETRIES) -> dict | None:
        """Make an authenticated API request with retry logic."""
        for attempt in range(retries):
            try:
                resp = self.session.post(url, json=payload, timeout=30)
                if resp.status_code == 200:
                    return resp.json()
                elif resp.status_code == 429:
                    wait = 2 ** (attempt + 1)
                    print(f"    Rate limited, waiting {wait}s...")
                    time.sleep(wait)
                    continue
                elif resp.status_code == 401:
                    print("    [WARN] Token expired, re-authenticating...")
                    if self.authenticate():
                        continue
                    return None
                else:
                    print(f"    [WARN] ZoomInfo API error: {resp.status_code}")
                    if attempt < retries - 1:
                        time.sleep(1)
                    continue
            except requests.RequestException as e:
                print(f"    [WARN] Request failed: {e}")
                if attempt < retries - 1:
                    time.sleep(2 ** attempt)
                continue
        return None

    def search_contacts_by_domain(self, domain: str, limit: int = 5) -> list[dict]:
        """
        Search for contacts at a company by domain.
        Returns list of contacts with name, title, email, phone.
        """
        payload = {
            "companyWebsite": domain,
            "rpp": limit,
            "jobTitleHierarchy": [
                "C-Suite", "VP-Level", "Director", "Manager", "Owner"
            ],
        }

        data = self._request(ZOOMINFO_SEARCH_URL, payload)
        if not data:
            return []

        contacts = []
        for contact in data.get("data", []):
            contacts.append({
                "name": f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip(),
                "first_name": contact.get("firstName", ""),
                "last_name": contact.get("lastName", ""),
                "title": contact.get("jobTitle", ""),
                "email": contact.get("email", ""),
                "phone": contact.get("directPhoneNumber", "") or contact.get("companyPhoneNumber", ""),
                "linkedin": contact.get("linkedinUrl", ""),
                "company": contact.get("companyName", ""),
            })

        return contacts

    def enrich_contact(self, email: str = None, name: str = None,
                       company: str = None) -> dict | None:
        """Enrich a specific contact by email or name+company."""
        payload = {}
        if email:
            payload["emailAddress"] = email
        if name and company:
            parts = name.split(" ", 1)
            payload["firstName"] = parts[0]
            if len(parts) > 1:
                payload["lastName"] = parts[1]
            payload["companyName"] = company

        if not payload:
            return None

        data = self._request(ZOOMINFO_ENRICH_URL, payload)
        if not data or not data.get("data"):
            return None

        contact = data["data"][0] if isinstance(data["data"], list) else data["data"]
        return {
            "name": f"{contact.get('firstName', '')} {contact.get('lastName', '')}".strip(),
            "title": contact.get("jobTitle", ""),
            "email": contact.get("email", ""),
            "phone": contact.get("directPhoneNumber", "") or contact.get("companyPhoneNumber", ""),
            "linkedin": contact.get("linkedinUrl", ""),
        }


def pick_best_contact(contacts: list[dict]) -> dict | None:
    """Pick the best contact from a list, preferring owners/founders with emails."""
    if not contacts:
        return None

    # Score each contact
    scored = []
    for c in contacts:
        score = 0
        title_lower = (c.get("title") or "").lower()

        # Must have an email
        if not c.get("email"):
            score -= 100

        # Prefer owner-level titles
        for i, target in enumerate(TARGET_TITLES):
            if target in title_lower:
                score += (len(TARGET_TITLES) - i) * 10
                break

        # Having a phone is a bonus
        if c.get("phone"):
            score += 5

        scored.append((score, c))

    scored.sort(key=lambda x: -x[0])
    best = scored[0]

    # Only return if they have an email
    if best[0] > -100:
        return best[1]
    return None


def enrich_csv(client: ZoomInfoClient, csv_path: str, dry_run: bool = False) -> dict:
    """
    Enrich a single CSV file with ZoomInfo contact data.
    Returns stats dict.
    """
    if not os.path.exists(csv_path):
        return {"file": csv_path, "status": "not_found"}

    filename = os.path.basename(csv_path)
    stats = {
        "file": filename,
        "total": 0,
        "enriched": 0,
        "already_had_email": 0,
        "no_match": 0,
        "errors": 0,
    }

    # Read existing data
    rows = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames or []
        for row in reader:
            rows.append(row)

    stats["total"] = len(rows)
    if not rows:
        return stats

    # Add enrichment columns if not present
    extra_fields = []
    for field in ["contact_email", "contact_name", "contact_title", "contact_phone", "contact_linkedin"]:
        if field not in fieldnames:
            extra_fields.append(field)
    all_fieldnames = fieldnames + extra_fields

    print(f"\n  Enriching {filename}: {len(rows)} leads")

    enriched_rows = []
    for i, row in enumerate(rows):
        domain = row.get("domain", "")
        existing_email = (
            row.get("contact_email", "")
            or row.get("email", "")
            or row.get("prospect_email", "")
        )

        # Skip if already has a real email (not a placeholder)
        if existing_email and not existing_email.startswith("contact@") and "@" in existing_email:
            stats["already_had_email"] += 1
            enriched_rows.append(row)
            continue

        if not domain:
            enriched_rows.append(row)
            stats["no_match"] += 1
            continue

        if dry_run:
            print(f"    [DRY RUN] Would enrich: {domain}")
            enriched_rows.append(row)
            stats["enriched"] += 1
            continue

        # Search ZoomInfo for contacts at this domain
        print(f"    [{i+1}/{len(rows)}] {domain}", end="")
        contacts = client.search_contacts_by_domain(domain, limit=5)
        best = pick_best_contact(contacts)

        if best and best.get("email"):
            row["contact_email"] = best["email"]
            row["contact_name"] = best["name"]
            row["contact_title"] = best["title"]
            row["contact_phone"] = best.get("phone", "")
            row["contact_linkedin"] = best.get("linkedin", "")

            # Also update email fields used by other CSVs
            if "email" in fieldnames:
                row["email"] = best["email"]
            if "prospect_email" in fieldnames:
                row["prospect_email"] = best["email"]

            stats["enriched"] += 1
            print(f" -> {best['name']} ({best['title']}) <{best['email']}>")
        else:
            stats["no_match"] += 1
            print(f" -> no match")

        enriched_rows.append(row)
        time.sleep(RATE_LIMIT_DELAY)

    # Write enriched CSV back
    if not dry_run and stats["enriched"] > 0:
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=all_fieldnames, extrasaction="ignore")
            writer.writeheader()
            for row in enriched_rows:
                writer.writerow(row)
        print(f"    Updated {csv_path} with {stats['enriched']} enriched contacts")

    return stats


def load_config() -> dict:
    """Load config.json."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def main():
    parser = argparse.ArgumentParser(
        description="ZoomInfo Contact Enricher — enrich pipeline leads with real emails and phones"
    )
    parser.add_argument(
        "--output-dir", default="output",
        help="Directory containing pipeline output CSVs (default: output)"
    )
    parser.add_argument(
        "--csv", default=None,
        help="Enrich only a specific CSV file (e.g., prospect_emails.csv)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview enrichment without making API calls"
    )
    parser.add_argument(
        "--api-key", default=None,
        help="ZoomInfo API key (overrides config.json)"
    )
    args = parser.parse_args()

    config = load_config()

    # Resolve output dir
    output_dir = args.output_dir
    if not os.path.isabs(output_dir):
        output_dir = str(BASE_DIR / output_dir)

    # Get credentials
    api_key = args.api_key or config.get("zoominfo_api_key", "")
    username = config.get("zoominfo_username", "")
    password = config.get("zoominfo_password", "")

    if not api_key and not (username and password):
        print("=" * 60)
        print("  ZoomInfo Contact Enricher")
        print("=" * 60)
        print()
        print("  [ERROR] No ZoomInfo credentials found.")
        print()
        print("  Add one of the following to config.json:")
        print()
        print('    "zoominfo_api_key": "YOUR_API_KEY"')
        print()
        print("  Or username/password:")
        print()
        print('    "zoominfo_username": "you@company.com",')
        print('    "zoominfo_password": "your_password"')
        print()
        print("  Or pass via command line:")
        print()
        print("    python zoominfo_enricher.py --api-key YOUR_KEY")
        print()
        print("=" * 60)
        sys.exit(1)

    print("=" * 60)
    print("  ZoomInfo Contact Enricher — Realside AI")
    print("=" * 60)
    print(f"  Output dir: {output_dir}")
    if args.dry_run:
        print(f"  Mode: DRY RUN")
    print("=" * 60)

    # Initialize client
    client = ZoomInfoClient(api_key=api_key, username=username, password=password)

    if not args.dry_run:
        print("\n  Authenticating with ZoomInfo...")
        if not client.authenticate():
            sys.exit(1)
        print("  [OK] Authenticated successfully")

    # Determine which CSVs to enrich
    if args.csv:
        csv_files = [args.csv]
    else:
        csv_files = ENRICHABLE_CSVS

    # Enrich each CSV
    all_stats = []
    total_enriched = 0
    total_leads = 0

    for csv_file in csv_files:
        csv_path = os.path.join(output_dir, csv_file)
        if not os.path.exists(csv_path):
            continue

        stats = enrich_csv(client, csv_path, dry_run=args.dry_run)
        all_stats.append(stats)
        total_enriched += stats.get("enriched", 0)
        total_leads += stats.get("total", 0)

    # Print summary
    print(f"\n{'=' * 60}")
    print(f"  ENRICHMENT SUMMARY")
    print(f"{'=' * 60}")

    for stats in all_stats:
        status = stats.get("status", "")
        if status == "not_found":
            continue
        print(f"\n  {stats['file']}:")
        print(f"    Total leads:       {stats['total']}")
        print(f"    Already had email: {stats['already_had_email']}")
        print(f"    Enriched:          {stats['enriched']}")
        print(f"    No match:          {stats['no_match']}")

    print(f"\n  TOTAL: {total_enriched}/{total_leads} leads enriched with ZoomInfo data")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
