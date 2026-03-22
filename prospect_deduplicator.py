#!/usr/bin/env python3
"""
Prospect Deduplicator - Prevents the same prospect from being emailed across multiple campaigns.

Standalone script and importable module that maintains a master prospect database
and filters CSVs to remove prospects already contacted within a configurable cooldown period.

Features:
  - Exact email dedup with per-campaign-type cooldowns
  - Fuzzy company name matching (catches "ABC Corp" vs "ABC Corporation")
  - Domain-level dedup (if anyone@company.com was contacted, flag new contacts there)
  - Detailed logging of WHY each prospect was deduped

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
import re
import sys
from datetime import datetime, timedelta, timezone


DEFAULT_MASTER_LIST_PATH = "output/master_prospect_list.json"
EMAIL_FIELDS = ("email", "contact_email", "prospect_email")
COMPANY_FIELDS = ("company_name", "prospect_company", "company")
DOMAIN_FIELDS = ("domain", "website")

# Per-campaign-type cooldown defaults (days)
CAMPAIGN_TYPE_COOLDOWNS = {
    "cold": 30,
    "prospect": 30,
    "case_study": 30,
    "news": 21,
    "displacement": 30,
    "social": 7,
    "warm": 7,
    "event": 14,
    "followup": 7,
    "follow-up": 7,
    "engaged": 7,
    "objection": 7,
    "job_signal": 21,
}

# Default cooldown when campaign type is unknown
DEFAULT_COOLDOWN_DAYS = 30

# Common company suffixes to normalize for fuzzy matching
COMPANY_SUFFIXES = [
    r"\s+(inc\.?|incorporated)$",
    r"\s+(llc|l\.l\.c\.)$",
    r"\s+(ltd\.?|limited)$",
    r"\s+(corp\.?|corporation)$",
    r"\s+(co\.?|company)$",
    r"\s+(group|holdings|enterprises)$",
    r"\s+(pllc|p\.l\.l\.c\.)$",
    r"\s+(pc|p\.c\.)$",
    r"\s+(pa|p\.a\.)$",
    r"\s+(dba|d/b/a)$",
    r"\s+(dds|md|dmd)$",
    r",?\s*(the)?$",
]


def load_master_list(path=DEFAULT_MASTER_LIST_PATH):
    """Load the master prospect list from disk.

    Args:
        path: Path to the JSON file containing the master prospect list.

    Returns:
        dict of {email_lower: {"campaigns": [...], "first_seen": iso_date,
                                "last_contacted": iso_date, "domain": str,
                                "company_name": str, "dedup_reason": str}}
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


def _extract_company(row):
    """Extract company name from a CSV row.

    Args:
        row: A dict representing a single CSV row.

    Returns:
        Company name string, or empty string if not found.
    """
    for field in COMPANY_FIELDS:
        val = row.get(field, "").strip()
        if val:
            return val
    row_lower = {k.lower(): v for k, v in row.items()}
    for field in COMPANY_FIELDS:
        val = row_lower.get(field, "").strip()
        if val:
            return val
    return ""


def _extract_row_domain(row):
    """Extract domain from a CSV row (from domain field or email).

    Args:
        row: A dict representing a single CSV row.

    Returns:
        Domain string, or empty string if not found.
    """
    for field in DOMAIN_FIELDS:
        val = row.get(field, "").strip()
        if val:
            # Clean up domain
            val = val.lower().replace("https://", "").replace("http://", "").split("/")[0]
            val = re.sub(r"^www\.", "", val)
            if "." in val:
                return val
    # Fall back to email domain
    email = _extract_email(row)
    if email:
        return _extract_domain(email)
    return ""


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


def normalize_company_name(name):
    """Normalize a company name for fuzzy matching.

    Strips common suffixes (Inc, LLC, Corp, etc.), lowercases,
    removes punctuation, and collapses whitespace.

    Args:
        name: Raw company name string.

    Returns:
        Normalized company name string.
    """
    if not name:
        return ""
    normalized = name.lower().strip()
    # Remove common suffixes
    for pattern in COMPANY_SUFFIXES:
        normalized = re.sub(pattern, "", normalized, flags=re.IGNORECASE)
    # Remove punctuation except hyphens
    normalized = re.sub(r"[^\w\s-]", "", normalized)
    # Collapse whitespace
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _build_domain_index(master_list):
    """Build a reverse index of domain -> list of emails for domain-level dedup.

    Args:
        master_list: The master prospect dict.

    Returns:
        dict of {domain: [email1, email2, ...]}
    """
    domain_index = {}
    for email, entry in master_list.items():
        domain = entry.get("domain") or _extract_domain(email)
        if domain:
            domain_index.setdefault(domain, []).append(email)
    return domain_index


def _build_company_index(master_list):
    """Build a reverse index of normalized_company_name -> list of emails.

    Args:
        master_list: The master prospect dict.

    Returns:
        dict of {normalized_name: [email1, email2, ...]}
    """
    company_index = {}
    for email, entry in master_list.items():
        company = entry.get("company_name", "")
        normalized = normalize_company_name(company)
        if normalized:
            company_index.setdefault(normalized, []).append(email)
    return company_index


def _get_cooldown_for_campaign(csv_path, explicit_cooldown=None):
    """Determine the cooldown period based on campaign type inferred from filename.

    Args:
        csv_path: Path to the CSV file.
        explicit_cooldown: If provided, use this instead of auto-detection.

    Returns:
        Cooldown in days.
    """
    if explicit_cooldown is not None:
        return explicit_cooldown

    basename = os.path.splitext(os.path.basename(csv_path))[0].lower()

    for keyword, days in CAMPAIGN_TYPE_COOLDOWNS.items():
        if keyword in basename:
            return days

    return DEFAULT_COOLDOWN_DAYS


def deduplicate_csv(csv_path, master_list, cooldown_days=None, domain_dedup=True,
                    fuzzy_company=True):
    """Read a CSV and filter out prospects already contacted within the cooldown period.

    Also deduplicates within the CSV itself, keeping the first occurrence of each email.
    Performs domain-level dedup and fuzzy company name matching when enabled.

    Args:
        csv_path: Path to the CSV file to deduplicate.
        master_list: The master prospect dict.
        cooldown_days: Number of days within which a prospect should not be re-emailed.
                       If None, auto-detects based on campaign type from filename.
        domain_dedup: If True, flag prospects whose domain has been contacted.
        fuzzy_company: If True, use fuzzy company name matching.

    Returns:
        Tuple of (kept_rows, skipped_rows, dedup_log) where kept/skipped are lists
        of dicts and dedup_log is a list of {email, reason, details} dicts.
    """
    if not os.path.exists(csv_path):
        print(f"Warning: CSV file not found: {csv_path}")
        return [], [], []

    # Auto-detect cooldown if not explicitly provided
    effective_cooldown = _get_cooldown_for_campaign(csv_path, cooldown_days)

    with open(csv_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"Warning: CSV file is empty: {csv_path}")
        return [], [], []

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=effective_cooldown)
    seen_in_csv = set()
    seen_domains_in_csv = set()
    kept = []
    skipped = []
    dedup_log = []

    # Build indexes for fast lookup
    domain_index = _build_domain_index(master_list) if domain_dedup else {}
    company_index = _build_company_index(master_list) if fuzzy_company else {}

    for row in rows:
        email = _extract_email(row)
        if email is None:
            # No email field found; keep the row but warn once
            kept.append(row)
            continue

        company = _extract_company(row)
        row_domain = _extract_row_domain(row) or _extract_domain(email)

        # --- Check 1: Duplicate within this CSV ---
        if email in seen_in_csv:
            skipped.append(row)
            dedup_log.append({
                "email": email,
                "reason": "duplicate_in_csv",
                "details": f"Already appears earlier in {os.path.basename(csv_path)}",
            })
            continue
        seen_in_csv.add(email)

        # --- Check 2: Exact email match in master list within cooldown ---
        entry = master_list.get(email)
        if entry:
            last_contacted = entry.get("last_contacted")
            if last_contacted:
                try:
                    last_dt = datetime.fromisoformat(last_contacted)
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    if last_dt >= cutoff:
                        days_ago = (now - last_dt).days
                        campaigns = ", ".join(entry.get("campaigns", [])[-3:])
                        skipped.append(row)
                        dedup_log.append({
                            "email": email,
                            "reason": "email_cooldown",
                            "details": (
                                f"Contacted {days_ago}d ago (cooldown: {effective_cooldown}d). "
                                f"Previous campaigns: {campaigns}"
                            ),
                        })
                        continue
                except (ValueError, TypeError):
                    pass

        # --- Check 3: Domain-level dedup ---
        if domain_dedup and row_domain and row_domain not in seen_domains_in_csv:
            domain_emails = domain_index.get(row_domain, [])
            for existing_email in domain_emails:
                if existing_email == email:
                    continue  # Skip self
                existing_entry = master_list.get(existing_email, {})
                last_contacted = existing_entry.get("last_contacted")
                if last_contacted:
                    try:
                        last_dt = datetime.fromisoformat(last_contacted)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        if last_dt >= cutoff:
                            days_ago = (now - last_dt).days
                            skipped.append(row)
                            dedup_log.append({
                                "email": email,
                                "reason": "domain_dedup",
                                "details": (
                                    f"Another contact at {row_domain} ({existing_email}) "
                                    f"was contacted {days_ago}d ago"
                                ),
                            })
                            break
                    except (ValueError, TypeError):
                        pass
            else:
                # Only reach here if inner loop did NOT break (no domain match found)
                pass

            if dedup_log and dedup_log[-1].get("email") == email and dedup_log[-1].get("reason") == "domain_dedup":
                # Was deduped by domain check above
                continue

        if row_domain:
            seen_domains_in_csv.add(row_domain)

        # --- Check 4: Fuzzy company name match ---
        if fuzzy_company and company:
            normalized = normalize_company_name(company)
            if normalized and normalized in company_index:
                company_emails = company_index[normalized]
                for existing_email in company_emails:
                    if existing_email == email:
                        continue
                    existing_entry = master_list.get(existing_email, {})
                    last_contacted = existing_entry.get("last_contacted")
                    if last_contacted:
                        try:
                            last_dt = datetime.fromisoformat(last_contacted)
                            if last_dt.tzinfo is None:
                                last_dt = last_dt.replace(tzinfo=timezone.utc)
                            if last_dt >= cutoff:
                                days_ago = (now - last_dt).days
                                orig_company = existing_entry.get("company_name", "?")
                                skipped.append(row)
                                dedup_log.append({
                                    "email": email,
                                    "reason": "fuzzy_company_match",
                                    "details": (
                                        f'"{company}" matches "{orig_company}" '
                                        f"(normalized: \"{normalized}\"). "
                                        f"Contact {existing_email} was reached {days_ago}d ago"
                                    ),
                                })
                                break
                        except (ValueError, TypeError):
                            pass

                if dedup_log and dedup_log[-1].get("email") == email and dedup_log[-1].get("reason") == "fuzzy_company_match":
                    continue

        kept.append(row)

    # Summary
    print(
        f"Deduped {csv_path}: {len(kept)} kept, {len(skipped)} skipped "
        f"(cooldown: {effective_cooldown}d, domain_dedup: {domain_dedup}, fuzzy: {fuzzy_company})"
    )

    # Print dedup reasons summary
    if dedup_log:
        reasons = {}
        for entry in dedup_log:
            r = entry["reason"]
            reasons[r] = reasons.get(r, 0) + 1
        reason_parts = [f"{v} {k.replace('_', ' ')}" for k, v in sorted(reasons.items(), key=lambda x: -x[1])]
        print(f"  Dedup breakdown: {', '.join(reason_parts)}")

    return kept, skipped, dedup_log


def register_contacts(emails, campaign_name, master_list, company_names=None):
    """Add or update contacts in the master list with the current timestamp and campaign.

    Args:
        emails: List of email address strings to register.
        campaign_name: Name of the campaign these contacts are part of.
        master_list: The master prospect dict (modified in place).
        company_names: Optional dict of {email: company_name} for company tracking.

    Returns:
        The updated master_list.
    """
    now_iso = datetime.now(timezone.utc).isoformat()
    company_names = company_names or {}

    for raw_email in emails:
        email = raw_email.strip().lower()
        if not email:
            continue

        company = company_names.get(email, "")

        if email in master_list:
            entry = master_list[email]
            entry["last_contacted"] = now_iso
            if campaign_name and campaign_name not in entry["campaigns"]:
                entry["campaigns"].append(campaign_name)
            if company and not entry.get("company_name"):
                entry["company_name"] = company
        else:
            master_list[email] = {
                "campaigns": [campaign_name] if campaign_name else [],
                "first_seen": now_iso,
                "last_contacted": now_iso,
                "domain": _extract_domain(email),
                "company_name": company,
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


def _save_dedup_log(dedup_log, output_dir="output"):
    """Save the dedup log to a JSON file for audit trail.

    Args:
        dedup_log: List of dedup log entries.
        output_dir: Directory to write the log file.
    """
    if not dedup_log:
        return
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    path = os.path.join(output_dir, f"dedup_log_{timestamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dedup_log, f, indent=2)
    print(f"  Dedup log saved to {path}")


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
        default=None,
        help="Override cooldown period in days (default: auto-detect by campaign type)",
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
    parser.add_argument(
        "--no-domain-dedup",
        action="store_true",
        help="Disable domain-level deduplication",
    )
    parser.add_argument(
        "--no-fuzzy",
        action="store_true",
        help="Disable fuzzy company name matching",
    )
    parser.add_argument(
        "--save-log",
        action="store_true",
        help="Save detailed dedup log to output/dedup_log_*.json",
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
        all_dedup_logs = []

        for csv_path in args.csvs:
            kept, skipped, dedup_log = deduplicate_csv(
                csv_path, master_list,
                cooldown_days=args.cooldown,
                domain_dedup=not args.no_domain_dedup,
                fuzzy_company=not args.no_fuzzy,
            )

            all_dedup_logs.extend(dedup_log)

            if not kept and not skipped:
                continue

            total_kept += len(kept)
            total_skipped += len(skipped)

            # Print detailed dedup reasons for verbose output
            if dedup_log and len(dedup_log) <= 20:
                for entry in dedup_log:
                    print(f"    SKIP {entry['email']}: {entry['reason']} - {entry['details']}")
            elif dedup_log:
                for entry in dedup_log[:10]:
                    print(f"    SKIP {entry['email']}: {entry['reason']} - {entry['details']}")
                print(f"    ... and {len(dedup_log) - 10} more")

            if not args.dry_run:
                # Overwrite the CSV with kept rows only
                if kept:
                    fieldnames = list(kept[0].keys())
                    _write_csv(csv_path, kept, fieldnames)

                # Register kept contacts in master list
                kept_emails = [_extract_email(row) for row in kept]
                kept_emails = [e for e in kept_emails if e is not None]
                # Also track company names for fuzzy matching
                company_map = {}
                for row in kept:
                    e = _extract_email(row)
                    c = _extract_company(row)
                    if e and c:
                        company_map[e] = c
                campaign_name = _infer_campaign_name(csv_path)
                register_contacts(kept_emails, campaign_name, master_list,
                                  company_names=company_map)

        # Print overall summary
        print(f"\nTotal across all files: {total_kept} kept, {total_skipped} skipped")

        # Print overall dedup reason breakdown
        if all_dedup_logs:
            reasons = {}
            for entry in all_dedup_logs:
                r = entry["reason"]
                reasons[r] = reasons.get(r, 0) + 1
            print("Dedup reasons across all files:")
            for reason, count in sorted(reasons.items(), key=lambda x: -x[1]):
                print(f"  {reason.replace('_', ' ')}: {count}")

        # Save log if requested
        if args.save_log and all_dedup_logs:
            _save_dedup_log(all_dedup_logs)

        if not args.dry_run:
            save_master_list(master_list, args.master_list)
            print(f"Master list saved to {args.master_list} ({len(master_list)} prospects)")
        else:
            print("[DRY RUN] No files were modified")


if __name__ == "__main__":
    main()
