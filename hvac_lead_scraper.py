#!/usr/bin/env python3
"""
HVAC Lead Scraper — Owner-Only, Email-Required
================================================
Scrapes Google Maps for HVAC companies across US + Canada,
extracts emails from their websites, and only keeps leads
that have a valid email. Designed for bulk cold email campaigns.

Uses Apify's Google Maps Email Extractor (WnMxbsRLNbPeYL6ge)
which scrapes businesses AND extracts contact emails in one pass.

Usage:
    python hvac_lead_scraper.py --target 1000
    python hvac_lead_scraper.py --target 500 --locations "Phoenix AZ,Dallas TX"
    python hvac_lead_scraper.py --target 200 --dry-run
    python hvac_lead_scraper.py --status
"""

import argparse
import csv
import json
import os
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
LEADS_FILE = os.path.join(OUTPUT_DIR, "hvac_leads_scraped.json")
CSV_FILE = os.path.join(OUTPUT_DIR, "hvac_campaign_emails.csv")
STATE_FILE = os.path.join(OUTPUT_DIR, "hvac_scraper_state.json")

APIFY_BASE = "https://api.apify.com/v2"
GOOGLE_MAPS_EMAIL_ACTOR = "WnMxbsRLNbPeYL6ge"

# HVAC search queries
HVAC_QUERIES = [
    "hvac company owner",
    "heating and air conditioning",
    "ac repair company",
    "hvac contractor",
    "furnace repair company",
    "air conditioning company",
]

# All target metros — US + Canada
ALL_LOCATIONS = [
    # US Sun Belt (highest AC demand)
    "Phoenix, AZ, USA", "Dallas, TX, USA", "Houston, TX, USA",
    "Miami, FL, USA", "Atlanta, GA, USA", "Las Vegas, NV, USA",
    "San Antonio, TX, USA", "Tampa, FL, USA", "Austin, TX, USA",
    "Orlando, FL, USA", "Jacksonville, FL, USA", "Charlotte, NC, USA",
    "Nashville, TN, USA", "Oklahoma City, OK, USA", "Tucson, AZ, USA",
    "Raleigh, NC, USA", "San Diego, CA, USA", "Fort Worth, TX, USA",
    "Memphis, TN, USA", "Sacramento, CA, USA",
    # US Northeast / Midwest (heating demand)
    "Chicago, IL, USA", "New York, NY, USA", "Philadelphia, PA, USA",
    "Boston, MA, USA", "Detroit, MI, USA", "Minneapolis, MN, USA",
    "Denver, CO, USA", "Indianapolis, IN, USA", "Columbus, OH, USA",
    "Kansas City, MO, USA", "St Louis, MO, USA", "Pittsburgh, PA, USA",
    "Cincinnati, OH, USA", "Cleveland, OH, USA", "Milwaukee, WI, USA",
    "Baltimore, MD, USA", "Richmond, VA, USA", "Louisville, KY, USA",
    "Salt Lake City, UT, USA", "Portland, OR, USA",
    # Canada
    "Toronto, ON, Canada", "Vancouver, BC, Canada", "Calgary, AB, Canada",
    "Edmonton, AB, Canada", "Ottawa, ON, Canada", "Montreal, QC, Canada",
    "Winnipeg, MB, Canada", "Halifax, NS, Canada", "Saskatoon, SK, Canada",
    "Hamilton, ON, Canada", "London, ON, Canada", "Kitchener, ON, Canada",
]

# Junk email prefixes to skip
GENERIC_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "no-reply",
    "billing", "reception", "frontdesk", "service", "scheduling",
}

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "godaddy.com", "wix.com", "squarespace.com", "example.com",
    "sentry.io", "facebook.com", "instagram.com",
}

# Cold email copy
OPENERS = [
    "Hey {{first_name}}, saw {{company}} is one of the top HVAC companies in {{city}}",
    "Hi {{first_name}}, came across {{company}} and had a quick thought",
    "Hey {{first_name}}, noticed {{company}} has been growing in {{city}}",
    "{{first_name}}, quick question for you",
    "Hi {{first_name}}, been looking at HVAC companies in {{city}} and {{company}} caught my eye",
]

PAIN_HOOKS = [
    "I know peak season gets insane with phones ringing nonstop. Missed calls during summer rushes can mean thousands in lost revenue per week.",
    "Most HVAC owners I talk to say the same thing: when it's hot outside, every call matters. But your team can't answer them all while they're out on jobs.",
    "Talked to a few HVAC owners recently who said they're losing 20-30% of inbound calls during peak because the team is in the field.",
    "HVAC is one of those businesses where a missed call on a hot day means a homeowner just calls the next company on Google. That revenue is gone.",
    "Running crews, handling dispatch, and managing phones all at once is a lot. Especially when AC season hits and call volume doubles overnight.",
]

VALUE_PROPS = [
    "We build custom AI voice agents for HVAC companies that pick up every call 24/7, qualify the lead, book the appointment, and send your team the details instantly.",
    "We set up an AI receptionist that answers every call for HVAC companies. It handles new customer intake, books service appointments, and does after-hours emergency triage.",
    "We deploy AI phone agents for HVAC companies that never miss a call. They qualify leads, book jobs on the calendar, and text your techs the details.",
    "We set up AI phone agents that handle inbound calls, qualify the job type, book the appointment, and follow up with the homeowner automatically.",
]

CTAS = [
    "Would love to show you how it works. What days are good for a quick call this week?",
    "Happy to walk you through a quick demo. What does your schedule look like this week?",
    "If you're open to it, I can show you exactly how it works in 15 minutes. What days work for you?",
    "Let me know if you'd be open to a quick chat. I can show you the whole system in under 15 minutes.",
]

FOLLOWUP_1 = [
    "Hey {{first_name}}, just bumping this. The AI agent I mentioned could save your team hours every week on phone duty alone. Worth a quick look?",
    "{{first_name}}, following up. One HVAC company we work with went from missing 30% of calls to capturing 100% within the first week. What days work?",
]

FOLLOWUP_2 = [
    "{{first_name}}, one more thought. We just helped an HVAC company capture an extra $47K/month by answering calls they were missing. Want to see how?",
    "Hey {{first_name}}, with summer coming, call volume is about to spike. Having an AI agent ready before the rush could be a game changer. Want me to show you?",
]

FOLLOWUP_3 = [
    "{{first_name}}, I'll keep this short. If {{company}} ever needs help handling more calls without hiring more staff, I'd love to help. Just reply whenever.",
    "{{first_name}}, last note. I genuinely think this could help {{company}} capture more revenue without adding overhead. If you're ever curious, just reply.",
]


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return {}


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"runs": [], "total_leads": 0, "locations_scraped": [], "emails_seen": []}


def save_state(state):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def is_owner_email(email):
    """Check if email looks like it belongs to an owner (not generic)."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    domain = email.split("@")[1].lower()
    if domain in JUNK_DOMAINS:
        return False
    if local in GENERIC_PREFIXES:
        return False
    return True


def extract_owner_name(email, company_name=""):
    """Try to extract first/last name from email address."""
    if not email or "@" not in email:
        return "", ""
    local = email.split("@")[0].lower()

    # Skip generic emails
    if local in GENERIC_PREFIXES:
        return "", ""

    # first.last@domain
    if "." in local:
        parts = local.split(".")
        return parts[0].title(), parts[-1].title()

    # firstlast@ (if short enough to be a name)
    if local.isalpha() and 3 <= len(local) <= 15:
        return local.title(), ""

    return "", ""


def clean_website(url):
    """Strip tracking params from website URL."""
    if not url:
        return ""
    if "?" in url:
        url = url.split("?")[0]
    return url.rstrip("/")


def scrape_location(apify_key, query, location, max_results=20):
    """Scrape a single location for HVAC businesses with emails."""
    print(f"  Scraping: '{query}' in {location} (max {max_results})...")

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
        print(f"    Network error starting run: {e}")
        return []

    if resp.status_code not in (200, 201):
        print(f"    Error starting run: {resp.status_code}")
        return []

    run_id = resp.json().get("data", {}).get("id")
    if not run_id:
        print("    No run ID returned")
        return []

    # Poll for completion (max 3 minutes per run)
    for i in range(36):
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

    print("    Timed out waiting for results")
    return []


def process_results(raw_items, seen_emails):
    """Filter to owner emails only, deduplicate."""
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
        city = item.get("city", "")
        state = item.get("state", "")
        phone = item.get("phone", "")
        website = clean_website(item.get("website", ""))
        category = item.get("categoryName", "")
        address = item.get("address", "")

        # Get the best email (prefer owner-like, non-generic)
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

        seen_emails.add(best_email)
        first_name, last_name = extract_owner_name(best_email, company)

        leads.append({
            "first_name": first_name,
            "last_name": last_name,
            "email": best_email,
            "company_name": company,
            "phone": phone,
            "website": website,
            "city": city,
            "state": state,
            "address": address,
            "category": category,
            "location": f"{city}, {state}" if city and state else city or state,
        })

    return leads


import random

def generate_email_copy(lead):
    """Generate personalized cold email for a single lead."""
    first = lead.get("first_name", "")
    company = lead.get("company_name", "your company")
    city = lead.get("city", "your area")
    state = lead.get("state", "")

    opener = random.choice(OPENERS)
    pain = random.choice(PAIN_HOOKS)
    value = random.choice(VALUE_PROPS)
    cta = random.choice(CTAS)

    # Use Instantly variables
    body = f"{opener}.\n\n{pain}\n\n{value}\n\n{cta}\n\nDylan"

    fu1 = random.choice(FOLLOWUP_1)
    fu2 = random.choice(FOLLOWUP_2)
    fu3 = random.choice(FOLLOWUP_3)

    subjects = [
        f"quick question about {{{{company}}}}",
        f"idea for {{{{company}}}}",
        f"missed calls at {{{{company}}}}?",
    ]
    if city:
        subjects.append(f"{city} HVAC + AI")

    lead["subject"] = random.choice(subjects)
    lead["body"] = body
    lead["followup_1"] = fu1
    lead["followup_2"] = fu2
    lead["followup_3"] = fu3
    return lead


def export_campaign_csv(leads, output_path=None):
    """Export leads as Instantly-ready CSV."""
    output_path = output_path or CSV_FILE
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    fieldnames = [
        "first_name", "last_name", "email", "company_name", "phone",
        "website", "city", "state", "location",
        "subject", "body", "followup_1", "followup_2", "followup_3",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)

    print(f"\nExported {len(leads)} leads -> {output_path}")


def run_scraper(apify_key, target=1000, locations=None, per_location=25, dry_run=False):
    """Main scraper loop: hit locations until we reach the target."""
    locations = locations or ALL_LOCATIONS
    state = load_state()
    seen_emails = set(state.get("emails_seen", []))
    all_leads = []

    print(f"\n{'='*60}")
    print(f"  HVAC LEAD SCRAPER — TARGET: {target} (owner emails only)")
    print(f"{'='*60}")
    print(f"  Locations: {len(locations)}")
    print(f"  Per location: {per_location}")
    print(f"  Already seen: {len(seen_emails)} emails")
    start_time = time.time()

    # Cycle through queries and locations
    query_idx = 0
    for location in locations:
        if len(all_leads) >= target:
            break

        query = HVAC_QUERIES[query_idx % len(HVAC_QUERIES)]
        query_idx += 1

        if dry_run:
            print(f"  [DRY RUN] Would scrape '{query}' in {location}")
            continue

        raw = scrape_location(apify_key, query, location, max_results=per_location)
        new_leads = process_results(raw, seen_emails)

        if new_leads:
            # Generate email copy for each lead
            for lead in new_leads:
                generate_email_copy(lead)
            all_leads.extend(new_leads)
            print(f"    -> {len(new_leads)} owner leads with email (total: {len(all_leads)}/{target})")
        else:
            print(f"    -> 0 owner leads with email")

        # Rate limit between locations
        time.sleep(2)

    elapsed = time.time() - start_time

    print(f"\n{'='*60}")
    print(f"  SCRAPE COMPLETE")
    print(f"{'='*60}")
    print(f"  Target: {target} | Found: {len(all_leads)} | Time: {elapsed:.0f}s")
    print(f"  Locations searched: {min(len(locations), query_idx)}")

    if all_leads and not dry_run:
        # Save raw leads
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        with open(LEADS_FILE, "w") as f:
            json.dump(all_leads, f, indent=2)
        print(f"  Raw leads saved: {LEADS_FILE}")

        # Export campaign CSV
        export_campaign_csv(all_leads)

        # Update state
        state["runs"].append({
            "timestamp": datetime.now().isoformat(),
            "target": target,
            "found": len(all_leads),
            "elapsed": round(elapsed),
        })
        state["total_leads"] += len(all_leads)
        state["emails_seen"] = sorted(seen_emails)
        save_state(state)

    return all_leads


def show_status():
    state = load_state()
    print(f"\n{'='*60}")
    print(f"  HVAC SCRAPER STATUS")
    print(f"{'='*60}")
    print(f"  Total leads scraped: {state.get('total_leads', 0)}")
    print(f"  Unique emails tracked: {len(state.get('emails_seen', []))}")
    print(f"  Last updated: {state.get('last_updated', 'never')}")

    runs = state.get("runs", [])
    if runs:
        print(f"\n  Recent runs:")
        for run in runs[-5:]:
            print(f"    {run['timestamp'][:16]} | {run['found']}/{run['target']} leads | {run['elapsed']}s")


def main():
    parser = argparse.ArgumentParser(description="HVAC Lead Scraper — Owner Emails Only")
    parser.add_argument("--target", type=int, default=1000, help="Target number of leads (default: 1000)")
    parser.add_argument("--locations", help="Comma-separated locations (default: all US+CA metros)")
    parser.add_argument("--per-location", type=int, default=25, help="Max businesses per location (default: 25)")
    parser.add_argument("--status", action="store_true", help="Show scraper status")
    parser.add_argument("--output", help="Custom CSV output path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without scraping")
    args = parser.parse_args()

    config = load_config()
    apify_key = config.get("apify_api_key", "")
    if not apify_key and not args.status:
        print("Error: No apify_api_key in config.json")
        sys.exit(1)

    if args.status:
        show_status()
        return

    locations = [l.strip() for l in args.locations.split(",")] if args.locations else None

    leads = run_scraper(
        apify_key, target=args.target,
        locations=locations, per_location=args.per_location,
        dry_run=args.dry_run,
    )

    if leads and args.output:
        export_campaign_csv(leads, args.output)


if __name__ == "__main__":
    main()
