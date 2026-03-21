#!/usr/bin/env python3
"""
Upload NS campaign emails to Instantly.ai
Creates campaign(s) in DRAFT mode and uploads all leads with custom emails.
Accepts both personal and generic emails (info@, contact@ etc.) since
these are small local businesses where the owner checks generic inboxes.
"""

import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

import requests

CONFIG_PATH = "config.json"
INPUT_FILE = "output/ns_campaign_emails.csv"
BASE_URL = "https://api.instantly.ai/api/v2"
RATE_LIMIT_DELAY = 1

# Campaign settings
CAMPAIGN_PREFIX = "Realside AI — NS Local"
BATCH_LIMIT = 100  # Leads per campaign (Instantly works better with smaller campaigns)


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_request(method, endpoint, api_key, data=None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(4):
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported: {method}")

            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}

            return resp.json() if resp.text else {}

        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                return {"error": str(e)}

    return {"error": "Max retries exceeded"}


def get_sending_accounts(api_key):
    result = api_request("GET", "/accounts", api_key, {"limit": 50})
    if "error" in result:
        print(f"  Warning: Could not fetch accounts: {result['error'][:100]}")
        return []
    accounts = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(accounts, dict) and "items" in accounts:
        accounts = accounts["items"]
    if isinstance(accounts, list):
        emails = [a.get("email", "") for a in accounts if a.get("email")]
        return emails
    return []


def create_campaign(api_key, name, sending_accounts, opts):
    timezone = opts.get("timezone", "America/Chicago")
    daily_limit = opts.get("daily_limit_per_account", 30)
    duration_days = opts.get("campaign_duration_days", 90)

    morning_start = opts.get("morning_start", "07:00")
    morning_end = opts.get("morning_end", "09:00")
    afternoon_start = opts.get("afternoon_start", "13:00")
    afternoon_end = opts.get("afternoon_end", "15:00")

    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")

    weekdays = {"0": False, "1": True, "2": True, "3": True, "4": True, "5": True, "6": False}

    payload = {
        "name": name,
        "campaign_schedule": {
            "start_date": start_date,
            "end_date": end_date,
            "schedules": [
                {
                    "name": "Morning",
                    "timing": {"from": morning_start, "to": morning_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
                {
                    "name": "Afternoon",
                    "timing": {"from": afternoon_start, "to": afternoon_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
            ],
        },
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

    if sending_accounts:
        payload["sending_accounts"] = sending_accounts

    campaign_settings = {
        "daily_limit": daily_limit,
        "link_tracking": False,
        "open_tracking": True,
    }
    payload["campaign_settings"] = campaign_settings

    result = api_request("POST", "/campaigns", api_key, payload)
    if "error" in result:
        print(f"  Failed to create campaign '{name}': {result['error'][:200]}")
        return ""

    campaign_id = result.get("id", "")
    if campaign_id:
        print(f"  Created campaign: {name} (ID: {campaign_id})")
    return campaign_id


def upload_lead(api_key, campaign_id, lead):
    payload = {
        "campaign": campaign_id,
        "email": lead["email"],
        "company_name": lead.get("company_name", ""),
        "website": lead.get("domain", ""),
        "custom_variables": {
            "custom_subject": lead.get("subject", ""),
            "custom_body": lead.get("body", ""),
            "category": lead.get("category", ""),
            "city": lead.get("city", ""),
        },
    }

    result = api_request("POST", "/leads", api_key, payload)
    if "error" in result:
        return False, result["error"][:100]
    return True, ""


def main():
    dry_run = "--dry-run" in sys.argv

    print("=== NS Campaign Uploader to Instantly ===\n")

    config = load_config()
    api_key = config.get("instantly_api_key", "")
    if not api_key:
        print("ERROR: No instantly_api_key in config.json")
        sys.exit(1)

    campaign_opts = config.get("campaign_options", {})

    # Load emails
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get('email', '').strip() and row.get('subject', '').strip():
                leads.append(row)

    print(f"Loaded {len(leads)} leads with emails + subjects")

    if not leads:
        print("No leads to upload!")
        return

    # Get sending accounts
    if not dry_run:
        accounts = get_sending_accounts(api_key)
        print(f"Found {len(accounts)} sending accounts: {accounts}")
    else:
        accounts = []

    # Split into category-based campaigns for better tracking
    # Group by high-level category
    category_groups = {
        "Dental": ["Dentist", "Dental clinic", "Orthodontist"],
        "Medical Spa & Beauty": ["Medical spa", "Beauty salon", "Hair salon", "Hairdresser",
                                  "Nail salon", "Barber shop", "Skin care clinic",
                                  "Laser hair removal service", "Facial spa"],
        "Health & Wellness": ["Chiropractor", "Massage therapist", "Physical therapist",
                              "Physical therapy clinic", "Wellness center", "Spa", "Day spa",
                              "Health spa", "Acupuncture clinic", "Naturopathic practitioner",
                              "Osteopath", "Medical clinic"],
        "Eye Care": ["Optometrist", "Eye care center"],
        "Mental Health": ["Counselor", "Psychologist", "Mental health service",
                          "Psychotherapist", "Mental health clinic", "Addiction treatment center"],
    }

    # Reverse map: category -> group name
    cat_to_group = {}
    for group, cats in category_groups.items():
        for cat in cats:
            cat_to_group[cat] = group

    # Group leads
    grouped = {}
    for lead in leads:
        group = cat_to_group.get(lead.get("category", ""), "Other")
        if group not in grouped:
            grouped[group] = []
        grouped[group].append(lead)

    print(f"\nCampaign breakdown:")
    for group, group_leads in sorted(grouped.items(), key=lambda x: -len(x[1])):
        print(f"  {CAMPAIGN_PREFIX} {group}: {len(group_leads)} leads")

    if dry_run:
        print(f"\n[DRY RUN] Would create {len(grouped)} campaigns with {len(leads)} total leads")
        return

    # Create campaigns and upload
    total_uploaded = 0
    total_failed = 0

    for group, group_leads in grouped.items():
        campaign_name = f"{CAMPAIGN_PREFIX} {group}"
        print(f"\n{'='*50}")
        print(f"Campaign: {campaign_name} ({len(group_leads)} leads)")

        campaign_id = create_campaign(api_key, campaign_name, accounts, campaign_opts)
        if not campaign_id:
            print(f"  SKIPPED: Could not create campaign")
            total_failed += len(group_leads)
            continue

        uploaded = 0
        failed = 0
        for i, lead in enumerate(group_leads):
            success, error = upload_lead(api_key, campaign_id, lead)
            if success:
                uploaded += 1
            else:
                failed += 1
                if failed <= 3:
                    print(f"  Failed: {lead['email']} - {error}")

            if (i + 1) % 5 == 0:
                time.sleep(RATE_LIMIT_DELAY)
            if (i + 1) % 25 == 0:
                print(f"  Progress: {uploaded}/{i+1} uploaded...")

        print(f"  Done: {uploaded} uploaded, {failed} failed")
        total_uploaded += uploaded
        total_failed += failed

    print(f"\n{'='*50}")
    print(f"=== Upload Complete ===")
    print(f"Total uploaded: {total_uploaded}")
    print(f"Total failed: {total_failed}")
    print(f"Campaigns created: {len(grouped)} (all in DRAFT mode)")
    print(f"\nGo to Instantly.ai dashboard to review and activate campaigns.")


if __name__ == "__main__":
    main()
