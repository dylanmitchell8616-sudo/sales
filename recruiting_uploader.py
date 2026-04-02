#!/usr/bin/env python3
"""
AI Recruiting Campaign Uploader
=================================
Takes the output from recruiting_campaign_generator.py and uploads it to
Instantly.ai as a 3-step sequence campaign with per-lead custom variables.

Usage:
    python recruiting_uploader.py --input output/recruiting_social_proof.csv
    python recruiting_uploader.py --input output/recruiting_social_proof.csv --dry-run
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
BASE_URL = "https://api.instantly.ai/api/v2"
CAMPAIGN_NAME = "AI Recruiting - Social Proof"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_request(method, endpoint, api_key, payload=None, params=None):
    """Make an authenticated API request to Instantly."""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    try:
        if method == "GET":
            resp = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            resp = requests.post(url, headers=headers, json=payload, timeout=30)
        elif method == "DELETE":
            del headers["Content-Type"]
            resp = requests.delete(url, headers=headers, timeout=30)
        else:
            return {"error": f"Unknown method: {method}"}

        if resp.status_code in (200, 201, 204):
            return resp.json() if resp.text else {}
        return {"error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
    except Exception as e:
        return {"error": str(e)}


def list_accounts(api_key):
    """Get all connected sending accounts."""
    result = api_request("GET", "/accounts", api_key, params={"limit": 100})
    if isinstance(result, list):
        return [a.get("email", "") for a in result if a.get("email")]
    if isinstance(result, dict):
        items = result.get("data", result.get("items", []))
        return [a.get("email", "") for a in items if a.get("email")]
    return []


def find_existing_campaign(api_key):
    """Check if campaign already exists."""
    result = api_request("GET", "/campaigns", api_key, params={"limit": 100})
    campaigns = result if isinstance(result, list) else result.get("data", result.get("items", []))
    for c in campaigns:
        if c.get("name") == CAMPAIGN_NAME:
            return c.get("id")
    return None


def create_campaign(api_key, sending_accounts, config):
    """Create the 3-step sequence campaign."""
    opts = config.get("campaign_options", {})
    timezone = opts.get("timezone", "America/Chicago")
    daily_limit = opts.get("daily_limit_per_account", 30)
    duration_days = opts.get("campaign_duration_days", 90)

    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")

    weekdays = {"0": False, "1": True, "2": True, "3": True, "4": True, "5": True, "6": False}

    payload = {
        "name": CAMPAIGN_NAME,
        "campaign_schedule": {
            "start_date": start_date,
            "end_date": end_date,
            "schedules": [
                {
                    "name": "Morning Window (7-9 AM)",
                    "timing": {"from": opts.get("morning_start", "07:00"),
                               "to": opts.get("morning_end", "09:00")},
                    "timezone": timezone,
                    "days": weekdays,
                },
                {
                    "name": "Afternoon Window (1-3 PM)",
                    "timing": {"from": opts.get("afternoon_start", "13:00"),
                               "to": opts.get("afternoon_end", "15:00")},
                    "timezone": timezone,
                    "days": weekdays,
                },
            ],
        },
        "sequences": [
            {
                "steps": [
                    # Step 1: Initial email (Day 0)
                    {
                        "type": "email",
                        "delay": 0,
                        "variants": [
                            {
                                "subject": "{{custom_subject_1}}",
                                "body": "{{custom_body_1}}",
                            }
                        ],
                    },
                    # Step 2: Follow-up (Day 3)
                    {
                        "type": "email",
                        "delay": 3,
                        "variants": [
                            {
                                "subject": "{{custom_subject_2}}",
                                "body": "{{custom_body_2}}",
                            }
                        ],
                    },
                    # Step 3: Last shot (Day 7)
                    {
                        "type": "email",
                        "delay": 4,
                        "variants": [
                            {
                                "subject": "{{custom_subject_3}}",
                                "body": "{{custom_body_3}}",
                            }
                        ],
                    },
                ]
            }
        ],
        "sending_accounts": sending_accounts,
        "campaign_settings": {
            "daily_limit": daily_limit,
            "open_tracking": opts.get("open_tracking", True),
            "link_tracking": opts.get("link_tracking", False),
        },
    }

    result = api_request("POST", "/campaigns", api_key, payload)
    if "error" in result:
        print(f"  Error creating campaign: {result['error']}")
        return None
    return result.get("id")


def upload_leads(api_key, campaign_id, leads, dry_run=False):
    """Upload leads with per-step custom variables."""
    uploaded = 0
    skipped = 0

    for i, lead in enumerate(leads):
        email = lead.get("email", "")
        if not email:
            skipped += 1
            continue

        payload = {
            "campaign": campaign_id,
            "email": email,
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company_name", ""),
            "website": lead.get("domain", ""),
            "personalization": lead.get("custom_first_line", ""),
            "custom_variables": lead.get("custom_variables", {}),
        }

        if dry_run:
            if i < 3:
                print(f"  [DRY-RUN] Would upload: {email} ({lead.get('company_name', '')})")
            uploaded += 1
            continue

        result = api_request("POST", "/leads", api_key, payload)
        if "error" in result:
            print(f"  Error uploading {email}: {result['error'][:100]}")
            skipped += 1
        else:
            uploaded += 1

        # Rate limiting: pause every 5 leads
        if (i + 1) % 5 == 0:
            time.sleep(1)

        if (i + 1) % 500 == 0:
            print(f"  Uploaded {i + 1}/{len(leads)}...")

    return uploaded, skipped


def main():
    parser = argparse.ArgumentParser(description="AI Recruiting Campaign Uploader")
    parser.add_argument("--input", required=True, help="Path to recruiting_social_proof.csv")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to config.json")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    config = load_config()
    api_key = config.get("instantly_api_key", "")
    if not api_key:
        print("Error: No instantly_api_key in config.json")
        sys.exit(1)

    print(f"\nAI Recruiting Campaign Uploader")
    print(f"{'='*60}")
    print(f"Campaign: {CAMPAIGN_NAME}")
    print(f"Input:    {args.input}")
    print(f"Mode:     {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    # Read the CSV and group by email (3 steps per lead)
    with open(args.input, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        all_rows = list(reader)

    # Group rows by email — each lead has 3 step rows
    lead_map = {}
    for row in all_rows:
        email = row.get("email", "").strip()
        if not email:
            continue
        if email not in lead_map:
            lead_map[email] = {
                "email": email,
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "company_name": row.get("company_name", ""),
                "domain": row.get("domain", ""),
                "custom_first_line": row.get("custom_first_line", ""),
                "custom_variables": {},
            }
        step = row.get("step_number", "1")
        lead_map[email]["custom_variables"][f"custom_subject_{step}"] = row.get("subject", "")
        lead_map[email]["custom_variables"][f"custom_body_{step}"] = row.get("body", "")

    leads = list(lead_map.values())
    print(f"Loaded {len(leads)} unique leads ({len(all_rows)} total rows across 3 steps)\n")

    # Get sending accounts
    accounts = list_accounts(api_key)
    print(f"Found {len(accounts)} sending accounts")

    # Check for existing campaign
    existing_id = find_existing_campaign(api_key)
    if existing_id:
        print(f"Found existing campaign: {CAMPAIGN_NAME} (ID: {existing_id})")
        campaign_id = existing_id
    else:
        if args.dry_run:
            print(f"[DRY-RUN] Would create campaign: {CAMPAIGN_NAME}")
            campaign_id = "dry-run-id"
        else:
            print(f"Creating campaign: {CAMPAIGN_NAME}...")
            campaign_id = create_campaign(api_key, accounts, config)
            if not campaign_id:
                print("Failed to create campaign. Exiting.")
                sys.exit(1)
            print(f"Created: {CAMPAIGN_NAME} (ID: {campaign_id})")

    # Upload leads
    print(f"\nUploading {len(leads)} leads...")
    uploaded, skipped = upload_leads(api_key, campaign_id, leads, dry_run=args.dry_run)

    print(f"\n{'='*60}")
    print(f"UPLOAD SUMMARY")
    print(f"{'='*60}")
    print(f"  Campaign: {CAMPAIGN_NAME}")
    print(f"  Uploaded: {uploaded}")
    print(f"  Skipped:  {skipped}")
    if not args.dry_run:
        print(f"  Campaign ID: {campaign_id}")
    print(f"\n  Campaign is in DRAFT mode.")
    print(f"  → Review and activate in Instantly.ai dashboard")


if __name__ == "__main__":
    main()
