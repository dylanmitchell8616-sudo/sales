#!/usr/bin/env python3
"""
Prospect Deduplicator - Prevents the same prospect from being emailed across multiple campaigns.

Standalone script and importable module that maintains a master prospect database
and filters CSVs to remove prospects already contacted within a configurable cooldown period.

Usage:
    # Deduplicate CSVs (dry-run, no changes written):
    python prospect_deduplicator.py --csvs output/*.csv --cooldown 30 --dry-run

    # Deduplicate and overwrite CSVs:
    python prospect_deduplicator.py --csvs output/prospect_emails.csv output/case_study_emails.csv

    # Clean up old entries from master list:
    python prospect_deduplicator.py --cleanup --max-age 90
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta, timezone


DEFAULT_MASTER_LIST_PATH = "output/master_prospect_list.json"
EMAIL_FIELDS = ("email", "contact_email", "prospect_email")


def load_master_list(path=DEFAULT_MASTER_LIST_PATH):
    """Load the master prospect list from disk.

    Args:
        path: Path to the JSON file containing the master prospect list.

    Returns:
        dict of {email_lower: {"campaigns": [...], "first_seen": iso_date,
                                "last_contacted": iso_date, "domain": str}}
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"Warning: Could not load master list from {path}: {e}")
        return {}
    return data


def save_master_list(data, path=DEFAULT_MASTER_LIST_PATH):
    """Persist the master prospect list to disk.

    Args:
        data: The master list dict to save.
        path: Destination file path.
    """
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _extract_email(row):
    """Extract and normalize email from a CSV row, trying multiple field names.

    Args:
        row: A dict representing a single CSV row.

    Returns:
        Lowercase email string, or None if no email field found.
    """
    for field in EMAIL_FIELDS:
        val = row.get(field, "").strip()
        if val:
            return val.lower()
    # Try case-insensitive field matching as a fallback
    row_lower = {k.lower(): v for k, v in row.items()}
    for field in EMAIL_FIELDS:
        val = row_lower.get(field, "").strip()
        if val:
            return val.lower()
    return None


def _extract_domain(email):
    """Extract domain from an email address.

    Args:
        email: An email address string.

    Returns:
        Domain portion of the email, or empty string on failure.
    """
    try:
        return email.split("@")[1]
    except (IndexError, AttributeError):
        return ""


def deduplicate_csv(csv_path, master_list, cooldown_days=30):
    """Read a CSV and filter out prospects already contacted within the cooldown period.

    Also deduplicates within the CSV itself, keeping the first occurrence of each email.

    Args:
        csv_path: Path to the CSV file to deduplicate.
        master_list: The master prospect dict.
        cooldown_days: Number of days within which a prospect should not be re-emailed.

    Returns:
        Tuple of (kept_rows, skipped_rows) where each is a list of dicts.
    """
    if not os.path.exists(csv_path):
        print(f"Warning: CSV file not found: {csv_path}")
        return [], []

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"Warning: CSV file is empty: {csv_path}")
        return [], []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=cooldown_days)
    seen_in_csv = set()
    kept = []
    skipped = []

    for row in rows:
        email = _extract_email(row)
        if email is None:
            # No email field found; keep the row but warn once
            kept.append(row)
            continue

        # Deduplicate within this CSV
        if email in seen_in_csv:
            skipped.append(row)
            continue
        seen_in_csv.add(email)

        # Check master list cooldown
        entry = master_list.get(email)
        if entry:
            last_contacted = entry.get("last_contacted")
            if last_contacted:
                try:
                    last_dt = datetime.fromisoformat(last_contacted)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt >= cutoff:
                        skipped.append(row)
                        continue
                except (ValueError, TypeError):
                    pass

        kept.append(row)

    print(
        f"Deduped {csv_path}: {len(kept)} kept, {len(skipped)} skipped "
        f"(already contacted within {cooldown_days} days)"
    )
    return kept, skipped


def register_contacts(emails, campaign_name, master_list):
    """Add or update contacts in the master list with the current timestamp and campaign.

    Args:
        emails: List of email address strings to register.
        campaign_name: Name of the campaign these contacts are part of.
        master_list: The master prospect dict (modified in place).

    Returns:
        The updated master_list.
    """
    now_iso = datetime.now(timezone.utc).isoformat()

    for raw_email in emails:
        email = raw_email.strip().lower()
        if not email:
            continue

        if email in master_list:
            entry = master_list[email]
            entry["last_contacted"] = now_iso
            if campaign_name and campaign_name not in entry["campaigns"]:
                entry["campaigns"].append(campaign_name)
        else:
            master_list[email] = {
                "campaigns": [campaign_name] if campaign_name else [],
                "first_seen": now_iso,
                "last_contacted": now_iso,
                "domain": _extract_domain(email),
            }

    return master_list


def cleanup_old_entries(master_list, max_age_days=90):
    """Remove entries older than max_age_days from the master list.

    An entry's age is determined by its last_contacted date.

    Args:
        master_list: The master prospect dict.
        max_age_days: Maximum age in days before an entry is removed.

    Returns:
        A new dict with old entries removed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    cleaned = {}
    removed = 0

    for email, entry in master_list.items():
        last_contacted = entry.get("last_contacted")
        if last_contacted:
            try:
                last_dt = datetime.fromisoformat(last_contacted)
                if last_dt.tzinfo is None:
                    last_dt = last_dt.replace(tzinfo=timezone.utc)
                if last_dt < cutoff:
                    removed += 1
                    continue
            except (ValueError, TypeError):
                pass
        cleaned[email] = entry

    print(f"Cleanup: removed {removed} entries older than {max_age_days} days, {len(cleaned)} remaining")
    return cleaned


def _write_csv(path, rows, fieldnames):
    """Write a list of row dicts back to a CSV file.

    Args:
        path: Output CSV path.
        rows: List of dicts to write.
        fieldnames: Column headers for the CSV.
    """
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _infer_campaign_name(csv_path):
    """Derive a campaign name from a CSV filename.

    Args:
        csv_path: Path to the CSV file.

    Returns:
        A human-readable campaign name string.
    """
    base = os.path.splitext(os.path.basename(csv_path))[0]
    return base.replace("_", " ").replace("-", " ").title()


def main():
    parser = argparse.ArgumentParser(
        description="Prospect Deduplicator - prevent duplicate emails across campaigns"
    )
    parser.add_argument(
        "--csvs",
        nargs="+",
        help="CSV files to deduplicate",
    )
    parser.add_argument(
        "--cooldown",
        type=int,
        default=30,
        help="Cooldown period in days (default: 30)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be removed without modifying any files",
    )
    parser.add_argument(
        "--cleanup",
        action="store_true",
        help="Remove old entries from the master list",
    )
    parser.add_argument(
        "--max-age",
        type=int,
        default=90,
        help="Max age in days for cleanup (default: 90)",
    )
    parser.add_argument(
        "--master-list",
        default=DEFAULT_MASTER_LIST_PATH,
        help=f"Path to master prospect list (default: {DEFAULT_MASTER_LIST_PATH})",
    )

    args = parser.parse_args()

    if not args.csvs and not args.cleanup:
        parser.print_help()
        sys.exit(1)

    master_list = load_master_list(args.master_list)
    print(f"Loaded master list: {len(master_list)} existing prospects")

    # Cleanup mode
    if args.cleanup:
        master_list = cleanup_old_entries(master_list, max_age_days=args.max_age)
        if not args.dry_run:
            save_master_list(master_list, args.master_list)
            print(f"Master list saved to {args.master_list}")
        else:
            print("[DRY RUN] Master list not saved")

    # CSV deduplication mode
    if args.csvs:
        total_kept = 0
        total_skipped = 0

        for csv_path in args.csvs:
            kept, skipped = deduplicate_csv(csv_path, master_list, cooldown_days=args.cooldown)

            if not kept and not skipped:
                continue

            total_kept += len(kept)
            total_skipped += len(skipped)

            if not args.dry_run:
                # Overwrite the CSV with kept rows only
                if kept:
                    fieldnames = list(kept[0].keys())
                    _write_csv(csv_path, kept, fieldnames)

                # Register kept contacts in master list
                kept_emails = [_extract_email(row) for row in kept]
                kept_emails = [e for e in kept_emails if e is not None]
                campaign_name = _infer_campaign_name(csv_path)
                register_contacts(kept_emails, campaign_name, master_list)

        # Print overall summary
        print(f"\nTotal across all files: {total_kept} kept, {total_skipped} skipped")

        if not args.dry_run:
            save_master_list(master_list, args.master_list)
            print(f"Master list saved to {args.master_list} ({len(master_list)} prospects)")
        else:
            print("[DRY RUN] No files were modified")


if __name__ == "__main__":
    main()
