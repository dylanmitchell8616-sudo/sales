#!/usr/bin/env python3
"""
Generate bulk HVAC cold email campaign for AI voice agents.
Uses the Evergreen lead scaling system (Supersearch + Apify) for sourcing.

Usage:
    python generate_hvac_campaign.py                              # Generate from local leads
    python generate_hvac_campaign.py --scale --target 1000        # Scale via Evergreen engine
    python generate_hvac_campaign.py --create-evergreen           # Auto-fill campaign on Instantly
    python generate_hvac_campaign.py --scale --target 1000 --dry-run
"""

import argparse
import csv
import json
import os
import random
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

INPUT_FILE = os.path.join(SCRIPT_DIR, "output", "hvac_leads.json")
OUTPUT_FILE = os.path.join(SCRIPT_DIR, "output", "hvac_campaign_emails.csv")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# ---------------------------------------------------------------------------
# Cold email copy for AI voice agents targeting HVAC
# ---------------------------------------------------------------------------

OPENERS = [
    "Hey {first_name}, saw {company} is one of the top HVAC companies in {city}",
    "Hi {first_name}, came across {company} and had a quick thought",
    "Hey {first_name}, noticed {company} has been growing in {city}",
    "{first_name}, quick question for you",
    "Hi {first_name}, been looking at HVAC companies in {city} and {company} caught my eye",
]

PAIN_HOOKS = [
    "I know peak season gets insane with phones ringing nonstop. Missed calls during summer rushes can mean thousands in lost revenue per week.",
    "Most HVAC owners I talk to say the same thing: when it's 100 degrees outside, every call matters. But your team can't answer them all while they're out on jobs.",
    "Talked to a few HVAC owners recently who said they're losing 20-30% of inbound calls during peak because the team is in the field.",
    "HVAC is one of those businesses where a missed call on a hot day means a homeowner just calls the next company on Google. That revenue is gone.",
    "Running crews, handling dispatch, and managing phones all at once is a lot. Especially when AC season hits and call volume doubles overnight.",
]

VALUE_PROPS = [
    "We build custom AI voice agents for HVAC companies that pick up every call 24/7, qualify the lead, book the appointment, and send your team the details instantly.",
    "We set up an AI receptionist that answers every call for HVAC companies. It handles new customer intake, books service appointments, and does after-hours emergency triage.",
    "We deploy AI phone agents for HVAC companies that never miss a call. They qualify leads, book jobs on the calendar, and text your techs the details.",
    "We set up AI phone agents that handle inbound calls, qualify the job type, book the appointment, and follow up with the homeowner automatically.",
    "We build AI voice agents that answer every call, capture lead info, schedule appointments, and make sure no revenue slips through the cracks.",
]

CTAS = [
    "Want to see how it works? What days work for a call?",
    "Happy to walk you through it. What days work?",
    "I can show you in 15 minutes. What days work for a call?",
]

FOLLOWUP_1 = [
    "Hey {first_name}, just wanted to bump this up. I know things get busy running {company}. The AI agent I mentioned could save your team hours every week on phone duty alone. Worth a quick look?",
    "{first_name}, following up. One HVAC company we work with went from missing 30% of calls to capturing 100% within the first week. Happy to share how. What days work?",
    "Hi {first_name}, circling back. We've been working with HVAC companies in {state} and the results have been solid. If you're curious, I can show you in 15 minutes.",
]

FOLLOWUP_2 = [
    "{first_name}, one HVAC company captured an extra $47K last month just by answering the calls they were missing. Want to see how it works for {company}?",
    "Hey {first_name}, call volume is about to spike this season. Having an AI agent ready before the rush could be huge for {company}. Worth a quick call?",
    "{first_name}, we just launched emergency dispatch prioritization for HVAC. Thought {company} might benefit. Worth a chat?",
]

FOLLOWUP_3 = [
    "{first_name}, if {company} ever needs help handling more calls without hiring, just reply. No pressure.",
    "Hey {first_name}, totally get it if now isn't the time. Door's open whenever {company} wants to explore AI for your phones.",
    "{first_name}, last note from me. Think this could help {company} capture more revenue. Reply anytime if you're curious.",
]

# HVAC Evergreen search filters for US + Canada
HVAC_EVERGREEN_FILTERS = {
    "titles": [
        "owner", "ceo", "founder", "president", "general manager",
        "operations manager", "office manager", "managing partner",
    ],
    "industries": [
        "construction", "consumer services", "building materials",
        "mechanical or industrial engineering",
    ],
    "employee_ranges": ["11-50", "51-200", "201-500"],
    "locations": ["United States", "Canada"],
    "keywords": [
        "hvac", "heating and air", "air conditioning", "heating cooling",
        "furnace", "ac repair", "hvac contractor", "plumbing heating",
        "heating ventilation", "climate control",
    ],
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def generate_email_pattern(first_name, last_name, domain):
    first = first_name.lower().strip()
    last = last_name.lower().strip()
    if not first or not last:
        return f"info@{domain}"
    return f"{first}@{domain}"


def extract_city_state(location):
    parts = [p.strip() for p in location.split(",")]
    city = parts[0] if parts else location
    state = parts[1] if len(parts) > 1 else ""
    return city, state


def personalize_email(lead):
    first_name = lead.get("first_name", "")
    last_name = lead.get("last_name", "")
    company = lead.get("company_name", lead.get("company", "your company"))
    location = lead.get("location", lead.get("city", ""))
    domain = lead.get("domain", "")
    if not domain:
        website = lead.get("website", "")
        domain = website.replace("https://", "").replace("http://", "").split("/")[0] if website else ""
    email = lead.get("email", "")

    city, state = extract_city_state(location)

    if not email and domain and first_name:
        email = generate_email_pattern(first_name, last_name, domain)

    opener = random.choice(OPENERS).format(
        first_name=first_name or "there", company=company, city=city or "your area"
    )
    pain = random.choice(PAIN_HOOKS)
    value = random.choice(VALUE_PROPS)
    cta = random.choice(CTAS)

    body = f"{opener}.\n\n{pain}\n\n{value}\n\n{cta}\n\nDylan"

    fu1 = random.choice(FOLLOWUP_1).format(
        first_name=first_name or "there", company=company, city=city, state=state
    )
    fu2 = random.choice(FOLLOWUP_2).format(
        first_name=first_name or "there", company=company, city=city, state=state
    )
    fu3 = random.choice(FOLLOWUP_3).format(
        first_name=first_name or "there", company=company, city=city, state=state
    )

    subject_options = [
        f"quick question about {company}",
        f"idea for {company}",
        f"missed calls at {company}?",
    ]
    if first_name:
        subject_options.append(f"{first_name}, AI for HVAC calls")
    if city:
        subject_options.append(f"{city} HVAC + AI")

    return {
        "first_name": first_name,
        "last_name": last_name,
        "email": email,
        "company_name": company,
        "title": lead.get("title", ""),
        "location": location,
        "linkedin": lead.get("linkedin", lead.get("url", "")),
        "domain": domain,
        "subject": random.choice(subject_options),
        "body": body,
        "followup_1": fu1,
        "followup_2": fu2,
        "followup_3": fu3,
    }


def generate_from_local():
    if not os.path.exists(INPUT_FILE):
        print(f"Error: {INPUT_FILE} not found")
        return []
    with open(INPUT_FILE, encoding="utf-8") as f:
        leads = json.load(f)
    return [personalize_email(lead) for lead in leads]


def generate_at_scale(target=1000, locations=None, dry_run=False, campaign_id=None):
    """Use the lead scaling engine (Evergreen + Supersearch + Apify) at scale."""
    try:
        from lead_scaling_engine import run_pipeline
    except ImportError:
        print("Error: lead_scaling_engine.py not found.")
        return []

    config = load_config()
    instantly_key = config.get("instantly_api_key", "")
    apify_key = config.get("apify_api_key", "")

    if not instantly_key:
        print("Error: No instantly_api_key in config.json")
        return []

    if not locations:
        locations = [
            # US Sun Belt (highest HVAC demand)
            "Phoenix AZ", "Dallas TX", "Houston TX", "Miami FL",
            "Atlanta GA", "Las Vegas NV", "San Antonio TX", "Tampa FL",
            "Charlotte NC", "Austin TX", "Nashville TN", "Orlando FL",
            "Jacksonville FL", "Oklahoma City OK", "Tucson AZ",
            # US Northeast / Midwest (heating demand)
            "Chicago IL", "New York NY", "Philadelphia PA", "Boston MA",
            "Detroit MI", "Minneapolis MN", "Denver CO", "Indianapolis IN",
            "Columbus OH", "Kansas City MO", "St Louis MO", "Pittsburgh PA",
            # Canada
            "Toronto ON", "Vancouver BC", "Calgary AB", "Edmonton AB",
            "Ottawa ON", "Montreal QC", "Winnipeg MB", "Halifax NS",
            "Saskatoon SK", "Hamilton ON",
        ]

    print(f"\n=== HVAC Lead Scaling: Target {target} leads (US + Canada) ===")
    print(f"  Using Evergreen + Supersearch + Apify pipeline")
    print(f"  {len(locations)} metros across US and Canada")

    raw_leads = run_pipeline(
        instantly_key, apify_key,
        target=target,
        campaign_id=campaign_id,
        niches=["hvac"],
        locations=locations,
        dry_run=dry_run,
    )

    if dry_run:
        print(f"\n  [DRY RUN] Would generate personalized emails for {target} leads")
        return []

    return [personalize_email(lead) for lead in raw_leads if lead.get("email")]


def create_evergreen_hvac(dry_run=False):
    """Create an auto-filling Evergreen HVAC campaign on Instantly."""
    try:
        from instantly_evergreen import create_evergreen_campaign, list_sending_accounts
    except ImportError:
        print("Error: instantly_evergreen.py not found.")
        return

    config = load_config()
    api_key = config.get("instantly_api_key", "")
    if not api_key:
        print("Error: No instantly_api_key in config.json")
        return

    accounts = list_sending_accounts(api_key)
    if not accounts:
        print("Error: No sending accounts found in Instantly.")
        return

    account_emails = [a.get("email", a.get("id")) for a in accounts]

    create_evergreen_campaign(
        api_key,
        name="HVAC AI Voice Agent Outreach (Evergreen)",
        sending_accounts=account_emails,
        schedule_preset="aggressive",
        search_filters=HVAC_EVERGREEN_FILTERS,
        dry_run=dry_run,
    )

    print("\nEvergreen campaign created! It will auto-add 30 HVAC leads/day.")
    print("Activate it in Instantly when ready.")


def export_csv(rows, output_path=None):
    output_path = output_path or OUTPUT_FILE
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fieldnames = [
        "first_name", "last_name", "email", "company_name", "title",
        "location", "linkedin", "domain", "subject", "body",
        "followup_1", "followup_2", "followup_3",
    ]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nGenerated {len(rows)} HVAC campaign emails -> {output_path}")
    companies = set(r["company_name"] for r in rows)
    print(f"Companies covered: {len(companies)}")
    for c in sorted(companies)[:20]:
        count = sum(1 for r in rows if r["company_name"] == c)
        print(f"  - {c}: {count} contacts")
    if len(companies) > 20:
        print(f"  ... and {len(companies) - 20} more")
    print(f"\nReady for Instantly upload!")


def main():
    parser = argparse.ArgumentParser(description="HVAC Bulk Cold Email Campaign Generator")
    parser.add_argument("--scale", action="store_true",
                        help="Use Evergreen/Supersearch/Apify to find leads at scale")
    parser.add_argument("--target", type=int, default=1000,
                        help="Target number of leads (default: 1000)")
    parser.add_argument("--locations", help="Comma-separated locations")
    parser.add_argument("--campaign-id", help="Upload directly to this Instantly campaign")
    parser.add_argument("--create-evergreen", action="store_true",
                        help="Create auto-filling Evergreen HVAC campaign on Instantly")
    parser.add_argument("--output", help="Custom output CSV path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    if args.create_evergreen:
        create_evergreen_hvac(dry_run=args.dry_run)
        return

    locations = [l.strip() for l in args.locations.split(",")] if args.locations else None

    if args.scale:
        rows = generate_at_scale(
            target=args.target, locations=locations,
            dry_run=args.dry_run, campaign_id=args.campaign_id,
        )
    else:
        rows = generate_from_local()

    if rows:
        export_csv(rows, args.output)


if __name__ == "__main__":
    main()
