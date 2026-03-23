#!/usr/bin/env python3
"""
HVAC Daily Lead Feeder
======================
Scrapes new HVAC leads daily via Apify, formats emails in the clean template,
deduplicates against existing leads, and uploads directly to the evergreen
HVAC campaign on Instantly.

Usage:
    python hvac_daily_feeder.py                    # Default: scrape 50 new leads
    python hvac_daily_feeder.py --target 100       # Scrape 100 new leads
    python hvac_daily_feeder.py --dry-run          # Preview without uploading
    python hvac_daily_feeder.py --status            # Show feeder stats

Automate with cron:
    0 6 * * * cd /home/user/sales && python hvac_daily_feeder.py --target 50 >> output/hvac_feeder.log 2>&1
"""

import argparse
import csv
import json
import os
import random
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests required. pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
FEEDER_STATE = os.path.join(OUTPUT_DIR, "hvac_feeder_state.json")
MASTER_EMAILS = os.path.join(OUTPUT_DIR, "hvac_master_emails.json")

APIFY_BASE = "https://api.apify.com/v2"
GOOGLE_MAPS_EMAIL_ACTOR = "WnMxbsRLNbPeYL6ge"
INSTANTLY_BASE = "https://api.instantly.ai/api/v2"

CAMPAIGN_ID = "72b411be-b966-443d-a2ef-d705a7e4d98e"

# Search queries — rotated daily
HVAC_QUERIES = [
    "hvac company owner",
    "heating and air conditioning",
    "ac repair company",
    "hvac contractor",
    "furnace repair company",
    "air conditioning company",
    "plumbing and hvac",
    "heating and cooling company",
]

# All target metros — rotated through over time
ALL_LOCATIONS = [
    # US Sun Belt
    "Phoenix, AZ, USA", "Dallas, TX, USA", "Houston, TX, USA",
    "Miami, FL, USA", "Atlanta, GA, USA", "Las Vegas, NV, USA",
    "San Antonio, TX, USA", "Tampa, FL, USA", "Austin, TX, USA",
    "Orlando, FL, USA", "Jacksonville, FL, USA", "Charlotte, NC, USA",
    "Nashville, TN, USA", "Oklahoma City, OK, USA", "Tucson, AZ, USA",
    "Raleigh, NC, USA", "San Diego, CA, USA", "Fort Worth, TX, USA",
    "Memphis, TN, USA", "Sacramento, CA, USA",
    # US Northeast / Midwest
    "Chicago, IL, USA", "New York, NY, USA", "Philadelphia, PA, USA",
    "Boston, MA, USA", "Detroit, MI, USA", "Minneapolis, MN, USA",
    "Denver, CO, USA", "Indianapolis, IN, USA", "Columbus, OH, USA",
    "Kansas City, MO, USA", "St Louis, MO, USA", "Pittsburgh, PA, USA",
    "Cincinnati, OH, USA", "Cleveland, OH, USA", "Milwaukee, WI, USA",
    "Baltimore, MD, USA", "Richmond, VA, USA", "Louisville, KY, USA",
    "Salt Lake City, UT, USA", "Portland, OR, USA",
    # US South
    "Birmingham, AL, USA", "New Orleans, LA, USA", "Little Rock, AR, USA",
    "Knoxville, TN, USA", "Chattanooga, TN, USA", "Greenville, SC, USA",
    "Columbia, SC, USA", "Savannah, GA, USA", "Augusta, GA, USA",
    "Baton Rouge, LA, USA", "Mobile, AL, USA", "Huntsville, AL, USA",
    "Tulsa, OK, USA", "Wichita, KS, USA", "Omaha, NE, USA",
    "Des Moines, IA, USA", "Albuquerque, NM, USA", "El Paso, TX, USA",
    "McAllen, TX, USA", "Corpus Christi, TX, USA",
    # Canada
    "Toronto, ON, Canada", "Vancouver, BC, Canada", "Calgary, AB, Canada",
    "Edmonton, AB, Canada", "Ottawa, ON, Canada", "Montreal, QC, Canada",
    "Winnipeg, MB, Canada", "Halifax, NS, Canada", "Saskatoon, SK, Canada",
    "Hamilton, ON, Canada", "London, ON, Canada", "Kitchener, ON, Canada",
]

# Junk filters
GENERIC_PREFIXES = {
    "contact", "contactus", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "no-reply", "enquiries",
    "billing", "reception", "frontdesk", "service", "scheduling", "dispatch",
    "booking", "estimates", "estimate", "inquiry", "inquiries", "inquires",
    "customer", "care", "clientcare", "custservice", "custsupport", "hr",
    "career", "careers", "jobs", "employment", "training", "media", "news",
    "privacy", "abuse", "webmaster", "it", "hq", "corporate", "management",
    "operations", "maintenance", "membership", "sponsorships", "schedule",
    "request", "credit", "controller", "orders", "parts", "accounts",
    "techsupport", "updates", "email", "emailinfo", "generalinfo",
}

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "godaddy.com", "wix.com", "squarespace.com", "example.com",
    "sentry.io", "facebook.com", "instagram.com",
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state():
    if os.path.exists(FEEDER_STATE):
        try:
            with open(FEEDER_STATE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "runs": [],
        "total_uploaded": 0,
        "location_index": 0,
        "query_index": 0,
    }


def save_state(state):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state["last_updated"] = datetime.now().isoformat()
    with open(FEEDER_STATE, "w") as f:
        json.dump(state, f, indent=2)


def load_master_emails():
    """Load set of all emails ever uploaded to avoid duplicates."""
    if os.path.exists(MASTER_EMAILS):
        try:
            with open(MASTER_EMAILS) as f:
                return set(json.load(f))
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def save_master_emails(emails):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(MASTER_EMAILS, "w") as f:
        json.dump(sorted(emails), f)


def is_owner_email(email):
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    domain = email.split("@")[1].lower()
    if domain in JUNK_DOMAINS:
        return False
    if local in GENERIC_PREFIXES:
        return False
    # Skip if local part is all numbers or too short
    if local.isdigit() or len(local) < 2:
        return False
    return True


def extract_owner_name(email):
    if not email or "@" not in email:
        return "", ""
    local = email.split("@")[0].lower()
    if local in GENERIC_PREFIXES:
        return "", ""
    if "." in local:
        parts = local.split(".")
        return parts[0].title(), parts[-1].title()
    if local.isalpha() and 3 <= len(local) <= 15:
        return local.title(), ""
    return "", ""


def scrape_location(apify_key, query, location, max_results=30):
    print(f"  Scraping: '{query}' in {location}...")
    run_input = {
        "searchStringsArray": [query],
        "locationQuery": location,
        "maxCrawledPlacesPerSearch": max_results,
        "language": "en",
        "maxImages": 0,
        "maxReviews": 0,
        "scrapeContactInfo": True,
    }

    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{GOOGLE_MAPS_EMAIL_ACTOR}/runs",
            params={"token": apify_key},
            json=run_input,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"    Network error: {e}")
        return []

    if resp.status_code not in (200, 201):
        print(f"    Error starting run: {resp.status_code}")
        return []

    run_id = resp.json().get("data", {}).get("id")
    if not run_id:
        print("    No run ID returned")
        return []

    # Poll for completion (max 4 minutes)
    for _ in range(48):
        time.sleep(5)
        try:
            sr = requests.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": apify_key},
                timeout=10,
            )
            status = sr.json().get("data", {}).get("status")
        except requests.exceptions.RequestException:
            continue

        if status == "SUCCEEDED":
            dataset_id = sr.json().get("data", {}).get("defaultDatasetId")
            try:
                items_resp = requests.get(
                    f"{APIFY_BASE}/datasets/{dataset_id}/items",
                    params={"token": apify_key, "limit": max_results},
                    timeout=15,
                )
                items = items_resp.json()
                print(f"    Got {len(items)} businesses")
                return items if isinstance(items, list) else []
            except requests.exceptions.RequestException as e:
                print(f"    Error fetching results: {e}")
                return []
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"    Run {status}")
            return []

    print("    Timed out")
    return []


def process_results(raw_items, seen_emails):
    leads = []
    for item in raw_items:
        emails = item.get("emails", [])
        if not emails:
            email = item.get("email")
            if email:
                emails = [email]
        if not emails:
            continue

        company = item.get("title", "")
        website = item.get("website", "")
        if website and "?" in website:
            website = website.split("?")[0]

        best_email = None
        for email in emails:
            email = email.lower().strip()
            if email in seen_emails:
                continue
            if is_owner_email(email):
                best_email = email
                break

        if not best_email:
            continue

        first_name, last_name = extract_owner_name(best_email)
        if not first_name:
            continue

        seen_emails.add(best_email)
        leads.append({
            "first_name": first_name,
            "last_name": last_name,
            "email": best_email,
            "company_name": company,
            "phone": item.get("phone", ""),
            "website": website,
            "city": item.get("city", ""),
            "state": item.get("state", ""),
        })

    return leads


def generate_email(lead):
    """Generate email in the clean template format."""
    first = lead["first_name"]
    company = lead["company_name"]
    website = lead.get("website", "").replace("http://", "").replace("https://", "").replace("www.", "").rstrip("/")

    if website:
        custom_text = f"I checked out {website} and really liked what I saw"
    else:
        custom_text = f"I've been looking into {company} and really liked what I saw"

    lead["subject"] = random.choice([
        f"missed call + something I built for {company}",
        f"quick question about {company}",
        f"idea for {company}",
    ])

    lead["body"] = (
        f"Hey {first},\n\n"
        f"I tried calling {company} earlier, but couldn't get through. "
        f"I figured I'd reach out here. {custom_text}. "
        f"I put together a quick demo for you showing how an AI agent could handle missed calls, "
        f"qualify jobs, and book appointments automatically. "
        f"Let me know when you have some time for me to walk you through it.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"Just following up on my last email. I still have that demo I put together for {company} ready to go. "
        f"One HVAC company we work with went from missing 30% of their calls to capturing every single one. "
        f"Happy to show you how it works whenever you have a few minutes.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"With summer coming up, call volume is about to spike. "
        f"The demo I built for {company} shows how an AI agent handles the rush so your team can focus on the jobs. "
        f"Worth a quick look?\n\n"
        f"Best,\nDylan"
    )

    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Totally understand if now is not the right time. "
        f"Just wanted to leave the door open. I built that demo specifically for {company} "
        f"and it will be here whenever you are ready.\n\n"
        f"Best,\nDylan"
    )

    return lead


def upload_to_instantly(api_key, leads):
    """Upload leads directly to the evergreen HVAC campaign."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    uploaded = 0
    failed = 0

    for lead in leads:
        payload = {
            "campaign": CAMPAIGN_ID,
            "email": lead["email"],
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company_name", ""),
            "website": lead.get("website", ""),
            "custom_variables": {
                "custom_subject": lead.get("subject", ""),
                "custom_body": lead.get("body", ""),
                "followup_1": lead.get("followup_1", ""),
                "followup_2": lead.get("followup_2", ""),
                "followup_3": lead.get("followup_3", ""),
                "phone": lead.get("phone", ""),
                "city": lead.get("city", ""),
                "state": lead.get("state", ""),
            },
        }

        try:
            r = requests.post(
                f"{INSTANTLY_BASE}/leads",
                headers=headers,
                json=payload,
                timeout=15,
            )
            if r.status_code in (200, 201):
                uploaded += 1
            else:
                failed += 1
        except requests.exceptions.RequestException:
            failed += 1

        time.sleep(0.3)

    return uploaded, failed


def run_feeder(apify_key, instantly_key, target=50, dry_run=False):
    """Main daily feeder: scrape, filter, format, upload."""
    state = load_state()
    master_emails = load_master_emails()

    # Also load existing campaign CSV emails
    csv_path = os.path.join(OUTPUT_DIR, "hvac_campaign_emails.csv")
    if os.path.exists(csv_path):
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                master_emails.add(row["email"].lower().strip())

    loc_idx = state.get("location_index", 0)
    q_idx = state.get("query_index", 0)

    print(f"\n{'='*60}")
    print(f"  HVAC DAILY FEEDER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  Target: {target} new leads")
    print(f"  Known emails: {len(master_emails)} (will skip)")
    print(f"  Starting location: {ALL_LOCATIONS[loc_idx % len(ALL_LOCATIONS)]}")

    all_leads = []
    locations_tried = 0

    while len(all_leads) < target and locations_tried < 15:
        location = ALL_LOCATIONS[loc_idx % len(ALL_LOCATIONS)]
        query = HVAC_QUERIES[q_idx % len(HVAC_QUERIES)]
        loc_idx += 1
        q_idx += 1
        locations_tried += 1

        if dry_run:
            print(f"  [DRY RUN] Would scrape '{query}' in {location}")
            continue

        raw = scrape_location(apify_key, query, location, max_results=30)
        new_leads = process_results(raw, master_emails)

        for lead in new_leads:
            generate_email(lead)

        all_leads.extend(new_leads)
        print(f"    -> {len(new_leads)} owner leads (total: {len(all_leads)}/{target})")
        time.sleep(2)

    if not all_leads:
        print("\n  No new leads found.")
        state["location_index"] = loc_idx
        state["query_index"] = q_idx
        save_state(state)
        return

    print(f"\n  Found {len(all_leads)} new owner leads")

    if not dry_run:
        # Upload to Instantly
        print(f"  Uploading to HVAC campaign...")
        uploaded, failed = upload_to_instantly(instantly_key, all_leads)
        print(f"  Uploaded: {uploaded} | Failed: {failed}")

        # Update master email list
        for lead in all_leads:
            master_emails.add(lead["email"])
        save_master_emails(master_emails)

        # Append to campaign CSV
        fieldnames = [
            "email", "first_name", "last_name", "company_name", "phone",
            "website", "city", "state", "subject", "body",
            "followup_1", "followup_2", "followup_3",
        ]
        file_exists = os.path.exists(csv_path)
        with open(csv_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            if not file_exists:
                writer.writeheader()
            writer.writerows(all_leads)

        # Update state
        state["location_index"] = loc_idx
        state["query_index"] = q_idx
        state["total_uploaded"] = state.get("total_uploaded", 0) + uploaded
        state["runs"].append({
            "timestamp": datetime.now().isoformat(),
            "target": target,
            "found": len(all_leads),
            "uploaded": uploaded,
            "failed": failed,
        })
        save_state(state)

    print(f"\n{'='*60}")
    print(f"  DONE — {len(all_leads)} leads added to HVAC campaign")
    print(f"  Total all-time: {state.get('total_uploaded', 0)}")
    print(f"{'='*60}\n")


def show_status():
    state = load_state()
    master = load_master_emails()
    print(f"\n{'='*60}")
    print(f"  HVAC DAILY FEEDER STATUS")
    print(f"{'='*60}")
    print(f"  Total uploaded: {state.get('total_uploaded', 0)}")
    print(f"  Master email list: {len(master)}")
    print(f"  Next location: {ALL_LOCATIONS[state.get('location_index', 0) % len(ALL_LOCATIONS)]}")
    print(f"  Last updated: {state.get('last_updated', 'never')}")
    runs = state.get("runs", [])
    if runs:
        print(f"\n  Recent runs:")
        for run in runs[-10:]:
            print(f"    {run['timestamp'][:16]} | found: {run.get('found', 0)} | uploaded: {run.get('uploaded', 0)}")


def main():
    parser = argparse.ArgumentParser(description="HVAC Daily Lead Feeder")
    parser.add_argument("--target", type=int, default=50, help="New leads to find per run (default: 50)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without scraping/uploading")
    parser.add_argument("--status", action="store_true", help="Show feeder stats")
    args = parser.parse_args()

    config = load_config()
    apify_key = config.get("apify_api_key", "")
    instantly_key = config.get("instantly_api_key", "")

    if args.status:
        show_status()
        return

    if not apify_key:
        print("Error: No apify_api_key in config.json")
        sys.exit(1)
    if not instantly_key:
        print("Error: No instantly_api_key in config.json")
        sys.exit(1)

    run_feeder(apify_key, instantly_key, target=args.target, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
