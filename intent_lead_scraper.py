#!/usr/bin/env python3
"""
Intent Lead Scraper
===================
Finds HIGH-INTENT leads by scraping buying signals, then enriches with
owner email and uploads personalized emails directly to Instantly.

Intent Signals:
1. HIRING RECEPTIONISTS — Companies posting jobs for receptionist/CSR/dispatcher
   on Indeed = actively spending money on the problem we solve
2. BAD REVIEWS — Google reviews mentioning "no one answered", "voicemail",
   "couldn't get through" = public proof they need us
3. RUNNING ADS — Companies spending on Google Ads for their services
   but missing calls = burning money

Usage:
    python intent_lead_scraper.py --signal hiring --industry hvac --target 50
    python intent_lead_scraper.py --signal hiring --industry dental --target 50
    python intent_lead_scraper.py --signal reviews --industry hvac --target 30
    python intent_lead_scraper.py --signal all --industry hvac --target 100
    python intent_lead_scraper.py --status
    python intent_lead_scraper.py --dry-run --signal hiring --industry hvac
"""

import argparse
import csv
import json
import os
import random
import re
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
STATE_FILE = os.path.join(OUTPUT_DIR, "intent_scraper_state.json")
MASTER_EMAILS = os.path.join(OUTPUT_DIR, "intent_master_emails.json")

APIFY_BASE = "https://api.apify.com/v2"
INDEED_ACTOR = "hMvNSpz3JnHgl5jkh"
GOOGLE_MAPS_EMAIL_ACTOR = "WnMxbsRLNbPeYL6ge"
INSTANTLY_BASE = "https://api.instantly.ai/api/v2"

# Campaign IDs — map industry to campaign
CAMPAIGN_IDS = {
    "hvac": "72b411be-b966-443d-a2ef-d705a7e4d98e",
    "dental": "e0e29600-5ec9-44e6-970d-35a5760d65af",
}

# Indeed search queries by industry
HIRING_QUERIES = {
    "hvac": [
        "HVAC receptionist",
        "HVAC office manager",
        "HVAC customer service representative",
        "HVAC dispatcher",
        "heating and cooling receptionist",
        "air conditioning office admin",
        "plumbing receptionist",
    ],
    "dental": [
        "dental receptionist",
        "dental front desk",
        "dental office manager",
        "dental patient coordinator",
        "dental scheduling coordinator",
        "orthodontic receptionist",
    ],
    "medspa": [
        "med spa receptionist",
        "medical spa front desk",
        "aesthetics receptionist",
        "medspa patient coordinator",
    ],
    "wellness": [
        "wellness center receptionist",
        "chiropractic receptionist",
        "physical therapy front desk",
    ],
}

# Google Maps queries for review scraping
REVIEW_QUERIES = {
    "hvac": ["hvac company", "air conditioning repair", "heating and cooling"],
    "dental": ["dental office", "dentist", "dental practice"],
    "medspa": ["med spa", "medical spa", "aesthetics clinic"],
}

# Locations for Indeed
INDEED_LOCATIONS = [
    "Phoenix, AZ", "Dallas, TX", "Houston, TX", "Miami, FL", "Atlanta, GA",
    "Las Vegas, NV", "Tampa, FL", "Austin, TX", "Nashville, TN", "Charlotte, NC",
    "Chicago, IL", "Denver, CO", "Orlando, FL", "San Antonio, TX", "Raleigh, NC",
    "Jacksonville, FL", "Indianapolis, IN", "Columbus, OH", "San Diego, CA",
    "Sacramento, CA", "Memphis, TN", "Oklahoma City, OK", "Tucson, AZ",
    "Birmingham, AL", "New Orleans, LA", "Knoxville, TN", "Greenville, SC",
    "Baton Rouge, LA", "Tulsa, OK", "Omaha, NE",
]

# Google Maps locations
GMAPS_LOCATIONS = [
    "Phoenix, AZ, USA", "Dallas, TX, USA", "Houston, TX, USA", "Miami, FL, USA",
    "Atlanta, GA, USA", "Las Vegas, NV, USA", "Tampa, FL, USA", "Austin, TX, USA",
    "Nashville, TN, USA", "Charlotte, NC, USA", "Chicago, IL, USA", "Denver, CO, USA",
    "Orlando, FL, USA", "San Antonio, TX, USA", "Raleigh, NC, USA",
    "Jacksonville, FL, USA", "Indianapolis, IN, USA", "Columbus, OH, USA",
]

# Generic email prefixes to skip
GENERIC_PREFIXES = {
    "contact", "contactus", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "no-reply", "enquiries",
    "billing", "reception", "frontdesk", "service", "scheduling", "dispatch",
    "booking", "estimates", "estimate", "inquiry", "inquiries", "customer",
    "care", "clientcare", "hr", "career", "careers", "jobs", "employment",
    "training", "media", "news", "privacy", "abuse", "webmaster", "it", "hq",
    "corporate", "management", "operations", "maintenance", "orders", "parts",
    "accounts", "techsupport", "updates", "email", "marketing", "appointments",
}

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "indeed.com", "ziprecruiter.com", "monster.com", "linkedin.com",
    "godaddy.com", "wix.com", "squarespace.com", "facebook.com", "instagram.com",
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"runs": [], "total_uploaded": 0, "hiring_location_index": 0, "review_location_index": 0}


def save_state(state):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state["last_updated"] = datetime.now().isoformat()
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


def load_master_emails():
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
    if local.isdigit() or len(local) < 2:
        return False
    return True


def extract_name(email):
    if not email or "@" not in email:
        return "", ""
    local = email.split("@")[0].lower()
    if "." in local:
        parts = local.split(".")
        return parts[0].title(), parts[-1].title()
    if local.isalpha() and 3 <= len(local) <= 15:
        return local.title(), ""
    return "", ""


def run_apify_actor(apify_key, actor_id, run_input, timeout_mins=5):
    """Run an Apify actor and return results."""
    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{actor_id}/runs",
            params={"token": apify_key},
            json=run_input,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"    Network error: {e}")
        return []

    if resp.status_code not in (200, 201):
        print(f"    Error starting actor: {resp.status_code} {resp.text[:200]}")
        return []

    run_id = resp.json().get("data", {}).get("id")
    if not run_id:
        return []

    max_polls = timeout_mins * 12
    for _ in range(max_polls):
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
                    params={"token": apify_key, "limit": 100},
                    timeout=15,
                )
                items = items_resp.json()
                return items if isinstance(items, list) else []
            except requests.exceptions.RequestException:
                return []
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"    Actor run {status}")
            return []

    print("    Timed out waiting for actor")
    return []


# =============================================================================
# SIGNAL 1: HIRING RECEPTIONISTS
# =============================================================================

def scrape_hiring_signal(apify_key, industry, locations, seen_emails, target=50):
    """Scrape Indeed for companies hiring receptionists in the target industry."""
    queries = HIRING_QUERIES.get(industry, HIRING_QUERIES["hvac"])
    leads = []

    for location in locations:
        if len(leads) >= target:
            break

        query = random.choice(queries)
        print(f"  [HIRING] Scraping Indeed: '{query}' in {location}...")

        run_input = {
            "position": query,
            "location": location,
            "maxItems": 20,
            "parseCompanyDetails": False,
            "saveOnlyUniqueItems": True,
            "maxConcurrency": 5,
        }

        results = run_apify_actor(apify_key, INDEED_ACTOR, run_input, timeout_mins=3)
        print(f"    Got {len(results)} job listings")

        # Extract company names and domains from job listings
        companies_found = {}
        for job in results:
            company = job.get("company", "") or job.get("companyName", "")
            job_title = job.get("positionName", "") or job.get("title", "") or job.get("position", "")
            job_location = job.get("location", location)
            job_url = job.get("url", "") or job.get("externalUrl", "")

            if not company:
                continue

            # Skip staffing agencies
            skip_words = ["staffing", "temp", "manpower", "adecco", "kelly services", "robert half"]
            if any(w in company.lower() for w in skip_words):
                continue

            if company not in companies_found:
                companies_found[company] = {
                    "company": company,
                    "job_title": job_title,
                    "location": job_location,
                    "job_url": job_url,
                }

        if not companies_found:
            continue

        print(f"    Found {len(companies_found)} unique companies hiring")

        # Now find owner emails via Google Maps
        for company_name, job_info in companies_found.items():
            if len(leads) >= target:
                break

            city = job_info["location"].split(",")[0].strip() if "," in job_info["location"] else job_info["location"]

            print(f"    Enriching: {company_name} ({city})...")
            gmaps_input = {
                "searchStringsArray": [company_name],
                "locationQuery": f"{city}, USA",
                "maxCrawledPlacesPerSearch": 3,
                "language": "en",
                "maxImages": 0,
                "maxReviews": 0,
                "scrapeContactInfo": True,
            }

            gmaps_results = run_apify_actor(apify_key, GOOGLE_MAPS_EMAIL_ACTOR, gmaps_input, timeout_mins=3)

            for item in gmaps_results:
                emails = item.get("emails", [])
                if not emails:
                    e = item.get("email")
                    if e:
                        emails = [e]
                if not emails:
                    continue

                website = item.get("website", "")
                phone = item.get("phone", "")
                actual_company = item.get("title", company_name)

                for email in emails:
                    email = email.lower().strip()
                    if email in seen_emails:
                        continue
                    if not is_owner_email(email):
                        continue

                    first_name, last_name = extract_name(email)
                    if not first_name:
                        continue

                    seen_emails.add(email)
                    leads.append({
                        "email": email,
                        "first_name": first_name,
                        "last_name": last_name,
                        "company_name": actual_company,
                        "phone": phone,
                        "website": website,
                        "city": item.get("city", city),
                        "state": item.get("state", ""),
                        "intent_signal": "hiring_receptionist",
                        "job_title_hiring": job_info["job_title"],
                    })
                    break

            time.sleep(2)

        time.sleep(2)

    return leads


# =============================================================================
# SIGNAL 2: BAD REVIEWS (missed calls, no answer)
# =============================================================================

def scrape_review_signal(apify_key, industry, locations, seen_emails, target=30):
    """Scrape Google Maps for businesses with reviews about missed calls."""
    queries = REVIEW_QUERIES.get(industry, REVIEW_QUERIES["hvac"])
    leads = []

    for location in locations:
        if len(leads) >= target:
            break

        query = random.choice(queries)
        print(f"  [REVIEWS] Scraping: '{query}' in {location}...")

        run_input = {
            "searchStringsArray": [query],
            "locationQuery": location,
            "maxCrawledPlacesPerSearch": 20,
            "language": "en",
            "maxImages": 0,
            "maxReviews": 10,
            "scrapeContactInfo": True,
            "reviewsSort": "newest",
        }

        results = run_apify_actor(apify_key, GOOGLE_MAPS_EMAIL_ACTOR, run_input, timeout_mins=4)
        print(f"    Got {len(results)} businesses with reviews")

        # Filter for businesses with bad review signals
        bad_review_keywords = [
            "no one answered", "never called back", "couldn't get through",
            "went to voicemail", "didn't answer", "no answer", "never returned",
            "didn't call back", "couldn't reach", "left a message", "no response",
            "didn't return my call", "hard to reach", "never picks up",
            "phone just rings", "can't get ahold", "impossible to reach",
        ]

        for item in results:
            if len(leads) >= target:
                break

            reviews = item.get("reviews", [])
            if not reviews:
                continue

            # Check reviews for missed call signals
            bad_review = None
            for review in reviews:
                review_text = (review.get("text", "") or review.get("textTranslated", "") or "").lower()
                stars = review.get("stars", 5)
                if stars <= 3:
                    for keyword in bad_review_keywords:
                        if keyword in review_text:
                            bad_review = review.get("text", "") or review.get("textTranslated", "")
                            break
                if bad_review:
                    break

            if not bad_review:
                continue

            # Found a business with a bad review about missed calls
            emails = item.get("emails", [])
            if not emails:
                e = item.get("email")
                if e:
                    emails = [e]
            if not emails:
                continue

            company = item.get("title", "")
            website = item.get("website", "")
            phone = item.get("phone", "")

            for email in emails:
                email = email.lower().strip()
                if email in seen_emails:
                    continue
                if not is_owner_email(email):
                    continue

                first_name, last_name = extract_name(email)
                if not first_name:
                    continue

                seen_emails.add(email)
                # Truncate review for the email
                review_snippet = bad_review[:150].strip()
                if len(bad_review) > 150:
                    review_snippet += "..."

                leads.append({
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "company_name": company,
                    "phone": phone,
                    "website": website,
                    "city": item.get("city", ""),
                    "state": item.get("state", ""),
                    "intent_signal": "bad_review",
                    "review_snippet": review_snippet,
                })
                break

        time.sleep(2)

    return leads


# =============================================================================
# EMAIL GENERATION — Custom per intent signal
# =============================================================================

def generate_hiring_email(lead, industry):
    """Email for companies hiring receptionists."""
    first = lead["first_name"]
    company = lead["company_name"]
    job = lead.get("job_title_hiring", "receptionist")

    industry_terms = {
        "hvac": ("calls", "jobs", "service appointments"),
        "dental": ("calls", "patients", "appointments"),
        "medspa": ("calls", "clients", "appointments"),
        "wellness": ("calls", "patients", "appointments"),
    }
    calls, people, appts = industry_terms.get(industry, ("calls", "leads", "appointments"))

    lead["subject"] = f"saw you're hiring — {company}"

    lead["body"] = (
        f"Hey {first},\n\n"
        f"I noticed {company} is hiring a {job.lower()}. Before you go through the whole hiring process, "
        f"I wanted to show you something. We built an AI agent that picks up every {calls.rstrip('s')} instantly, "
        f"qualifies {people}, and books {appts} on your calendar automatically.\n\n"
        f"It works 24/7, never calls in sick, and costs a fraction of a full-time hire. "
        f"I actually put together a quick demo for {company}.\n\n"
        f"Let me know what days work for a call.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"Just following up. I know hiring takes forever, especially for front desk. "
        f"The demo I built for {company} takes 15 minutes to walk through and could save you "
        f"months of recruiting, training, and turnover.\n\n"
        f"Worth a quick look?\n\n"
        f"Best,\nDylan"
    )

    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"One thing I should mention — a {job.lower()} costs $3-4K/month fully loaded. "
        f"Our AI agent does the same job for a fraction of that, and it never misses a {calls.rstrip('s')}. "
        f"One of our clients saved $40K/year making the switch.\n\n"
        f"Let me know if you want to see how it works.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Totally understand if now is not the right time. "
        f"Just wanted to leave the door open. The demo I built for {company} "
        f"will be here whenever you are ready.\n\n"
        f"Best,\nDylan"
    )

    return lead


def generate_review_email(lead, industry):
    """Email for companies with bad reviews about missed calls."""
    first = lead["first_name"]
    company = lead["company_name"]

    lead["subject"] = f"saw a review about {company} — easy fix"

    lead["body"] = (
        f"Hey {first},\n\n"
        f"I came across a recent review for {company} where a customer mentioned "
        f"they had trouble getting through on the phone. "
        f"I figured I'd reach out because that is exactly what we solve.\n\n"
        f"We built an AI agent that picks up every call instantly, qualifies the lead, "
        f"and books appointments on your calendar automatically. Never misses a call, works 24/7.\n\n"
        f"I put together a quick demo for {company}. "
        f"Let me know what days work for a call.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"Just following up on my last email. Missed calls are one of those things that "
        f"silently cost businesses thousands every month. The demo I put together for {company} "
        f"shows exactly how to fix it.\n\n"
        f"Happy to walk you through it whenever you have a few minutes.\n\n"
        f"Best,\nDylan"
    )

    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"Quick stat — the average missed call in your industry costs $200-500 in lost revenue. "
        f"Our AI agent makes sure you never miss another one. "
        f"One of our clients went from missing 30% of calls to capturing every single one.\n\n"
        f"Worth a quick look?\n\n"
        f"Best,\nDylan"
    )

    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Totally understand if now is not the right time. "
        f"Just wanted to leave the door open. The demo I built for {company} "
        f"will be here whenever you are ready.\n\n"
        f"Best,\nDylan"
    )

    return lead


# =============================================================================
# UPLOAD TO INSTANTLY
# =============================================================================

def upload_to_instantly(api_key, leads, campaign_id):
    """Upload leads to an Instantly campaign."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    uploaded = 0
    failed = 0

    for lead in leads:
        payload = {
            "campaign": campaign_id,
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
                "intent_signal": lead.get("intent_signal", ""),
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


# =============================================================================
# MAIN
# =============================================================================

def run_scraper(config, signal, industry, target, campaign_id, dry_run=False):
    state = load_state()
    seen_emails = load_master_emails()

    apify_key = config["apify_api_key"]
    instantly_key = config["instantly_api_key"]

    print(f"\n{'='*60}")
    print(f"  INTENT LEAD SCRAPER — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  Signal: {signal}")
    print(f"  Industry: {industry}")
    print(f"  Target: {target}")
    print(f"  Campaign: {campaign_id}")
    print(f"  Known emails: {len(seen_emails)}")

    all_leads = []

    if signal in ("hiring", "all"):
        loc_idx = state.get("hiring_location_index", 0)
        locations = INDEED_LOCATIONS[loc_idx:loc_idx + 10]
        if not locations:
            locations = INDEED_LOCATIONS[:10]
            loc_idx = 0

        hiring_target = target if signal == "hiring" else target // 2

        if dry_run:
            print(f"\n  [DRY RUN] Would scrape Indeed for {industry} receptionist jobs in {len(locations)} cities")
        else:
            hiring_leads = scrape_hiring_signal(apify_key, industry, locations, seen_emails, target=hiring_target)
            for lead in hiring_leads:
                generate_hiring_email(lead, industry)
            all_leads.extend(hiring_leads)
            print(f"\n  Hiring signal: {len(hiring_leads)} leads found")

        state["hiring_location_index"] = loc_idx + len(locations)

    if signal in ("reviews", "all"):
        loc_idx = state.get("review_location_index", 0)
        locations = GMAPS_LOCATIONS[loc_idx:loc_idx + 8]
        if not locations:
            locations = GMAPS_LOCATIONS[:8]
            loc_idx = 0

        review_target = target if signal == "reviews" else target // 2

        if dry_run:
            print(f"\n  [DRY RUN] Would scrape Google Reviews for {industry} missed call signals in {len(locations)} cities")
        else:
            review_leads = scrape_review_signal(apify_key, industry, locations, seen_emails, target=review_target)
            for lead in review_leads:
                generate_review_email(lead, industry)
            all_leads.extend(review_leads)
            print(f"\n  Review signal: {len(review_leads)} leads found")

        state["review_location_index"] = loc_idx + len(locations)

    print(f"\n  Total intent leads: {len(all_leads)}")

    if all_leads and not dry_run:
        # Upload to Instantly
        print(f"  Uploading to campaign...")
        uploaded, failed = upload_to_instantly(instantly_key, all_leads, campaign_id)
        print(f"  Uploaded: {uploaded} | Failed: {failed}")

        # Save master emails
        for lead in all_leads:
            seen_emails.add(lead["email"])
        save_master_emails(seen_emails)

        # Save CSV
        csv_path = os.path.join(OUTPUT_DIR, f"intent_{industry}_{signal}_leads.csv")
        fieldnames = [
            "email", "first_name", "last_name", "company_name", "phone",
            "website", "city", "state", "intent_signal", "subject", "body",
            "followup_1", "followup_2", "followup_3",
        ]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(all_leads)
        print(f"  Saved CSV: {csv_path}")

        # Update state
        state["total_uploaded"] = state.get("total_uploaded", 0) + uploaded
        state["runs"].append({
            "timestamp": datetime.now().isoformat(),
            "signal": signal,
            "industry": industry,
            "target": target,
            "found": len(all_leads),
            "uploaded": uploaded,
        })
        save_state(state)

    print(f"\n{'='*60}")
    print(f"  DONE — {len(all_leads)} high-intent leads")
    print(f"{'='*60}\n")

    return all_leads


def show_status():
    state = load_state()
    master = load_master_emails()
    print(f"\n{'='*60}")
    print(f"  INTENT SCRAPER STATUS")
    print(f"{'='*60}")
    print(f"  Total uploaded: {state.get('total_uploaded', 0)}")
    print(f"  Master emails: {len(master)}")
    print(f"  Last updated: {state.get('last_updated', 'never')}")
    runs = state.get("runs", [])
    if runs:
        print(f"\n  Recent runs:")
        for run in runs[-10:]:
            print(f"    {run['timestamp'][:16]} | {run['signal']} | {run['industry']} | found: {run.get('found', 0)} | uploaded: {run.get('uploaded', 0)}")


def main():
    parser = argparse.ArgumentParser(description="Intent Lead Scraper")
    parser.add_argument("--signal", choices=["hiring", "reviews", "all"], default="all",
                        help="Intent signal to scrape (default: all)")
    parser.add_argument("--industry", default="hvac",
                        help="Industry to target: hvac, dental, medspa, wellness")
    parser.add_argument("--target", type=int, default=50,
                        help="Target number of leads (default: 50)")
    parser.add_argument("--campaign-id", help="Override campaign ID")
    parser.add_argument("--dry-run", action="store_true", help="Preview without scraping")
    parser.add_argument("--status", action="store_true", help="Show status")
    args = parser.parse_args()

    config = load_config()

    if args.status:
        show_status()
        return

    campaign_id = args.campaign_id or CAMPAIGN_IDS.get(args.industry)
    if not campaign_id:
        print(f"No campaign ID for industry '{args.industry}'. Use --campaign-id to specify.")
        sys.exit(1)

    run_scraper(config, args.signal, args.industry, args.target, campaign_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
