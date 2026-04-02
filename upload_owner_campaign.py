#!/usr/bin/env python3
"""
Upload owner campaign with follow-up sequences to Instantly.
Creates campaigns with 4-step sequences (initial + 3 follow-ups).
"""

import csv
import json
import sys
import time
from datetime import datetime, timedelta
from collections import defaultdict

import requests

CONFIG_PATH = "config.json"
INPUT_FILE = "output/owner_campaign_emails.csv"
BASE_URL = "https://api.instantly.ai/api/v2"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_request(method, endpoint, api_key, data=None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

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
                time.sleep(2 ** (attempt + 1))
            else:
                return {"error": str(e)}
    return {"error": "Max retries exceeded"}


def get_sending_accounts(api_key):
    result = api_request("GET", "/accounts", api_key, {"limit": 50})
    if "error" in result:
        return []
    accounts = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(accounts, dict) and "items" in accounts:
        accounts = accounts["items"]
    if isinstance(accounts, list):
        return [a.get("email", "") for a in accounts if a.get("email")]
    return []


def create_campaign_with_sequence(api_key, name, sending_accounts, opts):
    """Create campaign with 4-step sequence using custom variables per step."""
    timezone = opts.get("timezone", "America/Chicago")
    daily_limit = opts.get("daily_limit_per_account", 30)
    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=90)).strftime("%Y-%m-%d")

    weekdays = {"0": False, "1": True, "2": True, "3": True, "4": True, "5": True, "6": False}

    payload = {
        "name": name,
        "campaign_schedule": {
            "start_date": start_date,
            "end_date": end_date,
            "schedules": [
                {
                    "name": "Morning",
                    "timing": {"from": "07:00", "to": "09:00"},
                    "timezone": timezone,
                    "days": weekdays,
                },
                {
                    "name": "Afternoon",
                    "timing": {"from": "13:00", "to": "15:00"},
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
                        "variants": [{"subject": "{{subject_1}}", "body": "{{body_1}}"}],
                    },
                    {
                        "type": "email",
                        "delay": 3,
                        "variants": [{"subject": "{{subject_2}}", "body": "{{body_2}}"}],
                    },
                    {
                        "type": "email",
                        "delay": 2,
                        "variants": [{"subject": "{{subject_3}}", "body": "{{body_3}}"}],
                    },
                    {
                        "type": "email",
                        "delay": 3,
                        "variants": [{"subject": "{{subject_4}}", "body": "{{body_4}}"}],
                    },
                ]
            }
        ],
        "campaign_settings": {
            "daily_limit": daily_limit,
            "link_tracking": False,
            "open_tracking": True,
        },
    }

    if sending_accounts:
        payload["sending_accounts"] = sending_accounts

    result = api_request("POST", "/campaigns", api_key, payload)
    if "error" in result:
        print(f"  Failed to create campaign: {result['error'][:200]}")
        return ""

    campaign_id = result.get("id", "")
    if campaign_id:
        print(f"  Created campaign: {name} (ID: {campaign_id})")
    return campaign_id


def main():
    dry_run = "--dry-run" in sys.argv

    print("=== Owner Campaign Uploader to Instantly ===\n")

    config = load_config()
    api_key = config.get("instantly_api_key", "")
    campaign_opts = config.get("campaign_options", {})

    # Load emails and group by owner (4 steps each)
    all_rows = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            all_rows.append(row)

    # Group by email (owner)
    owners = defaultdict(list)
    for row in all_rows:
        owners[row['email']].append(row)

    print(f"Loaded {len(owners)} owners with {len(all_rows)} total email steps")

    if not owners:
        print("No owners to upload!")
        return

    # Get sending accounts
    accounts = [] if dry_run else get_sending_accounts(api_key)
    print(f"Found {len(accounts)} sending accounts")

    # Create single campaign with all owners
    campaign_name = "Realside AI — Halifax Owners"

    if dry_run:
        print(f"\n[DRY RUN] Would create campaign '{campaign_name}' with {len(owners)} owners")
        for email, steps in list(owners.items())[:3]:
            print(f"  {steps[0]['first_name']} {steps[0]['last_name']} ({steps[0]['company_name']}) - {email}")
        return

    campaign_id = create_campaign_with_sequence(api_key, campaign_name, accounts, campaign_opts)
    if not campaign_id:
        print("Failed to create campaign!")
        return

    # Upload each owner with their 4 custom email steps as variables
    uploaded = 0
    failed = 0

    for email, steps in owners.items():
        # Build custom variables with all 4 steps
        custom_vars = {}
        for step in steps:
            step_num = step['sequence_step']
            custom_vars[f"subject_{step_num}"] = step['subject']
            custom_vars[f"body_{step_num}"] = step['body']

        # For follow-ups with empty subject, use "Re: " + original subject
        original_subject = custom_vars.get("subject_1", "")
        for i in [2, 3, 4]:
            if not custom_vars.get(f"subject_{i}"):
                custom_vars[f"subject_{i}"] = f"Re: {original_subject}"

        payload = {
            "campaign": campaign_id,
            "email": email,
            "first_name": steps[0].get('first_name', ''),
            "last_name": steps[0].get('last_name', ''),
            "company_name": steps[0].get('company_name', ''),
            "custom_variables": custom_vars,
        }

        result = api_request("POST", "/leads", api_key, payload)
        if "error" in result:
            failed += 1
            if failed <= 5:
                print(f"  Failed: {email} - {result['error'][:100]}")
        else:
            uploaded += 1

        if (uploaded + failed) % 5 == 0:
            time.sleep(1)
        if (uploaded + failed) % 20 == 0:
            print(f"  Progress: {uploaded}/{uploaded + failed}...")

    print(f"\n=== Upload Complete ===")
    print(f"Uploaded: {uploaded}")
    print(f"Failed: {failed}")
    print(f"Campaign: {campaign_name} (DRAFT mode)")
    print(f"Sequence: 4 steps (Day 0 → Day 3 → Day 5 → Day 8)")


if __name__ == "__main__":
    main()
