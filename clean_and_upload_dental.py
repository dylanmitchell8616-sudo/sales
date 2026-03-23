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


def _get_practice_type(company, title):
    """Infer practice specialty from company name and job title."""
    combined = f"{company} {title}".lower()
    if "pediatric" in combined or "children" in combined or "kids" in combined:
        return "pediatric dental"
    if "orthodont" in combined or "braces" in combined or "invisalign" in combined:
        return "orthodontic"
    if "oral surgery" in combined or "oral surgeon" in combined:
        return "oral surgery"
    if "endodont" in combined or "root canal" in combined:
        return "endodontic"
    if "periodont" in combined:
        return "periodontic"
    if "cosmetic" in combined or "implant" in combined:
        return "cosmetic dental"
    if "denture" in combined:
        return "denture"
    return "dental"


# Known DSO parent companies and what makes them unique
DSO_CONTEXT = {
    "affordable dentures": {
        "parent": "Affordable Dentures & Implants",
        "note": "you're focused on high-volume denture and implant cases",
        "pain": "patient volume is high and every missed call is a case that walks",
    },
    "aspen dental": {
        "parent": "Aspen Dental",
        "note": "you've got the Aspen brand bringing in demand",
        "pain": "the brand drives a ton of inbound calls, and the ones that slip through voicemail don't call back",
    },
    "pds health": {
        "parent": "PDS Health",
        "note": "PDS gives you great operational support",
        "pain": "even with PDS systems, front desk gaps during lunch, after-hours, and high-volume days still cost you new patients",
    },
    "pacific dental": {
        "parent": "Pacific Dental Services",
        "note": "PDS gives you great operational support",
        "pain": "even with PDS systems, front desk gaps during lunch, after-hours, and high-volume days still cost you new patients",
    },
    "clearchoice": {
        "parent": "ClearChoice",
        "note": "you're handling high-value implant cases",
        "pain": "every missed call on a full-arch case is potentially $25K+ in lost production",
    },
    "comfort dental": {
        "parent": "Comfort Dental",
        "note": "Comfort Dental's model is built on volume and accessibility",
        "pain": "high call volume means your front desk gets overwhelmed, especially during peak hours",
    },
    "heartland dental": {
        "parent": "Heartland Dental",
        "note": "Heartland gives you a strong support system",
        "pain": "but even the best front desk team can't answer 3 calls at once during the morning rush",
    },
    "dental fix": {
        "parent": "Dental Fix Rx",
        "note": "you're running equipment repair and service calls",
        "pain": "when a dentist's chair goes down, they're calling everyone until someone picks up. If you miss that call, they're calling your competitor",
    },
}


def _get_dso_info(company):
    """Get DSO-specific context if this is a known DSO."""
    company_lower = company.lower()
    for key, info in DSO_CONTEXT.items():
        if key in company_lower:
            return info
    return None


def generate_dental_email(lead):
    """Generate hyper-personalized cold email + 3 follow-ups for dental owner."""
    first = lead["first_name"]
    last = lead.get("last_name", "")
    company = lead["company_name"]
    title = lead.get("job_title", "")
    website = lead.get("website", "")
    location = lead.get("location", "")
    linkedin = lead.get("linkedin", "")

    practice_type = _get_practice_type(company, title)
    dso_info = _get_dso_info(company)
    site_display = website.replace("https://", "").replace("http://", "").rstrip("/") if website else ""
    location_str = f" in {location}" if location else ""

    # ── DSO owner email ──
    if dso_info:
        lead["subject"] = random.choice([
            f"{first}, quick idea for your {dso_info['parent']} location",
            f"built something for your practice, {first}",
            f"{first}, thought of your {dso_info['parent']} office",
        ])
        lead["body"] = (
            f"Hey {first},\n\n"
            f"I know {dso_info['note']}, but {dso_info['pain']}.\n\n"
            f"I build custom AI phone agents for {practice_type} practices. I already "
            f"put one together for your location that answers every patient call on the "
            f"first ring, handles new patient intake (insurance, referral source, symptoms, "
            f"scheduling preferences), and books the appointment directly on your calendar.\n\n"
            f"It also follows up with patients who cancel or no-show, and can reactivate "
            f"patients who haven't been in 6+ months. Works 24/7, including evenings and "
            f"weekends when your front desk is closed but patients are still searching.\n\n"
            f"I can walk you through the demo I built for your practice in about 15 minutes. "
            f"What days work for a call?\n\n"
            f"Dylan"
        )
        lead["followup_1"] = (
            f"Hey {first},\n\n"
            f"Wanted to follow up on the AI phone agent I built for your {dso_info['parent']} "
            f"location. Here's what one of our dental clients saw in their first 30 days:\n\n"
            f"- Captured 100% of inbound patient calls (up from ~70%)\n"
            f"- Booked 34 new patients that would have gone to voicemail\n"
            f"- Added $41K in production from calls they were previously missing\n"
            f"- After-hours calls alone accounted for 40% of new bookings\n\n"
            f"The biggest insight? Most patients don't leave voicemails. They just call the "
            f"next practice on Google. Our agent makes sure that never happens at your office.\n\n"
            f"Worth 15 minutes to see how it works for your practice?\n\n"
            f"Dylan"
        )
        lead["followup_2"] = (
            f"Hey {first},\n\n"
            f"Quick math on this. The average new dental patient is worth $1,200 in year-one "
            f"production. If your front desk misses even 5 new patient calls per week (lunch "
            f"breaks, hold times, busy signals, after-hours), that's roughly $25K/month in "
            f"lost production.\n\n"
            f"The AI agent I built for your practice handles unlimited concurrent calls, so "
            f"even when every line is ringing during the Monday morning rush, no patient hits "
            f"voicemail. It qualifies them, books them, and sends your team the details.\n\n"
            f"What days work for a quick call?\n\n"
            f"Dylan"
        )
        lead["followup_3"] = (
            f"Hey {first},\n\n"
            f"Last note from me. I know running your {dso_info['parent']} location keeps you busy "
            f"enough without more sales emails. I genuinely built something that could move the "
            f"needle for your practice, and the demo is here whenever the timing feels right.\n\n"
            f"Just reply whenever you want to take a look. No pressure.\n\n"
            f"All the best,\nDylan"
        )
        return lead

    # ── Independent practice owner email ──
    if site_display:
        opener = (
            f"I was looking at {site_display} and checked out what you're building "
            f"with {company}{location_str}. Great practice."
        )
    elif location:
        opener = (
            f"I've been researching {practice_type} practices in {location} and "
            f"{company} stood out."
        )
    else:
        opener = (
            f"I've been looking into {practice_type} practices like {company} and "
            f"wanted to reach out."
        )

    lead["subject"] = random.choice([
        f"{first}, quick idea for {company}",
        f"built something for {company}",
        f"{first}, something for {company}",
        f"AI phone agent for {company}",
    ])
    lead["body"] = (
        f"Hey {first},\n\n"
        f"{opener}\n\n"
        f"I build custom AI phone agents for {practice_type} practices. I already put one "
        f"together specifically for {company}. It answers every patient call on the first ring, "
        f"handles new patient intake (insurance, symptoms, scheduling preferences), and books "
        f"the appointment directly on your calendar.\n\n"
        f"It also follows up with cancellations, no-shows, and patients who haven't been in "
        f"6+ months to get them back on the schedule. Works 24/7 including after-hours and "
        f"weekends.\n\n"
        f"I can walk you through the demo in about 15 minutes. What days work for a call?\n\n"
        f"Dylan"
    )
    lead["followup_1"] = (
        f"Hey {first},\n\n"
        f"Wanted to circle back on the AI phone agent I built for {company}. Here's a quick "
        f"snapshot of what one of our {practice_type} clients saw in their first 30 days:\n\n"
        f"- Went from missing ~30% of new patient calls to capturing 100%\n"
        f"- Booked 34 additional patients that would've gone to voicemail\n"
        f"- Added $41K in production from calls they were previously losing\n\n"
        f"Their biggest surprise was after-hours. Patients search for dentists at night and on "
        f"weekends. The practices that answer first, win. Our agent makes sure {company} "
        f"never misses those calls.\n\n"
        f"Happy to show you what that looks like for your practice. Worth 15 minutes?\n\n"
        f"Dylan"
    )
    lead["followup_2"] = (
        f"Hey {first},\n\n"
        f"Quick math: the average new dental patient is worth $1,200 in year-one production. "
        f"If {company} is missing even 5 new patient calls per week (lunch breaks, hold times, "
        f"after-hours), that's roughly $25K/month walking out the door.\n\n"
        f"The agent I built for {company} handles unlimited concurrent calls. Even during your "
        f"busiest mornings, no patient hits voicemail. It qualifies them, books them, and sends "
        f"your front desk the details.\n\n"
        f"What days work for a quick call?\n\n"
        f"Dylan"
    )
    lead["followup_3"] = (
        f"Hey {first},\n\n"
        f"Last note from me. I know you're busy running {company} and the last thing you need "
        f"is more sales emails. The demo I built specifically for your practice is here whenever "
        f"the timing feels right.\n\n"
        f"Just reply whenever you want to take a look. No pressure at all.\n\n"
        f"All the best{location_str},\nDylan"
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
