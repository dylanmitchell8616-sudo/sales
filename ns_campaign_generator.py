#!/usr/bin/env python3
"""
Niche-Specific Campaign Generator (Claude-Powered)
====================================================
Generates fully custom, AI-written emails for each lead using Claude API.
No templates, no variable swaps. Each email is uniquely crafted per business.

Input CSV must have columns: email, first_name, last_name, company_name, niche, city, rating, reviews, website
(Optional columns: state, phone, linkedin, job_title)

Usage:
    python ns_campaign_generator.py --input leads.csv
    python ns_campaign_generator.py --input leads.csv --output output/ns_campaign.csv
    python ns_campaign_generator.py --input leads.csv --resume  # resume from checkpoint
    python ns_campaign_generator.py --input leads.csv --dry-run --limit 3  # test with 3 leads
"""

import argparse
import csv
import json
import os
import sys
import time
import random
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
DEFAULT_OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CHECKPOINT_SUFFIX = ".checkpoint.json"

MODEL = "claude-sonnet-4-20250514"
DELAY_MIN = 1.0  # min seconds between API calls
DELAY_MAX = 2.5  # max seconds between API calls

# Niche-to-product mapping — inbound for almost everything
# Only insurance and staffing get outbound pitch
PRODUCT_MAP = {
    "insurance": "outbound",
    "staffing": "recruiting",
    # Everything else defaults to inbound receptionist
}

# Niche-specific pain points for richer prompt context
NICHE_PAIN_POINTS = {
    "med spa": [
        "Front desk gets slammed during peak hours and calls go to voicemail",
        "New patient inquiries from ads sit for hours before anyone follows up",
        "Botox and filler consultations lost because nobody answered the phone at 7pm",
        "Repeat clients can't book easily and end up going to a competitor",
    ],
    "dental": [
        "Hygienist schedule has gaps because recall patients aren't being called",
        "New patient calls ring out during lunch hour when front desk is short-staffed",
        "Emergency calls after hours go to a generic voicemail that nobody checks until morning",
        "Insurance verification calls eat up half the front desk's day",
    ],
    "wellness": [
        "Clients call to book but hang up after 4 rings when the practitioner is in session",
        "Class and appointment reminders are manual and no-show rates are climbing",
        "New lead inquiries from Google sit in a contact form for days",
        "Phone tag with potential clients who want to ask about services before booking",
    ],
    "plastic surgery": [
        "High-value consult requests go unanswered after hours",
        "Prospective patients researching procedures call multiple clinics and book whoever picks up first",
        "Front desk spends 30 minutes per call explaining financing options",
        "Post-op follow-up calls are falling through the cracks",
    ],
    "iv therapy": [
        "Walk-in and call-in demand spikes are unpredictable and the phone gets overwhelmed",
        "Group bookings and party inquiries need fast follow-up or they book elsewhere",
        "Membership and package upsells aren't happening because staff is too busy",
        "After-hours calls from people feeling sick go straight to voicemail",
    ],
    "chiropractic": [
        "New patient calls during adjustments go unanswered",
        "Reactivation of lapsed patients isn't happening because there's no bandwidth",
        "Insurance and billing questions eat up front desk time",
        "After-hours calls from people in pain go to voicemail",
    ],
    "insurance": [
        "Speed-to-lead on new quote requests is way too slow",
        "Renewal follow-ups aren't happening consistently",
        "Old leads in the CRM are gathering dust with no one to call them",
        "Agents spend half their day on outbound calls that don't connect",
    ],
    "recruiting": [
        "Candidate outreach is bottlenecked by how many calls recruiters can make per day",
        "Hot candidates go cold because follow-up takes too long",
        "Sourced candidates sit in the ATS without a first touch for days",
        "Phone screens for high-volume roles eat up senior recruiter time",
    ],
    "staffing": [
        "Speed-to-contact on new applicants determines placement rates",
        "Database of past candidates isn't being worked because there aren't enough callers",
        "No-shows spike when confirmation calls don't happen",
        "After-hours applicant calls go unanswered and they apply at the next agency",
    ],
    "hvac": [
        "Emergency calls at 2am go to voicemail and the customer calls the next company",
        "Busy season means the phone rings nonstop and half the calls get missed",
        "Estimate requests pile up and customers book whoever responds first",
        "Techs are on the road and nobody's answering the office line",
    ],
    "plumbing": [
        "Emergency leak calls after hours go straight to voicemail",
        "Missed calls during the day because everyone's out on jobs",
        "Estimate follow-ups fall through the cracks when things get busy",
        "Customers call 3 plumbers and book whoever picks up first",
    ],
    "electrical": [
        "Customers need someone NOW and if you don't pick up they call the next guy",
        "Office phone rings out when you're on a job site",
        "Quote requests sit in voicemail for hours during busy weeks",
        "After-hours emergency calls are going to competitors",
    ],
    "roofing": [
        "Storm season hits and the phone explodes — half the calls get missed",
        "Estimate requests from homeowners go cold if you don't respond same day",
        "Crews are on roofs all day and nobody's manning the phone",
        "Insurance claim calls need fast response or the homeowner moves on",
    ],
    "landscaping": [
        "Spring rush means 50 calls a day and you can't answer them all",
        "Quote requests from new customers go to voicemail while crews are out",
        "Seasonal customers don't get called back for spring startup",
        "Phone rings while you're on the mower and the customer calls someone else",
    ],
    "pest_control": [
        "Panicked customers with a bug problem call whoever picks up first",
        "Seasonal spikes mean the phone is ringing off the hook",
        "Recurring service reminders aren't going out consistently",
        "After-hours calls from people with urgent pest issues go to voicemail",
    ],
    "real_estate": [
        "Zillow and Realtor.com leads sit for hours before anyone calls them back",
        "Open house sign-in leads never get a follow-up call",
        "Past clients aren't getting touched for referrals or repeat business",
        "Speed-to-lead determines who gets the listing and most agents are too slow",
    ],
    "law_firm": [
        "Potential clients call after hours and hire whoever picks up the phone",
        "Intake calls during court or meetings go to voicemail",
        "Leads from Google Ads aren't getting called back fast enough",
        "Front desk is doing intake, scheduling, and admin all at once",
    ],
    "accounting": [
        "Tax season means 100 calls a day and half go to voicemail",
        "New client inquiries sit in the inbox while staff handles existing clients",
        "After-hours calls from anxious business owners go unanswered",
        "Phone tag with clients wastes hours every week",
    ],
    "auto_repair": [
        "Customers calling for quotes book whoever answers first",
        "Service advisors are busy with walk-ins and can't answer every call",
        "Recall and maintenance reminders aren't going out to past customers",
        "After-hours calls from people with car trouble go to voicemail",
    ],
    "car_dealership": [
        "Internet leads go cold if you don't call back within 5 minutes",
        "Service department phones ring nonstop and customers get frustrated",
        "Sales follow-ups fall through the cracks during busy weekends",
        "After-hours inquiries from serious buyers sit until Monday morning",
    ],
    "fitness": [
        "Trial and membership inquiries call once and if nobody answers they join somewhere else",
        "No-shows for classes and PT sessions cost you money every week",
        "New leads from Instagram ads don't get a call back for days",
        "Front desk is checking people in and can't answer the phone",
    ],
    "homecare": [
        "Families calling about care for a loved one need someone NOW, not a voicemail",
        "Referral calls from hospitals go to voicemail after hours",
        "New client inquiries sit in the inbox while caregivers are on assignments",
        "Follow-up calls to families aren't happening consistently",
    ],
    "salon": [
        "Clients call to book but stylists are mid-appointment and can't answer",
        "Walk-in heavy days mean the phone gets ignored",
        "Rebooking and recall reminders aren't going out to past clients",
        "After-hours booking requests go to voicemail and they book somewhere else",
    ],
    "spa": [
        "Clients call to book but therapists are in session and front desk is busy",
        "Gift certificate and package inquiries need quick follow-up",
        "Cancellation slots could be filled if someone was calling the waitlist",
        "Weekend and evening inquiries go unanswered until Monday",
    ],
    "optometry": [
        "New patient calls go to voicemail during lunch or when staff is with patients",
        "Annual exam recalls aren't going out consistently",
        "Contact lens reorder calls eat up front desk time",
        "After-hours calls from parents with kids' eye emergencies go to voicemail",
    ],
    "mental_health": [
        "Someone reaching out for help calls once — if nobody answers, they don't call back",
        "Therapists are in session all day and can't answer intake calls",
        "New client inquiries from Psychology Today or Google sit for days",
        "After-hours calls from people in crisis hit a voicemail",
    ],
    "physiotherapy": [
        "New patient referrals from doctors need to be booked quickly or they go elsewhere",
        "Therapists are treating patients and can't answer the phone",
        "Recall appointments for ongoing treatment aren't being followed up",
        "After-hours calls from athletes and post-surgery patients go to voicemail",
    ],
}

def load_config():
    """Load config.json and return dict."""
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: config.json not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        return json.load(f)


def get_product_pitch(niche: str) -> str:
    """Determine which product to pitch based on niche."""
    niche_lower = niche.lower().strip()
    for keyword, product in PRODUCT_MAP.items():
        if keyword in niche_lower:
            return product
    return "inbound"


def get_pain_points(niche: str) -> list:
    """Get niche-specific pain points, falling back to generic ones."""
    niche_lower = niche.lower().strip()
    for key, points in NICHE_PAIN_POINTS.items():
        if key in niche_lower:
            return points
    # Generic fallback
    return [
        "Missed calls during busy hours mean lost revenue",
        "New leads from ads and Google sit too long before follow-up",
        "Front desk is stretched thin juggling phones, walk-ins, and admin",
        "After-hours callers hit voicemail and book with a competitor instead",
    ]


def build_generation_prompt(lead: dict) -> str:
    """Build the Claude prompt for generating a custom email for this lead."""
    product = get_product_pitch(lead.get("niche", ""))
    pain_points = get_pain_points(lead.get("niche", ""))

    if product == "recruiting":
        product_description = (
            "AI Recruiting Agent that screens applicants instantly, schedules interviews, "
            "and follows up with candidates automatically. Cuts time-to-fill in half."
        )
        product_label = "AI Recruiting Agent"
    elif product == "outbound":
        product_description = (
            "AI Outbound Agent that calls and texts new leads within 2 minutes, "
            "re-engages dormant CRM leads, and books appointments automatically. "
            "Plus an AI Inbound Receptionist that answers every call 24/7. Full package."
        )
        product_label = "AI Outbound Agent + Inbound Receptionist"
    else:
        product_description = (
            "AI Inbound Receptionist that answers every incoming call 24/7, "
            "books appointments, handles FAQs, follows up on missed calls, and does live transfers. "
            "Recovers 20-40% of missed calls and adds 10-25% more bookings."
        )
        product_label = "AI Inbound Receptionist"

    # Build lead context block
    lead_context_parts = []
    lead_context_parts.append(f"Company: {lead.get('company_name', 'Unknown')}")
    if lead.get("first_name"):
        lead_context_parts.append(f"Contact first name: {lead['first_name']}")
    if lead.get("last_name"):
        lead_context_parts.append(f"Contact last name: {lead['last_name']}")
    if lead.get("job_title"):
        lead_context_parts.append(f"Title: {lead['job_title']}")
    lead_context_parts.append(f"Niche: {lead.get('niche', 'service business')}")
    if lead.get("city"):
        lead_context_parts.append(f"City: {lead['city']}")
    if lead.get("state"):
        lead_context_parts.append(f"State: {lead['state']}")
    if lead.get("rating"):
        lead_context_parts.append(f"Google rating: {lead['rating']}")
    if lead.get("reviews"):
        lead_context_parts.append(f"Google review count: {lead['reviews']}")
    if lead.get("website"):
        lead_context_parts.append(f"Website: {lead['website']}")

    lead_context = "\n".join(lead_context_parts)

    pain_points_text = "\n".join(f"- {p}" for p in pain_points)

    prompt = f"""You are Dylan Mitchell, founder of Realside AI. Write a cold outreach email to this specific business.

LEAD DATA:
{lead_context}

PRODUCT TO PITCH: {product_label}
{product_description}

NICHE-SPECIFIC PAIN POINTS (use 1-2 naturally, don't list them all):
{pain_points_text}

RULES (follow every single one):
1. The email must feel like Dylan personally wrote it for THIS business. Reference specific details: their city, their Google reviews/rating, their niche, their company name. Make it feel like you actually looked them up.
2. Under 120 words. Tight and punchy.
3. Tone: friendly, confident, casual. Like a real person reaching out to a business owner. Not corporate, not salesy, not robotic.
4. Never use '--' (double dashes) anywhere.
5. Vary the structure. Don't start with "Hi [name]" every time. Mix up openers: sometimes lead with an observation, a question, a compliment, a stat. Be creative.
6. End with a soft CTA: either a casual question or the Calendly link (https://calendly.com/realsideai). Alternate between these.
7. Sign off as Dylan from Realside AI. Vary sign-offs (Cheers, Best, Talk soon, etc.)
8. Do NOT use generic filler ("I hope this email finds you well", "I wanted to reach out", "I came across your company"). Get straight to the point.
9. Do NOT over-explain the product. Spark curiosity. The goal is to get them on a call, not close via email.
10. If the lead has a first_name, use it naturally. If not, address the team or company.

SUBJECT LINE RULES:
- Short (3-8 words max)
- Curiosity-driven and personalized (use company name, city, or niche reference)
- Lowercase is fine. No clickbait. No emojis.
- Should feel like a subject line from someone they know, not a marketing email

Return your response in this exact JSON format (no markdown, no code fences):
{{"subject": "your subject line here", "body": "your email body here"}}"""

    return prompt


def generate_email(client: anthropic.Anthropic, lead: dict) -> dict:
    """Call Claude to generate a fully custom email for one lead."""
    prompt = build_generation_prompt(lead)

    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.9,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Parse JSON response
    # Strip markdown fences if Claude added them
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                result = json.loads(text[start:end])
            except json.JSONDecodeError:
                print(f"  WARNING: Could not parse Claude response for {lead.get('company_name', '?')}")
                print(f"  Raw response: {text[:200]}")
                return None
        else:
            print(f"  WARNING: No JSON found in response for {lead.get('company_name', '?')}")
            return None

    subject = result.get("subject", "").strip()
    body = result.get("body", "").strip()

    if not subject or not body:
        print(f"  WARNING: Empty subject or body for {lead.get('company_name', '?')}")
        return None

    # Enforce no '--' rule
    body = body.replace("--", "\u2014")
    subject = subject.replace("--", "\u2014")

    return {"subject": subject, "body": body}


def load_checkpoint(checkpoint_path: str) -> set:
    """Load set of already-processed email addresses from checkpoint."""
    if not os.path.exists(checkpoint_path):
        return set()
    with open(checkpoint_path) as f:
        data = json.load(f)
    return set(data.get("processed", []))


def save_checkpoint(checkpoint_path: str, processed: set):
    """Save processed email set to checkpoint file."""
    with open(checkpoint_path, "w") as f:
        json.dump({"processed": sorted(processed), "updated": datetime.now().isoformat()}, f)


def read_leads(input_path: str) -> list:
    """Read the input leads CSV and return list of dicts."""
    if not os.path.exists(input_path):
        print(f"Error: Input file not found: {input_path}")
        sys.exit(1)

    leads = []
    with open(input_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # Normalize column names to lowercase/stripped
            lead = {k.strip().lower().replace(" ", "_"): v.strip() if v else "" for k, v in row.items()}
            # Skip rows with no email
            if not lead.get("email"):
                continue
            leads.append(lead)

    return leads


def main():
    parser = argparse.ArgumentParser(description="Generate fully custom AI-written campaign emails")
    parser.add_argument("--input", required=True, help="Path to input leads CSV")
    parser.add_argument("--output", default=None, help="Path to output campaign CSV (default: output/ns_campaign_TIMESTAMP.csv)")
    parser.add_argument("--campaign-name", default=None, help="Campaign name for the output (default: auto from input filename)")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint (skip already-processed leads)")
    parser.add_argument("--dry-run", action="store_true", help="Print generated emails instead of saving")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N leads (0 = all)")
    args = parser.parse_args()

    # Load config
    config = load_config()
    api_key = config.get("anthropic_api_key")
    if not api_key:
        print("Error: anthropic_api_key not found in config.json")
        sys.exit(1)

    # Set up paths
    input_path = os.path.abspath(args.input)
    if args.output:
        output_path = os.path.abspath(args.output)
    else:
        os.makedirs(DEFAULT_OUTPUT_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_name = os.path.splitext(os.path.basename(input_path))[0]
        output_path = os.path.join(DEFAULT_OUTPUT_DIR, f"ns_{base_name}_{timestamp}.csv")

    checkpoint_path = output_path + CHECKPOINT_SUFFIX

    # Campaign name
    if args.campaign_name:
        campaign_name = args.campaign_name
    else:
        base = os.path.splitext(os.path.basename(input_path))[0]
        campaign_name = f"Realside AI — NS {base.replace('_', ' ').title()}"

    # Read leads
    leads = read_leads(input_path)
    if not leads:
        print("No leads found in input CSV. Make sure it has an 'email' column.")
        sys.exit(1)

    if args.limit > 0:
        leads = leads[: args.limit]

    # Load checkpoint for resume
    processed_emails = set()
    if args.resume:
        processed_emails = load_checkpoint(checkpoint_path)
        print(f"Resuming: {len(processed_emails)} leads already processed")

    # Filter out already-processed leads
    remaining = [l for l in leads if l["email"] not in processed_emails]
    print(f"Input: {len(leads)} leads total, {len(remaining)} to process")
    print(f"Output: {output_path}")
    print(f"Campaign: {campaign_name}")
    print(f"Model: {MODEL}")
    print()

    if not remaining:
        print("All leads already processed. Nothing to do.")
        return

    # Initialize Claude client
    client = anthropic.Anthropic(api_key=api_key)

    # Open output CSV (append if resuming, write new if not)
    file_exists = os.path.exists(output_path) and args.resume
    output_fields = [
        "email", "first_name", "last_name", "company_name", "subject", "body",
        "website", "linkedin", "job_title", "location", "niche", "rating",
        "reviews", "campaign_name", "personalized"
    ]

    mode = "a" if file_exists else "w"
    outfile = open(output_path, mode, newline="", encoding="utf-8")
    writer = csv.DictWriter(outfile, fieldnames=output_fields, extrasaction="ignore")
    if not file_exists:
        writer.writeheader()

    # Process each lead
    success_count = 0
    fail_count = 0
    start_time = time.time()

    for i, lead in enumerate(remaining, 1):
        company = lead.get("company_name", "Unknown")
        email = lead["email"]
        print(f"[{i}/{len(remaining)}] Generating email for {company} ({email})...", end=" ", flush=True)

        try:
            result = generate_email(client, lead)
        except anthropic.RateLimitError:
            print("RATE LIMITED. Waiting 30s...")
            time.sleep(30)
            try:
                result = generate_email(client, lead)
            except Exception as e:
                print(f"FAILED after retry: {e}")
                fail_count += 1
                continue
        except Exception as e:
            print(f"ERROR: {e}")
            fail_count += 1
            continue

        if result is None:
            fail_count += 1
            print("SKIPPED (parse error)")
            continue

        # Build output row
        location_parts = []
        if lead.get("city"):
            location_parts.append(lead["city"])
        if lead.get("state"):
            location_parts.append(lead["state"])
        location = ", ".join(location_parts)

        row = {
            "email": email,
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": company,
            "subject": result["subject"],
            "body": result["body"],
            "website": lead.get("website", ""),
            "linkedin": lead.get("linkedin", ""),
            "job_title": lead.get("job_title", ""),
            "location": location,
            "niche": lead.get("niche", ""),
            "rating": lead.get("rating", ""),
            "reviews": lead.get("reviews", ""),
            "campaign_name": campaign_name,
            "personalized": "true",
        }

        if args.dry_run:
            print("OK")
            print(f"  Subject: {result['subject']}")
            print(f"  Body:\n    " + result["body"].replace("\n", "\n    "))
            print()
        else:
            writer.writerow(row)
            outfile.flush()
            print("OK")

        # Track progress
        processed_emails.add(email)
        success_count += 1

        # Save checkpoint every 5 leads
        if success_count % 5 == 0 and not args.dry_run:
            save_checkpoint(checkpoint_path, processed_emails)

        # Rate limiting: random delay between API calls
        if i < len(remaining):
            delay = random.uniform(DELAY_MIN, DELAY_MAX)
            time.sleep(delay)

    outfile.close()

    # Final checkpoint save
    if not args.dry_run:
        save_checkpoint(checkpoint_path, processed_emails)

    # Summary
    elapsed = time.time() - start_time
    print()
    print("=" * 50)
    print(f"Done in {elapsed:.1f}s")
    print(f"  Successful: {success_count}")
    print(f"  Failed:     {fail_count}")
    if not args.dry_run:
        print(f"  Output:     {output_path}")
        print(f"  Campaign:   {campaign_name}")
    print()

    # Clean up checkpoint if everything succeeded
    if fail_count == 0 and not args.dry_run and os.path.exists(checkpoint_path):
        os.remove(checkpoint_path)
        print("Checkpoint cleaned up (all leads processed successfully)")


if __name__ == "__main__":
    main()
