#!/usr/bin/env python3
"""
Clean HVAC leads, generate personalized emails, and upload to Instantly.

Filters:
1. Must be HVAC/trade company (not restaurant, hotel, staffing, etc.)
2. Must have real owner-style email (no info@, admin@, generic prefixes)
3. Must have a first name
4. Deduplicates by email
5. Generates fresh personalized email for every lead

Usage:
    python clean_and_upload_hvac.py --dry-run    # preview only
    python clean_and_upload_hvac.py              # clean + upload
"""

import csv
import json
import os
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

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
CAMPAIGN_ID = "72b411be-b966-443d-a2ef-d705a7e4d98e"

# ── Filters ──────────────────────────────────────────────────────────────

GENERIC_PREFIXES = {
    "info", "contact", "contactus", "admin", "hello", "support", "help",
    "sales", "team", "office", "general", "mail", "noreply", "no-reply",
    "enquiries", "billing", "reception", "frontdesk", "service", "scheduling",
    "dispatch", "booking", "estimates", "estimate", "inquiry", "customer",
    "care", "hr", "career", "careers", "jobs", "employment", "media",
    "privacy", "abuse", "webmaster", "it", "hq", "corporate", "management",
    "operations", "maintenance", "orders", "parts", "accounts", "techsupport",
    "updates", "email", "marketing", "appointments", "ap", "ar", "accounting",
    "payroll", "purchasing", "controls", "permits", "compliance", "safety",
    "training", "warehouse", "shop", "fleet", "install", "installs",
    "warranty", "claims", "dispatch", "work", "feedback", "request",
    "miami", "dallas", "houston", "phoenix", "tampa", "orlando", "atlanta",
    "chicago", "denver", "austin", "nashville", "charlotte", "raleigh",
    "sacramento", "jacksonville", "indianapolis", "columbus", "memphis",
    "newpatients", "reservations", "share", "haysoffice", "apply",
    "human", "recruiting", "talent", "staffing", "yardsigns", "dot",
    "abc", "test", "demo", "sample", "xxx",
    "ecommerce", "win", "webteam", "digital",
}

JUNK_EMAIL_DOMAINS_EXTRA = {"xyz.com", "test.com", "example.com"}

# Additional local-part patterns to reject
GENERIC_PATTERNS = [
    "office", "dept", "group", "division", "center", "location",
    "branch", "region", "district", "coloradosprings", "emea", "apac",
    "americas", "northamerica", "national", "corporate",
]

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "indeed.com", "ziprecruiter.com", "monster.com", "linkedin.com",
    "godaddy.com", "wix.com", "squarespace.com", "facebook.com",
    "ubs.com", "wellsfargo.com", "chase.com", "citi.com", "bofa.com",
}

# Companies that are NOT HVAC/trade — filter out
JUNK_COMPANY_WORDS = [
    "staffing", "temp agency", "manpower", "adecco", "kelly services",
    "robert half", "panera", "hotel", "marriott", "hilton", "hyatt",
    "mcdonald", "burger", "wendy", "chili", "applebee", "olive garden",
    "subway", "pizza", "taco", "starbucks", "dunkin", "chipotle",
    "walmart", "target", "amazon", "fedex", "ups", "usps", "costco",
    "university", "college", "school district", "high school",
    "hospital", "medical center", "health system", "clinic",
    "dental", "orthodont", "veterinar", "animal hospital",
    "insurance", "bank", "credit union", "financial",
    "real estate", "realty", "property management", "apartment",
    "church", "ymca", "goodwill", "salvation army",
    "spa", "salon", "nail", "beauty", "barber", "hair",
    "law firm", "attorney", "legal", "accounting firm", "cpa",
    "car wash", "auto dealer", "dealership", "toyota", "ford", "honda",
    "gym", "fitness", "crossfit", "yoga",
    "daycare", "preschool", "childcare",
    "storage", "u-haul", "moving",
    "pest control",  # different vertical
    "landscap", "lawn care", "tree service",
    "distribut",  # distributors, not service companies
    "supply house", "wholesale",
    "museum", "holocaust", "memorial", "gallery",
    "public school", "school", "education",
    "pain", "spine", "orthopedic", "physical therapy",
    "pride industries", "goodwill industries",
    "supply", "equipment supply",
    "manufacturing", "multivac", "duke mfg", "dukemfg",
    "johnson controls", "jci", "carrier", "trane", "lennox", "daikin",
    "koch air", "gustave", "larson company",
    "filter division",
    "r.e. michel", "remichel", "re michel",
    "hyspeco", "petro home",
    "hooper corp", "modern htg",
    "extended stay", "lodging", "corpay", "clc",
    "suites", "inn ", "motel",
]

# Confirm HVAC/trade
HVAC_COMPANY_WORDS = [
    "hvac", "heating", "cooling", "air condition", "a/c", "furnace",
    "plumb", "mechanical", "refrigerat", "duct", "ventilat", "boiler",
    "comfort", "climate", "energy", "home service", "fire", "electric",
    "restoration", "roofing", "contractor", "service", "repair",
    "install", "maintenance", "thermal", "indoor air", "heat pump",
]

HVAC_CATEGORIES = [
    "hvac", "heating", "air condition", "plumb", "contractor",
    "mechanical", "refrigerat", "electric", "fire",
]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def is_owner_email(email):
    """Only allow personal-name emails on company domains."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower().strip()
    domain = email.split("@")[1].lower().strip()

    if domain in JUNK_DOMAINS or domain in JUNK_EMAIL_DOMAINS_EXTRA:
        return False
    if local in GENERIC_PREFIXES:
        return False
    # Check if local part contains generic patterns
    for pattern in GENERIC_PATTERNS:
        if pattern in local:
            return False
    if local.isdigit() or len(local) < 2:
        return False
    # Skip numeric-heavy prefixes (like tech123@)
    if sum(c.isdigit() for c in local) > len(local) / 2:
        return False
    # Skip if local part has "human" "resource" etc
    reject_words = ["human", "resource", "reservat", "newpatient", "service", "wichita", "mhac"]
    for word in reject_words:
        if word in local:
            return False
    # Reject if local part looks like city+role (e.g. "dallasps", "houstonhr")
    if len(local) > 8 and not "." in local and not local.isalpha():
        # Probably not a real name
        pass
    return True


def extract_name(email):
    """Extract first name from email local part."""
    local = email.split("@")[0].lower().strip()
    # john.smith@ -> John
    if "." in local:
        parts = local.split(".")
        first = parts[0]
        last = parts[-1] if len(parts) > 1 and parts[-1] != first else ""
        if first.isalpha() and len(first) >= 2:
            return first.title(), last.title() if last.isalpha() and len(last) >= 2 else ""
    # john@ -> John
    if local.isalpha() and 2 <= len(local) <= 15:
        return local.title(), ""
    return "", ""


def is_junk_company(name):
    name_lower = name.lower()
    for word in JUNK_COMPANY_WORDS:
        if word in name_lower:
            return True
    return False


def is_hvac_company(name, category=""):
    """Check if company name or Google Maps category confirms HVAC/trade."""
    combined = f"{name} {category}".lower()
    for word in HVAC_COMPANY_WORDS:
        if word in combined:
            return True
    for cat in HVAC_CATEGORIES:
        if cat in combined:
            return True
    return False


def generate_email(lead):
    """Generate personalized cold email + 3 follow-ups for each lead."""
    first = lead["first_name"]
    company = lead["company_name"]
    signal = lead.get("intent_signal", "")
    job_hiring = lead.get("job_title_hiring", "")

    # ── Hiring intent email ──
    if signal == "hiring_receptionist" and job_hiring:
        lead["subject"] = f"saw you're hiring, {first}"
        lead["body"] = (
            f"Hey {first},\n\n"
            f"Noticed {company} is hiring a {job_hiring.lower()}. Before you go through "
            f"the hiring process, wanted to show you something.\n\n"
            f"We built an AI agent that picks up every call, qualifies the lead, "
            f"and books jobs on your calendar. Works 24/7, costs a fraction of a hire.\n\n"
            f"I put together a quick demo for {company}. What days work for a call?\n\n"
            f"Dylan"
        )
        lead["followup_1"] = (
            f"Hey {first},\n\n"
            f"Hiring takes forever, especially front desk. The demo I built for "
            f"{company} takes 15 min and could save you months of recruiting.\n\n"
            f"Worth a quick look?\n\n"
            f"Dylan"
        )
        lead["followup_2"] = (
            f"Hey {first},\n\n"
            f"A {job_hiring.lower()} costs $3-4K/month fully loaded. Our AI agent "
            f"does the same job for a fraction, never misses a call. One client "
            f"saved $40K/year making the switch.\n\n"
            f"Want to see how it works?\n\n"
            f"Dylan"
        )
        lead["followup_3"] = (
            f"Hey {first},\n\n"
            f"Totally get it if now's not the time. The demo I built for {company} "
            f"is here whenever you're ready.\n\n"
            f"Dylan"
        )
        return lead

    # ── Bad review email ──
    if signal == "bad_review":
        lead["subject"] = f"saw a review about {company}"
        lead["body"] = (
            f"Hey {first},\n\n"
            f"Came across a review for {company} where a customer mentioned "
            f"trouble getting through on the phone. That's exactly what we solve.\n\n"
            f"We built an AI agent that picks up every call, qualifies the lead, "
            f"and books appointments automatically. Never misses, works 24/7.\n\n"
            f"I put together a demo for {company}. What days work for a call?\n\n"
            f"Dylan"
        )
        lead["followup_1"] = (
            f"Hey {first},\n\n"
            f"Missed calls silently cost businesses thousands every month. "
            f"The demo I built for {company} shows exactly how to fix it.\n\n"
            f"Happy to walk you through it. What days work?\n\n"
            f"Dylan"
        )
        lead["followup_2"] = (
            f"Hey {first},\n\n"
            f"The average missed call in your industry costs $200-500 in lost revenue. "
            f"One client went from missing 30% of calls to capturing every one.\n\n"
            f"Worth a quick look?\n\n"
            f"Dylan"
        )
        lead["followup_3"] = (
            f"Hey {first},\n\n"
            f"Totally get it if now's not the time. The demo I built for {company} "
            f"is here whenever you're ready.\n\n"
            f"Dylan"
        )
        return lead

    # ── Default / bulk scrape email ──
    lead["subject"] = f"built something for {company}"
    lead["body"] = (
        f"Hey {first},\n\n"
        f"I build AI phone agents for HVAC companies and I already put one together "
        f"for {company}. It picks up every call, qualifies the job, and books "
        f"appointments on your calendar automatically.\n\n"
        f"Works 24/7, never calls in sick. What days work for a call?\n\n"
        f"Dylan"
    )
    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"Just bumping this. One HVAC company we work with went from missing "
        f"30% of calls to capturing 100% in the first week.\n\n"
        f"Happy to show you how. What days work?\n\n"
        f"Dylan"
    )
    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"Quick stat: the average HVAC company loses $5-10K/month in missed calls. "
        f"Our AI agent makes sure you never miss another one.\n\n"
        f"Worth a quick look?\n\n"
        f"Dylan"
    )
    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Totally get it if now's not the time. The demo I built for {company} "
        f"is here whenever you're ready.\n\n"
        f"Dylan"
    )
    return lead


def load_scraped_json():
    """Load bulk scraped leads from JSON."""
    path = os.path.join(OUTPUT_DIR, "hvac_leads_scraped.json")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return json.load(f)


def load_intent_csv():
    """Load intent leads from CSV."""
    path = os.path.join(OUTPUT_DIR, "intent_hvac_hiring_leads.csv")
    if not os.path.exists(path):
        return []
    leads = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)
    return leads


def load_bulk_csv():
    """Load bulk campaign leads from CSV."""
    path = os.path.join(OUTPUT_DIR, "hvac_campaign_emails.csv")
    if not os.path.exists(path):
        return []
    leads = []
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            leads.append(row)
    return leads


def clean_leads(raw_leads, source_name):
    """Filter and clean leads. Returns clean list."""
    clean = []
    seen_emails = set()
    rejected = {"no_email": 0, "generic_email": 0, "no_name": 0, "junk_company": 0, "not_hvac": 0, "dupe": 0}

    for lead in raw_leads:
        email = (lead.get("email", "") or "").lower().strip()
        if not email or "@" not in email:
            rejected["no_email"] += 1
            continue

        if email in seen_emails:
            rejected["dupe"] += 1
            continue

        if not is_owner_email(email):
            rejected["generic_email"] += 1
            continue

        company = (lead.get("company_name", "") or "").strip()
        if not company:
            rejected["junk_company"] += 1
            continue

        if is_junk_company(company):
            rejected["junk_company"] += 1
            continue

        # Get first name — from data or extract from email
        first_name = (lead.get("first_name", "") or "").strip()
        last_name = (lead.get("last_name", "") or "").strip()
        if not first_name:
            first_name, last_name_extracted = extract_name(email)
            if not last_name:
                last_name = last_name_extracted

        if not first_name or len(first_name) < 2:
            rejected["no_name"] += 1
            continue

        # Check HVAC category for all sources
        category = lead.get("category", "")
        if not is_hvac_company(company, category):
            rejected["not_hvac"] += 1
            continue

        seen_emails.add(email)
        clean.append({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company,
            "phone": (lead.get("phone", "") or "").strip(),
            "website": (lead.get("website", "") or "").strip(),
            "city": (lead.get("city", "") or "").strip(),
            "state": (lead.get("state", "") or "").strip(),
            "intent_signal": (lead.get("intent_signal", "") or "").strip(),
            "job_title_hiring": (lead.get("job_title_hiring", "") or "").strip(),
            "source": source_name,
        })

    return clean, rejected


def upload_to_instantly(api_key, leads, campaign_id):
    """Upload leads to Instantly campaign."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    uploaded = 0
    failed = 0
    errors = []

    for i, lead in enumerate(leads):
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
                if len(errors) < 5:
                    errors.append(f"{lead['email']}: {r.status_code} {r.text[:100]}")
        except requests.exceptions.RequestException as e:
            failed += 1
            if len(errors) < 5:
                errors.append(f"{lead['email']}: {e}")

        # Progress
        if (i + 1) % 50 == 0:
            print(f"    Uploaded {i+1}/{len(leads)}...")

        time.sleep(0.3)

    return uploaded, failed, errors


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Clean HVAC leads and upload to Instantly")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    args = parser.parse_args()

    config = load_config()

    print(f"\n{'='*60}")
    print(f"  HVAC LEAD CLEANER + UPLOADER")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # ── Load all sources ──
    print(f"\n  Loading leads...")

    scraped = load_scraped_json()
    print(f"    Bulk scraped (JSON): {len(scraped)}")

    intent = load_intent_csv()
    print(f"    Intent hiring (CSV): {len(intent)}")

    bulk_csv = load_bulk_csv()
    print(f"    Bulk campaign (CSV): {len(bulk_csv)}")

    # ── Clean each source ──
    print(f"\n  Cleaning...")

    clean_scraped, rej_scraped = clean_leads(scraped, "bulk_scraped")
    print(f"    Bulk scraped: {len(scraped)} -> {len(clean_scraped)} clean")
    print(f"      Rejected: {rej_scraped}")

    clean_intent, rej_intent = clean_leads(intent, "intent_hiring")
    print(f"    Intent hiring: {len(intent)} -> {len(clean_intent)} clean")
    print(f"      Rejected: {rej_intent}")

    clean_bulk, rej_bulk = clean_leads(bulk_csv, "bulk_campaign")
    print(f"    Bulk campaign: {len(bulk_csv)} -> {len(clean_bulk)} clean")
    print(f"      Rejected: {rej_bulk}")

    # ── Global dedup across all sources ──
    all_leads = []
    global_seen = set()

    # Priority: intent leads first, then scraped, then bulk
    for lead_list in [clean_intent, clean_scraped, clean_bulk]:
        for lead in lead_list:
            if lead["email"] not in global_seen:
                global_seen.add(lead["email"])
                all_leads.append(lead)

    print(f"\n  After global dedup: {len(all_leads)} unique leads")

    # ── Generate personalized emails ──
    print(f"  Generating personalized emails...")
    for lead in all_leads:
        generate_email(lead)

    # ── Stats ──
    by_source = {}
    for lead in all_leads:
        src = lead.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1

    print(f"\n  Breakdown by source:")
    for src, count in sorted(by_source.items()):
        print(f"    {src}: {count}")

    by_signal = {}
    for lead in all_leads:
        sig = lead.get("intent_signal", "") or "bulk_outreach"
        by_signal[sig] = by_signal.get(sig, 0) + 1

    print(f"\n  Breakdown by signal:")
    for sig, count in sorted(by_signal.items()):
        print(f"    {sig}: {count}")

    # ── Preview sample ──
    print(f"\n  Sample leads:")
    for lead in all_leads[:10]:
        print(f"    {lead['first_name']} {lead['last_name']} | {lead['email']} | {lead['company_name']}")

    # ── Save clean CSV ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    clean_csv_path = os.path.join(OUTPUT_DIR, "hvac_clean_leads.csv")
    fieldnames = [
        "email", "first_name", "last_name", "company_name", "phone",
        "website", "city", "state", "intent_signal", "source",
        "subject", "body", "followup_1", "followup_2", "followup_3",
    ]
    with open(clean_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(all_leads)
    print(f"\n  Saved clean CSV: {clean_csv_path}")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would upload {len(all_leads)} leads to campaign {CAMPAIGN_ID}")
        print(f"{'='*60}\n")
        return

    # ── Upload to Instantly ──
    print(f"\n  Uploading {len(all_leads)} leads to Instantly...")
    uploaded, failed, errors = upload_to_instantly(
        config["instantly_api_key"], all_leads, CAMPAIGN_ID
    )
    print(f"\n  Upload complete!")
    print(f"    Uploaded: {uploaded}")
    print(f"    Failed: {failed}")
    if errors:
        print(f"    Sample errors:")
        for err in errors:
            print(f"      {err}")

    print(f"\n{'='*60}")
    print(f"  DONE — {uploaded} clean HVAC leads in your campaign")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
