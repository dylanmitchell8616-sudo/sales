#!/usr/bin/env python3
"""
Clean dental DSO leads, generate personalized emails, dedup against
existing campaign leads, and upload to Instantly.

Usage:
    python clean_and_upload_dental.py --dry-run
    python clean_and_upload_dental.py
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
RAW_CSV_1 = os.path.join(OUTPUT_DIR, "dental_dso_raw.csv")
RAW_CSV_2 = os.path.join(OUTPUT_DIR, "dental_dso_raw2.csv")

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
CAMPAIGN_ID = "e0e29600-5ec9-44e6-970d-35a5760d65af"

# ── Filters ──────────────────────────────────────────────────────────────

# Non-dental companies to filter out
JUNK_COMPANY_WORDS = [
    "vision source", "optometr", "eye care", "eye doctor", "optical",
    "pet health", "veterinar", "animal hospital", "vet clinic",
    "staffing", "temp agency", "manpower", "robert half",
    "hotel", "marriott", "hilton", "hyatt",
    "restaurant", "pizza", "burger", "taco", "subway",
    "real estate", "realty", "insurance", "bank",
    "church", "ymca", "goodwill",
    "gym", "fitness", "crossfit",
    "salon", "barber", "nail", "spa",  # non-dental spa
    "hvac", "plumb", "roofing", "electric",
    "car wash", "auto dealer",
    "lawn care", "landscap",
]

# Confirm dental/DSO
DENTAL_KEYWORDS = [
    "dental", "dentist", "orthodont", "endodont", "periodont",
    "oral surgery", "implant", "smile", "tooth", "teeth",
    "pediatric dent", "prosthodont", "denture",
    "dso", "dental service", "dental group", "dental care",
    "dental studio", "dental center", "dental clinic",
    "dental health", "dental practice", "dental office",
    "braces", "invisalign", "cosmetic dent",
]

DENTAL_TITLE_KEYWORDS = [
    "dentist", "dental", "dds", "dmd", "orthodont", "endodont",
    "periodont", "oral surg", "prosthodont",
]

# Generic email prefixes to skip
GENERIC_PREFIXES = {
    "info", "contact", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "billing",
    "reception", "frontdesk", "scheduling", "hr", "careers", "jobs",
    "marketing", "media", "it", "webmaster",
}

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "indeed.com", "linkedin.com",
}


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def is_dental_company(company_name, job_title=""):
    """Check if company or job title confirms dental."""
    combined = f"{company_name} {job_title}".lower()
    for word in DENTAL_KEYWORDS:
        if word in combined:
            return True
    for word in DENTAL_TITLE_KEYWORDS:
        if word in combined:
            return True
    # Owner titles at known DSOs are dental
    known_dsos = [
        "affordable dentures", "aspen dental", "pds health",
        "pacific dental", "clearchoice", "comfort dental",
        "heartland dental", "dental fix", "benevis",
    ]
    for dso in known_dsos:
        if dso in company_name.lower():
            return True
    return False


def is_junk_company(name):
    name_lower = name.lower()
    for word in JUNK_COMPANY_WORDS:
        if word in name_lower:
            return True
    return False


def is_owner_email(email):
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower().strip()
    domain = email.split("@")[1].lower().strip()
    if domain in JUNK_DOMAINS:
        return False
    if local in GENERIC_PREFIXES:
        return False
    return True


def get_existing_campaign_emails(api_key, campaign_id):
    """Fetch all existing lead emails from the Instantly campaign."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    existing = set()
    skip = 0
    limit = 100

    print(f"  Fetching existing campaign leads for dedup...")
    while True:
        try:
            r = requests.get(
                f"{INSTANTLY_BASE}/leads",
                headers=headers,
                params={"campaign": campaign_id, "limit": limit, "skip": skip},
                timeout=15,
            )
            if r.status_code != 200:
                print(f"    Warning: API returned {r.status_code} fetching leads")
                break

            data = r.json()
            # Handle both list and dict responses
            if isinstance(data, list):
                leads = data
            elif isinstance(data, dict):
                leads = data.get("items", data.get("leads", data.get("data", [])))
            else:
                break

            if not leads:
                break

            for lead in leads:
                email = ""
                if isinstance(lead, dict):
                    email = (lead.get("email", "") or "").lower().strip()
                if email:
                    existing.add(email)

            if len(leads) < limit:
                break
            skip += limit
            time.sleep(0.3)
        except requests.exceptions.RequestException as e:
            print(f"    Warning: {e}")
            break

    print(f"    Found {len(existing)} existing leads in campaign")
    return existing


def generate_dental_email(lead):
    """Generate personalized cold email + 3 follow-ups for dental DSO owner."""
    first = lead["first_name"]
    company = lead["company_name"]
    title = lead.get("job_title", "")

    # Personalize based on DSO vs independent
    is_dso = any(dso in company.lower() for dso in [
        "affordable dentures", "aspen dental", "pds health",
        "pacific dental", "clearchoice", "comfort dental",
        "heartland dental", "benevis",
    ])

    if is_dso:
        # DSO owner — they manage a location, corporate handles some ops
        pain_hooks = [
            f"Running a location under {company} means you still own the patient experience",
            f"I know {company} gives you great support, but front desk coverage gaps still cost you patients",
            f"Even with {company}'s systems, missed calls and slow follow-ups still slip through",
        ]
        value_hooks = [
            "picks up every patient call instantly, qualifies the inquiry, and books them on your calendar",
            "answers calls 24/7, handles new patient intake, and follows up with no-shows automatically",
            "captures every inbound call, books appointments, and reactivates patients who haven't been in 6+ months",
        ]
    else:
        # Independent practice owner
        pain_hooks = [
            f"I checked out {company} and noticed you're growing fast",
            f"Most practice owners I talk to at places like {company} are losing 20-30% of new patient calls",
            f"I built something specifically for {company} that I think you should see",
        ]
        value_hooks = [
            "picks up every patient call, qualifies them, and books directly on your calendar",
            "handles new patient calls 24/7, books appointments, and sends automated confirmations",
            "answers every call instantly, does intake, and follows up with patients who cancel or no-show",
        ]

    pain = random.choice(pain_hooks)
    value = random.choice(value_hooks)

    lead["subject"] = f"built something for {company}, {first}"
    lead["body"] = (
        f"Hey {first},\n\n"
        f"{pain}.\n\n"
        f"I built an AI phone agent for dental practices that {value}.\n\n"
        f"Already put together a demo for {company}. What days work for a call?\n\n"
        f"Dylan"
    )

    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"One dental practice we work with went from missing 30% of new patient calls "
        f"to capturing every single one. They added $18K/month in production just from "
        f"the calls they were missing before.\n\n"
        f"Worth a quick look for {company}?\n\n"
        f"Dylan"
    )

    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"Quick math: the average new dental patient is worth $1,200 in year-one production. "
        f"If you're missing even 5 calls a week, that's $25K/month walking out the door.\n\n"
        f"Our AI agent makes sure none of those slip through. What days work for a call?\n\n"
        f"Dylan"
    )

    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Totally get it if now's not the time. The demo I built for {company} "
        f"is here whenever you're ready.\n\n"
        f"Dylan"
    )

    return lead


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
                "job_title": lead.get("job_title", ""),
                "linkedin": lead.get("linkedin", ""),
                "location": lead.get("location", ""),
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

        if (i + 1) % 50 == 0:
            print(f"    Uploaded {i+1}/{len(leads)}...")

        time.sleep(0.3)

    return uploaded, failed, errors


def main():
    parser = argparse.ArgumentParser(description="Clean dental DSO leads and upload to Instantly")
    parser.add_argument("--dry-run", action="store_true", help="Preview without uploading")
    args = parser.parse_args()

    config = load_config()

    print(f"\n{'='*60}")
    print(f"  DENTAL DSO LEAD CLEANER + UPLOADER")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")

    # ── Load raw CSVs ──
    raw = []

    # File 1: Instantly export format
    if os.path.exists(RAW_CSV_1):
        with open(RAW_CSV_1, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw.append({
                    "Email": row.get("Email", ""),
                    "First Name": row.get("First Name", ""),
                    "Last Name": row.get("Last Name", ""),
                    "companyName": row.get("companyName", ""),
                    "jobTitle": row.get("jobTitle", ""),
                    "website": row.get("website", ""),
                    "linkedIn": row.get("linkedIn", ""),
                    "location": row.get("location", ""),
                })
        print(f"\n  File 1 (DSO leads): {sum(1 for r in raw if r.get('Email'))}")

    # File 2: Apollo/enrichment format
    if os.path.exists(RAW_CSV_2):
        count_before = len(raw)
        with open(RAW_CSV_2, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                raw.append({
                    "Email": row.get("Business Email", ""),
                    "First Name": row.get("First Name", ""),
                    "Last Name": row.get("Last Name", ""),
                    "companyName": row.get("Company Name", ""),
                    "jobTitle": row.get("Job Title", ""),
                    "website": row.get("Company URL", ""),
                    "linkedIn": "",
                    "location": row.get("Company Country", ""),
                })
        print(f"  File 2 (Canadian leads): {len(raw) - count_before}")

    print(f"  Total raw: {len(raw)}")

    # ── Fetch existing campaign leads for dedup ──
    existing_emails = get_existing_campaign_emails(config["instantly_api_key"], CAMPAIGN_ID)

    # ── Clean and filter ──
    clean = []
    seen_emails = set()
    rejected = {
        "no_email": 0, "generic_email": 0, "junk_company": 0,
        "not_dental": 0, "dupe_internal": 0, "dupe_campaign": 0,
        "no_name": 0,
    }

    for row in raw:
        email = (row.get("Email", "") or "").lower().strip()
        if not email:
            rejected["no_email"] += 1
            continue

        if not is_owner_email(email):
            rejected["generic_email"] += 1
            continue

        # Internal dedup
        if email in seen_emails:
            rejected["dupe_internal"] += 1
            continue

        # Campaign dedup
        if email in existing_emails:
            rejected["dupe_campaign"] += 1
            continue

        first_name = (row.get("First Name", "") or "").strip()
        last_name = (row.get("Last Name", "") or "").strip()
        if not first_name:
            rejected["no_name"] += 1
            continue

        company = (row.get("companyName", "") or "").strip()
        job_title = (row.get("jobTitle", "") or "").strip()
        website = (row.get("website", "") or "").strip()
        linkedin = (row.get("linkedIn", "") or "").strip()
        location = (row.get("location", "") or "").strip()

        if not company:
            company = "their practice"

        if is_junk_company(company):
            rejected["junk_company"] += 1
            continue

        if not is_dental_company(company, job_title):
            rejected["not_dental"] += 1
            continue

        seen_emails.add(email)
        clean.append({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company,
            "job_title": job_title,
            "website": website,
            "linkedin": linkedin,
            "location": location,
        })

    print(f"\n  Cleaning results:")
    print(f"    Raw: {len(raw)}")
    print(f"    Clean: {len(clean)}")
    print(f"    Rejected: {rejected}")

    # ── Generate personalized emails ──
    print(f"\n  Generating personalized emails...")
    for lead in clean:
        generate_dental_email(lead)

    # ── Stats ──
    by_company = {}
    for lead in clean:
        c = lead["company_name"]
        by_company[c] = by_company.get(c, 0) + 1

    print(f"\n  Top companies:")
    for c, n in sorted(by_company.items(), key=lambda x: -x[1])[:10]:
        print(f"    {c}: {n}")

    print(f"\n  Sample leads:")
    for lead in clean[:8]:
        print(f"    {lead['first_name']} {lead['last_name']} | {lead['email']} | {lead['company_name']} | {lead['job_title']}")

    # ── Save clean CSV ──
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    clean_csv = os.path.join(OUTPUT_DIR, "dental_dso_clean.csv")
    fieldnames = [
        "email", "first_name", "last_name", "company_name", "job_title",
        "website", "linkedin", "location",
        "subject", "body", "followup_1", "followup_2", "followup_3",
    ]
    with open(clean_csv, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(clean)
    print(f"\n  Saved: {clean_csv}")

    if args.dry_run:
        print(f"\n  [DRY RUN] Would upload {len(clean)} leads to campaign {CAMPAIGN_ID}")
        print(f"{'='*60}\n")
        return

    # ── Upload ──
    print(f"\n  Uploading {len(clean)} leads to Instantly...")
    uploaded, failed, errors = upload_to_instantly(
        config["instantly_api_key"], clean, CAMPAIGN_ID
    )

    print(f"\n  Upload complete!")
    print(f"    Uploaded: {uploaded}")
    print(f"    Failed: {failed}")
    if errors:
        print(f"    Sample errors:")
        for err in errors:
            print(f"      {err}")

    print(f"\n{'='*60}")
    print(f"  DONE — {uploaded} dental DSO leads in your campaign")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
