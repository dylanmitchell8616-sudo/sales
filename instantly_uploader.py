#!/usr/bin/env python3
"""
Instantly.ai Campaign Uploader
===============================
Takes pipeline output CSVs and uploads them as campaigns to Instantly.ai
with fully custom per-lead emails using custom variables.

Usage:
    python instantly_uploader.py --api-key YOUR_KEY
    python instantly_uploader.py --api-key YOUR_KEY --csvs output/prospect_emails.csv output/case_study_emails.csv
    python instantly_uploader.py --api-key YOUR_KEY --list-campaigns
    python instantly_uploader.py --api-key YOUR_KEY --dry-run
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

BASE_URL = "https://api.instantly.ai/api/v2"
DEFAULT_TIMEZONE = "America/Chicago"
BATCH_SIZE = 50  # leads per API call
RATE_LIMIT_DELAY = 1  # seconds between API calls

# Optimal cold-email sending defaults
DEFAULT_DAILY_LIMIT_PER_ACCOUNT = 30  # conservative to protect deliverability
DEFAULT_REPLY_TO_PERCENTAGE = 100  # reply tracking
DEFAULT_OPEN_TRACKING = True
DEFAULT_LINK_TRACKING = False  # link tracking hurts deliverability

# Map CSV filenames to campaign names
CAMPAIGN_NAMES = {
    "prospect_emails.csv": "Realside AI — Prospect Outreach",
    "case_study_emails.csv": "Realside AI — Case Study Match",
    "news_triggered_emails.csv": "Realside AI — News Trigger",
    "displacement_emails.csv": "Realside AI — Competitor Displacement",
    "social_outreach_emails.csv": "Realside AI — Social Warm Outreach",
    "job_signal_emails.csv": "Realside AI — Job Signal Outreach",
    "event_outreach_emails.csv": "Realside AI — Event Outreach",
    "followup_sequences.csv": "Realside AI — Follow-up Sequences",
    "objection_responses.csv": "Realside AI — Objection Responses",
    "engaged_followups.csv": "Realside AI — Engaged Follow-ups",
}


def api_request(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    """Make an authenticated request to the Instantly API."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(4):
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            elif method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                print(f"  API error {resp.status_code}: {resp.text[:300]}")
                return {"error": resp.text, "status_code": resp.status_code}

            return resp.json() if resp.text else {}

        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after 4 attempts: {e}")
                return {"error": str(e)}

    return {"error": "Max retries exceeded"}


def list_campaigns(api_key: str):
    """List existing campaigns."""
    result = api_request("GET", "/campaigns", api_key, {"limit": 50})
    if "error" in result:
        print(f"Error listing campaigns: {result['error']}")
        return []

    campaigns = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(campaigns, list):
        for c in campaigns:
            status = c.get("status", "unknown")
            name = c.get("name", "Unnamed")
            cid = c.get("id", "?")
            print(f"  [{status}] {name} (ID: {cid})")
        return campaigns
    elif isinstance(campaigns, dict) and "items" in campaigns:
        for c in campaigns["items"]:
            status = c.get("status", "unknown")
            name = c.get("name", "Unnamed")
            cid = c.get("id", "?")
            print(f"  [{status}] {name} (ID: {cid})")
        return campaigns["items"]
    else:
        print(f"  Response: {json.dumps(result, indent=2)[:500]}")
        return []


def list_accounts(api_key: str) -> list:
    """List connected email accounts."""
    result = api_request("GET", "/accounts", api_key, {"limit": 50})
    if "error" in result:
        print(f"Error listing accounts: {result['error']}")
        return []

    accounts = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(accounts, list):
        return accounts
    elif isinstance(accounts, dict) and "items" in accounts:
        return accounts["items"]
    return []


def create_campaign(api_key: str, name: str, sending_accounts: list = None,
                    campaign_options: dict = None) -> str:
    """Create a new campaign with optimized settings for cold email deliverability.

    Optimizations:
    - Two send windows: morning (7-9 AM) + afternoon (1-3 PM) — peak open times
    - Mon-Fri only, no weekends
    - All sending accounts rotated for volume + deliverability
    - Conservative daily limits per account (30/day default)
    - Link tracking OFF (hurts deliverability), open tracking ON
    - 90-day campaign duration
    """
    opts = campaign_options or {}
    timezone = opts.get("timezone", DEFAULT_TIMEZONE)
    daily_limit = opts.get("daily_limit_per_account", DEFAULT_DAILY_LIMIT_PER_ACCOUNT)
    duration_days = opts.get("campaign_duration_days", 90)

    # Send windows — split into two blocks for natural spacing
    morning_start = opts.get("morning_start", "07:00")
    morning_end = opts.get("morning_end", "09:00")
    afternoon_start = opts.get("afternoon_start", "13:00")
    afternoon_end = opts.get("afternoon_end", "15:00")

    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")

    weekdays = {
        "0": False,  # Sunday
        "1": True,   # Monday
        "2": True,   # Tuesday
        "3": True,   # Wednesday
        "4": True,   # Thursday
        "5": True,   # Friday
        "6": False,  # Saturday
    }

    payload = {
        "name": name,
        "campaign_schedule": {
            "start_date": start_date,
            "end_date": end_date,
            "schedules": [
                {
                    "name": "Morning Window (7-9 AM)",
                    "timing": {"from": morning_start, "to": morning_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
                {
                    "name": "Afternoon Window (1-3 PM)",
                    "timing": {"from": afternoon_start, "to": afternoon_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
            ],
        },
        # Use custom variables so each lead gets a fully unique email
        "sequences": [
            {
                "steps": [
                    {
                        "type": "email",
                        "delay": 0,
                        "variants": [
                            {
                                "subject": "{{custom_subject}}",
                                "body": "{{custom_body}}",
                            }
                        ],
                    }
                ]
            }
        ],
    }

    # Attach ALL sending accounts for rotation (spreads volume, protects domains)
    if sending_accounts:
        payload["sending_accounts"] = sending_accounts
        print(f"  Rotating across {len(sending_accounts)} sending accounts")

    # Campaign-level settings (daily limit, tracking)
    campaign_settings = {}
    if daily_limit:
        campaign_settings["daily_limit"] = daily_limit
    if not opts.get("link_tracking", DEFAULT_LINK_TRACKING):
        campaign_settings["link_tracking"] = False
    if opts.get("open_tracking", DEFAULT_OPEN_TRACKING):
        campaign_settings["open_tracking"] = True
    if campaign_settings:
        payload["campaign_settings"] = campaign_settings

    result = api_request("POST", "/campaigns", api_key, payload)
    if "error" in result:
        print(f"  Failed to create campaign '{name}': {result['error']}")
        return ""

    campaign_id = result.get("id", "")
    if campaign_id:
        print(f"  Created campaign: {name} (ID: {campaign_id})")
        print(f"    Schedule: {morning_start}-{morning_end} + {afternoon_start}-{afternoon_end} Mon-Fri ({timezone})")
        print(f"    Daily limit/account: {daily_limit} | Duration: {duration_days} days")
    return campaign_id


def read_pipeline_csv(filepath: str) -> list[dict]:
    """Read a pipeline output CSV and normalize column names."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def csv_to_leads(rows: list[dict]) -> list[dict]:
    """Convert pipeline CSV rows to Instantly lead format with custom variables."""
    leads = []
    for row in rows:
        # Extract contact info — handle different column name conventions
        email = (
            row.get("contact_email", "")
            or row.get("email", "")
            or row.get("prospect_email", "")
        )
        first_name = ""
        last_name = ""
        contact_name = (
            row.get("contact_name", "")
            or row.get("prospect_contact", "")
            or ""
        )
        if contact_name:
            parts = contact_name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

        company = (
            row.get("company_name", "")
            or row.get("prospect_company", "")
            or ""
        )
        domain = row.get("domain", "")
        subject = row.get("subject", "")
        body = row.get("body", "")
        title = row.get("contact_title", "")
        personalization = row.get("personalization_hook", "")

        # Build the lead object
        lead = {
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company,
            "website": domain if domain and not domain.startswith("http") else domain,
            "custom_variables": {
                "custom_subject": subject,
                "custom_body": body,
                "contact_title": title,
                "personalization_hook": personalization,
                "domain": domain,
                "full_name": contact_name,
            },
        }

        # Set email — real email, domain placeholder, or skip if neither exists
        if email:
            lead["email"] = email
        elif domain:
            # Placeholder — user should enrich with real emails before sending
            lead["email"] = f"contact@{domain}"
            lead["custom_variables"]["needs_real_email"] = "true"
        else:
            # No email and no domain — skip this lead
            continue

        leads.append(lead)

    return leads


def upload_leads(api_key: str, campaign_id: str, leads: list[dict]) -> int:
    """Upload leads one at a time to a campaign (Instantly V2 API format)."""
    total_uploaded = 0

    for i, lead in enumerate(leads):
        payload = {
            "campaign": campaign_id,
            "email": lead.get("email", ""),
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company_name", ""),
            "website": lead.get("website", ""),
            "personalization": lead.get("custom_variables", {}).get("personalization_hook", ""),
            "custom_variables": lead.get("custom_variables", {}),
        }

        result = api_request("POST", "/leads", api_key, payload)
        if "error" in result:
            print(f"  Error uploading lead {i + 1} ({lead.get('email', '?')}): {result['error'][:100]}")
        else:
            total_uploaded += 1

        # Rate limit every 5 leads
        if (i + 1) % 5 == 0:
            time.sleep(RATE_LIMIT_DELAY)
            if (i + 1) % 20 == 0:
                print(f"  Uploaded {total_uploaded}/{i + 1} leads...")

    return total_uploaded


def process_csv(api_key: str, csv_path: str, dry_run: bool = False,
                sending_accounts: list = None, campaign_options: dict = None) -> dict:
    """Process a single CSV: create campaign + upload leads."""
    filename = os.path.basename(csv_path)
    campaign_name = CAMPAIGN_NAMES.get(filename, f"Realside AI — {filename.replace('.csv', '').replace('_', ' ').title()}")

    print(f"\n{'='*60}")
    print(f"Processing: {filename}")
    print(f"Campaign:   {campaign_name}")
    print(f"{'='*60}")

    # Read CSV
    rows = read_pipeline_csv(csv_path)
    if not rows:
        print("  No rows found, skipping.")
        return {"name": campaign_name, "status": "skipped", "reason": "empty CSV"}

    # Convert to leads
    leads = csv_to_leads(rows)
    needs_email = sum(1 for l in leads if l.get("custom_variables", {}).get("needs_real_email") == "true")

    print(f"  Leads: {len(leads)} total")
    if needs_email:
        print(f"  ⚠ {needs_email} leads have placeholder emails (need enrichment)")

    if dry_run:
        print("  [DRY-RUN] Would create campaign and upload leads")
        opts = campaign_options or {}
        tz = opts.get("timezone", DEFAULT_TIMEZONE)
        dl = opts.get("daily_limit_per_account", DEFAULT_DAILY_LIMIT_PER_ACCOUNT)
        ms = opts.get("morning_start", "07:00")
        me = opts.get("morning_end", "09:00")
        a_s = opts.get("afternoon_start", "13:00")
        ae = opts.get("afternoon_end", "15:00")
        num_accounts = len(sending_accounts) if sending_accounts else 0
        print(f"    Schedule: {ms}-{me} + {a_s}-{ae} Mon-Fri ({tz})")
        print(f"    Sending accounts: {num_accounts} | Daily limit/account: {dl}")
        for i, lead in enumerate(leads[:3]):
            print(f"    Lead {i+1}: {lead.get('first_name', '?')} {lead.get('last_name', '')} "
                  f"@ {lead.get('company_name', '?')} ({lead.get('email', 'no email')})")
            print(f"      Subject: {lead['custom_variables']['custom_subject'][:60]}...")
        if len(leads) > 3:
            print(f"    ... and {len(leads) - 3} more")
        return {"name": campaign_name, "status": "dry-run", "leads": len(leads)}

    # Create campaign with optimized settings
    campaign_id = create_campaign(api_key, campaign_name, sending_accounts, campaign_options)
    if not campaign_id:
        return {"name": campaign_name, "status": "failed", "reason": "campaign creation failed"}

    # Upload leads
    uploaded = upload_leads(api_key, campaign_id, leads)
    print(f"  Total uploaded: {uploaded}/{len(leads)}")

    return {
        "name": campaign_name,
        "campaign_id": campaign_id,
        "status": "success",
        "leads_uploaded": uploaded,
        "leads_total": len(leads),
        "needs_email_enrichment": needs_email,
    }


def main():
    parser = argparse.ArgumentParser(description="Upload pipeline emails to Instantly.ai")
    parser.add_argument("--api-key", required=True, help="Instantly API key (Bearer token)")
    parser.add_argument("--csvs", nargs="*", help="Specific CSV files to upload (default: all in output/)")
    parser.add_argument("--output-dir", default="output", help="Pipeline output directory")
    parser.add_argument("--sending-account", default=None, help="Email account to send from")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating campaigns")
    parser.add_argument("--campaign-options", default=None,
                        help="JSON string of campaign options (timezone, daily_limit_per_account, etc.)")
    parser.add_argument("--list-campaigns", action="store_true", help="List existing campaigns")
    parser.add_argument("--list-accounts", action="store_true", help="List connected email accounts")
    args = parser.parse_args()

    if args.list_campaigns:
        print("Existing campaigns:")
        list_campaigns(args.api_key)
        return

    if args.list_accounts:
        print("Connected email accounts:")
        accounts = list_accounts(args.api_key)
        for a in accounts:
            email = a.get("email", "?")
            status = a.get("status", "unknown")
            print(f"  [{status}] {email}")
        return

    # Determine which CSVs to upload
    if args.csvs:
        csv_files = args.csvs
    else:
        output_dir = args.output_dir
        csv_files = []
        for f in sorted(os.listdir(output_dir)):
            if f.endswith(".csv") and not f.startswith("_") and f in CAMPAIGN_NAMES:
                csv_files.append(os.path.join(output_dir, f))

    if not csv_files:
        print("No CSV files found to upload.")
        print(f"Expected files in {args.output_dir}/: {', '.join(CAMPAIGN_NAMES.keys())}")
        sys.exit(1)

    print(f"Instantly.ai Campaign Uploader")
    print(f"{'='*60}")
    print(f"Files to process: {len(csv_files)}")
    if args.dry_run:
        print("Mode: DRY-RUN (no changes will be made)")
    print()

    # Check API connectivity
    print("Checking API access...")
    accounts = list_accounts(args.api_key)
    if not accounts:
        print("Warning: Could not list accounts. Check your API key and permissions.")
    else:
        print(f"  Found {len(accounts)} connected account(s)")
        for a in accounts:
            print(f"    - {a.get('email', '?')}")

    # Collect ALL sending accounts for rotation (maximizes volume + deliverability)
    if args.sending_account:
        sending_accounts = [args.sending_account]
    elif accounts:
        sending_accounts = [a.get("email", "") for a in accounts if a.get("email")]
        print(f"  Rotating across ALL {len(sending_accounts)} connected accounts")
    else:
        sending_accounts = []

    # Campaign options (can be overridden via --campaign-options JSON)
    campaign_options = {
        "timezone": DEFAULT_TIMEZONE,
        "daily_limit_per_account": DEFAULT_DAILY_LIMIT_PER_ACCOUNT,
        "campaign_duration_days": 90,
        "morning_start": "07:00",
        "morning_end": "09:00",
        "afternoon_start": "13:00",
        "afternoon_end": "15:00",
        "open_tracking": DEFAULT_OPEN_TRACKING,
        "link_tracking": DEFAULT_LINK_TRACKING,
    }
    if args.campaign_options:
        try:
            overrides = json.loads(args.campaign_options)
            campaign_options.update(overrides)
            print(f"  Campaign options overridden: {list(overrides.keys())}")
        except json.JSONDecodeError:
            print(f"  Warning: Could not parse --campaign-options JSON, using defaults")

    # Process each CSV
    results = []
    for csv_path in csv_files:
        if not os.path.exists(csv_path):
            print(f"\n  Skipping {csv_path} (file not found)")
            continue
        result = process_csv(args.api_key, csv_path, args.dry_run, sending_accounts, campaign_options)
        results.append(result)

    # Summary
    print(f"\n{'='*60}")
    print("UPLOAD SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status_icon = "✓" if r["status"] == "success" else "○" if r["status"] == "dry-run" else "✗"
        print(f"  [{status_icon}] {r['name']}: {r['status']}")
        if r.get("leads_uploaded"):
            print(f"      {r['leads_uploaded']}/{r['leads_total']} leads uploaded")
        if r.get("needs_email_enrichment", 0) > 0:
            print(f"      ⚠ {r['needs_email_enrichment']} leads need real email addresses")
        if r.get("campaign_id"):
            print(f"      Campaign ID: {r['campaign_id']}")

    print(f"\n⚠ IMPORTANT: Campaigns are created in DRAFT mode.")
    print(f"  → Log in to Instantly.ai to review and activate each campaign.")
    print(f"  → Leads with placeholder emails (contact@domain.com) need real addresses.")
    print()


if __name__ == "__main__":
    main()
