#!/usr/bin/env python3
"""
AI Recruiting Campaign Generator — Social Proof Edition
=========================================================
Generates a 3-step cold email sequence for selling AI recruiting services
to homecare agencies and staffing firms. Each lead gets a personalized
first line + social-proof-driven copy.

Usage:
    python recruiting_campaign_generator.py --input output/recruiting_leads.csv
    python recruiting_campaign_generator.py --input output/recruiting_leads.csv --dry-run
    python recruiting_campaign_generator.py --input output/recruiting_leads.csv --enrich
"""

import argparse
import csv
import json
import logging
import os
import random
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── Campaign copy templates ───────────────────────────────────────────────────
# These use {{custom_first_line}}, {{first_name}}, {{company_name}} variables
# that get replaced per-lead. The sequence is 3 steps with escalating social proof.

CAMPAIGN_NAME = "AI Recruiting - Social Proof"

# ─── Email Step 1: Lead with the problem + social proof ────────────────────────
STEP1_SUBJECT_TEMPLATES = [
    "{{company_name}}, 43% of your interviews are no-shows",
    "{{company_name}} is losing candidates in the first 2 hours",
    "76% of recruiters got ghosted last year",
    "{{first_name}}, what if screening took 2 minutes instead of 16 hours?",
]

STEP1_BODY = """{{custom_first_line}}

Here's a stat that probably feels familiar: 43% of interviews in staffing are no-shows, and 76% of recruiters say they've been ghosted by candidates. The problem isn't finding applicants. It's that by the time someone calls them back, they've already taken another offer.

We built an AI that handles the entire recruiting process from application to final interview. The moment a candidate applies, our AI screens them, asks qualifying questions, checks availability, and books the interview on your team's calendar. Your recruiters only talk to pre-qualified, ready-to-start candidates.

{{testimonial_placeholder}}

Would a 15-minute call make sense to see how this fits {{company_name}}?

{{calendar_link}}

{{sender_name}}
{{sender_email}}"""

# ─── Email Step 2: Case study / proof stack (Day 3) ───────────────────────────
STEP2_SUBJECT_TEMPLATES = [
    "The $171K problem nobody at {{company_name}} is measuring",
    "Re: {{company_name}} hiring process",
    "Quick math on what slow screening costs {{company_name}}",
]

STEP2_BODY = """Hey {{first_name}},

Quick follow-up with some numbers that might sting.

The average agency spends $2,600-$5,000 per hire and takes 25-45 days to fill a role. With 77% annual turnover, a 100-person team burns $171K+/year just replacing people. And every unfilled shift is $240 in lost revenue.

Meanwhile, conversion rates drop 8x when follow-up is delayed by just 5 minutes. Most agencies take 2+ days.

Our AI contacts every applicant within seconds of applying, screens them, and books the final interview. No recruiter time wasted on the 90% of applicants who won't get hired. Your team only talks to candidates who are qualified and ready.

Worth 15 minutes to see if the math works for {{company_name}}?

{{calendar_link}}

{{sender_name}}"""

# ─── Email Step 3: Pattern interrupt / last shot (Day 7) ──────────────────────
STEP3_SUBJECT_TEMPLATES = [
    "Not trying to be annoying, {{first_name}}",
    "Last one from me",
    "89% of agencies are turning people away",
]

STEP3_BODY = """{{first_name}},

89% of homecare providers have had to deny care because they can't staff fast enough. That's clients walking out the door because the hiring process can't keep up.

If {{company_name}} is spending more time screening than closing, or losing good candidates to faster-moving agencies, that's exactly what our AI fixes. Application to final interview, fully automated.

If the timing is off, no hard feelings. But if you're curious, 15 minutes and I'll show you how it works.

{{calendar_link}}

{{sender_name}}"""

# ─── Sequence config ──────────────────────────────────────────────────────────
SEQUENCE_STEPS = [
    {"delay": 0, "subjects": STEP1_SUBJECT_TEMPLATES, "body": STEP1_BODY},
    {"delay": 3, "subjects": STEP2_SUBJECT_TEMPLATES, "body": STEP2_BODY},
    {"delay": 7, "subjects": STEP3_SUBJECT_TEMPLATES, "body": STEP3_BODY},
]


def load_config():
    """Load config.json."""
    with open(CONFIG_PATH) as f:
        return json.load(f)


def detect_columns(headers: list) -> dict:
    """Auto-detect column mappings from Apollo or generic CSV headers."""
    mapping = {}
    header_lower = {h.lower().strip(): h for h in headers}

    # Email
    for candidate in ["email", "contact_email", "prospect_email", "email_address",
                       "work email", "personal email"]:
        if candidate in header_lower:
            mapping["email"] = header_lower[candidate]
            break

    # First name
    for candidate in ["first_name", "first name", "firstname", "contact_first_name"]:
        if candidate in header_lower:
            mapping["first_name"] = header_lower[candidate]
            break

    # Last name
    for candidate in ["last_name", "last name", "lastname", "contact_last_name"]:
        if candidate in header_lower:
            mapping["last_name"] = header_lower[candidate]
            break

    # Full name (Apollo uses this)
    for candidate in ["full name", "full_name", "name", "contact_name"]:
        if candidate in header_lower:
            mapping["full_name"] = header_lower[candidate]
            break

    # Company
    for candidate in ["company name", "company", "company_name", "organization",
                       "organization name", "account_name"]:
        if candidate in header_lower:
            mapping["company"] = header_lower[candidate]
            break

    # Title
    for candidate in ["title", "job_title", "job title", "contact_title", "person title"]:
        if candidate in header_lower:
            mapping["title"] = header_lower[candidate]
            break

    # Domain / website
    for candidate in ["website", "domain", "company_domain", "website url",
                       "company website"]:
        if candidate in header_lower:
            mapping["domain"] = header_lower[candidate]
            break

    # Employee count (Apollo uses "# employees")
    for candidate in ["# employees", "employees", "employee_count", "number of employees",
                       "company size", "employee count"]:
        if candidate in header_lower:
            mapping["employees"] = header_lower[candidate]
            break

    # Industry
    for candidate in ["industry", "company_industry", "sub_industry"]:
        if candidate in header_lower:
            mapping["industry"] = header_lower[candidate]
            break

    # City / Location (person city first, then company city)
    for candidate in ["city", "person city", "company city", "location",
                       "headquarters"]:
        if candidate in header_lower:
            mapping["location"] = header_lower[candidate]
            break

    # State (for combined location)
    for candidate in ["state", "person state", "company state"]:
        if candidate in header_lower:
            mapping["state"] = header_lower[candidate]
            break

    # LinkedIn
    for candidate in ["person linkedin url", "linkedin", "linkedin url",
                       "linkedin_url", "contact_linkedin"]:
        if candidate in header_lower:
            mapping["linkedin"] = header_lower[candidate]
            break

    # Seniority (Apollo field)
    for candidate in ["seniority", "person seniority"]:
        if candidate in header_lower:
            mapping["seniority"] = header_lower[candidate]
            break

    # Email quality/status (Apollo fields for filtering)
    for candidate in ["email status", "email_status"]:
        if candidate in header_lower:
            mapping["email_status"] = header_lower[candidate]
            break

    return mapping


def generate_first_line_with_ai(lead: dict, config: dict) -> str:
    """Use Claude to generate a personalized first line for a lead."""
    api_key = config.get("anthropic_api_key", "")
    if not api_key:
        return generate_first_line_fallback(lead)

    company = lead.get("company", "your company")
    title = lead.get("title", "")
    first_name = lead.get("first_name", "")
    industry = lead.get("industry", "staffing")
    employees = lead.get("employees", "")
    location = lead.get("location", "")
    domain = lead.get("domain", "")

    prompt = f"""Generate a personalized cold email opening line (1 sentence, under 25 words) for selling AI recruiting automation to a staffing/homecare company.

Lead info:
- Name: {first_name}
- Company: {company}
- Title: {title}
- Industry: {industry}
- Employees: {employees}
- Location: {location}
- Website: {domain}

Industry context you can weave in naturally:
- Caregiver turnover is 77-79% annually (entire staff replaced every 14 months)
- 43% interview no-show rate in staffing
- Only 9.6% of homecare applicants get hired
- It takes 16+ hours of screening per open position
- 89% of providers have denied care due to staffing shortages
- Conversion drops 8x when follow-up is delayed by 5 minutes

Rules:
- Reference something specific about their company, size, location, or pain point
- Sound like a real person who understands their daily grind, not a marketer
- No generic openers ("I hope this finds you well", "I came across your company")
- No flattery ("I love what you're doing", "Impressive growth")
- Make it feel like you know their business and industry inside out
- Do NOT include a greeting like "Hi [Name]" — just the opening line itself
- End with a period, not a question mark
- Examples of good first lines:
  "Running a 50-person homecare team in Phoenix means your recruiters are probably screening all day instead of placing."
  "With 77% annual turnover, {company} is essentially rehiring its entire team every 14 months."
  "At {company}'s size, the 43% interview no-show rate alone is costing you hundreds of hours a year."

Return ONLY the first line, nothing else."""

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 100,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "").strip()
            if text and len(text) < 200:
                return text
    except Exception as e:
        logging.warning(f"AI first-line generation failed for {company}: {e}")

    return generate_first_line_fallback(lead)


def generate_first_line_fallback(lead: dict) -> str:
    """Generate a decent first line without AI, using lead data."""
    company = lead.get("company", "your company")
    industry = lead.get("industry", "").lower()
    employees = lead.get("employees", "")
    location = lead.get("location", "")
    title = lead.get("title", "").lower()

    templates = []

    if "homecare" in industry or "home care" in industry or "home health" in industry:
        templates.extend([
            f"With 77% annual caregiver turnover, {company} is essentially rehiring its entire team every 14 months.",
            f"89% of homecare providers have had to turn away clients because they can't staff fast enough, and {company} probably isn't the exception.",
            f"Every day {company} has an open caregiver role is $240 in lost revenue per unfilled shift.",
            f"Only 9.6% of homecare applicants get hired, which means {company}'s recruiters are spending 16+ hours screening for every single placement.",
        ])
    elif "staffing" in industry or "recruiting" in industry or "employment" in industry:
        templates.extend([
            f"When {company} has open reqs, conversion drops 8x if follow-up takes more than 5 minutes.",
            f"With a 43% interview no-show rate across staffing, {company}'s recruiters are wasting almost half their scheduled screening time.",
            f"Your recruiters at {company} are probably spending 16+ hours screening per role when only 1 in 10 applicants will get hired.",
        ])

    if employees:
        try:
            count = int(str(employees).replace(",", "").strip())
            if count > 100:
                templates.append(f"At {count} employees with 77% turnover, {company} is burning through $171K+ a year just on replacement costs.")
            elif count > 20:
                templates.append(f"At {company}'s size, the 43% interview no-show rate alone is costing your team hundreds of hours a year.")
        except (ValueError, TypeError):
            pass

    if location:
        templates.append(f"The caregiver shortage in {location} means {company} is competing for the same shrinking talent pool as everyone else.")

    if not templates:
        templates = [
            f"76% of recruiters say they got ghosted by candidates last year, and {company} is probably feeling that number firsthand.",
            f"Most companies like {company} lose their best candidates in the first 2 hours after they apply.",
            f"The gap between when a candidate applies and when {company} calls them back is where placements go to die.",
        ]

    return random.choice(templates)


def process_leads(input_csv: str, config: dict, enrich: bool = False,
                  dry_run: bool = False, limit: int = 0) -> list:
    """Read leads CSV, generate personalized emails for each."""
    with open(input_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        col_map = detect_columns(headers)

        logging.info(f"Detected columns: {json.dumps(col_map, indent=2)}")

        if "email" not in col_map:
            logging.error("No email column found! Cannot proceed.")
            sys.exit(1)

        rows = list(reader)

    if limit:
        rows = rows[:limit]
    logging.info(f"Processing {len(rows)} leads from {input_csv}")

    calendar_link = config.get("calendar_link", "https://calendly.com/realsideai")
    sender_name = config.get("sender_name", "Dylan Mitchell")
    sender_email = config.get("sender_email", "dylan.realside@gmail.com")
    testimonial = config.get("recruiting_testimonial",
                              "We went from spending 6 hours a day screening to only talking to candidates who are ready to start.")

    output_rows = []
    first_line_count = 0

    skipped_email = 0
    skipped_status = 0

    for i, row in enumerate(rows):
        email = row.get(col_map.get("email", ""), "").strip()
        if not email or "@" not in email:
            skipped_email += 1
            continue

        # Skip invalid/risky emails (Apollo email_status filter)
        email_status = row.get(col_map.get("email_status", ""), "").strip().lower()
        if email_status and email_status not in ("verified", "valid", ""):
            skipped_status += 1
            continue

        first_name = row.get(col_map.get("first_name", ""), "").strip()
        last_name = row.get(col_map.get("last_name", ""), "").strip()

        # Fallback: parse full name if first/last are empty
        if not first_name and "full_name" in col_map:
            full = row.get(col_map["full_name"], "").strip()
            if full:
                parts = full.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""

        company = row.get(col_map.get("company", ""), "").strip()
        title = row.get(col_map.get("title", ""), "").strip()
        domain = row.get(col_map.get("domain", ""), "").strip()
        employees = row.get(col_map.get("employees", ""), "").strip()
        industry = row.get(col_map.get("industry", ""), "").strip()
        location = row.get(col_map.get("location", ""), "").strip()
        state = row.get(col_map.get("state", ""), "").strip()
        if state and location:
            location = f"{location}, {state}"
        elif state:
            location = state
        linkedin = row.get(col_map.get("linkedin", ""), "").strip()

        lead = {
            "email": email,
            "first_name": first_name or "there",
            "last_name": last_name,
            "company": company or "your company",
            "title": title,
            "domain": domain,
            "employees": employees,
            "industry": industry,
            "location": location,
            "linkedin": linkedin,
        }

        # Generate personalized first line
        if enrich:
            first_line = generate_first_line_with_ai(lead, config)
            time.sleep(0.3)  # Rate limiting
        else:
            first_line = generate_first_line_fallback(lead)

        first_line_count += 1

        # Pick subject lines for each step
        for step_idx, step in enumerate(SEQUENCE_STEPS):
            subject = random.choice(step["subjects"])
            body = step["body"]

            # Replace variables
            replacements = {
                "{{custom_first_line}}": first_line,
                "{{first_name}}": first_name or "there",
                "{{company_name}}": company or "your company",
                "{{calendar_link}}": calendar_link,
                "{{sender_name}}": sender_name,
                "{{sender_email}}": sender_email,
                "{{testimonial_placeholder}}": testimonial,
            }

            for var, val in replacements.items():
                subject = subject.replace(var, val)
                body = body.replace(var, val)

            output_rows.append({
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "company_name": company,
                "contact_title": title,
                "domain": domain,
                "step_number": step_idx + 1,
                "delay_days": step["delay"],
                "subject": subject,
                "body": body,
                "custom_first_line": first_line,
                "personalization_hook": first_line,
                "sender_email": sender_email,
                "sender_name": sender_name,
            })

        if (i + 1) % 500 == 0:
            logging.info(f"  Processed {i + 1}/{len(rows)} leads...")

    if skipped_email:
        logging.info(f"Skipped {skipped_email} leads with no/invalid email")
    if skipped_status:
        logging.info(f"Skipped {skipped_status} leads with unverified email status")
    logging.info(f"Generated {first_line_count} first lines, {len(output_rows)} total email rows")
    return output_rows


def write_output(rows: list, output_path: str):
    """Write campaign emails to CSV."""
    if not rows:
        logging.warning("No rows to write.")
        return

    fieldnames = list(rows[0].keys())
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    logging.info(f"Wrote {len(rows)} rows to {output_path}")


def main():
    parser = argparse.ArgumentParser(description="AI Recruiting Campaign Generator")
    parser.add_argument("--input", required=True, help="Path to leads CSV (Apollo export)")
    parser.add_argument("--output", default=None, help="Output CSV path (default: output/recruiting_social_proof.csv)")
    parser.add_argument("--enrich", action="store_true", help="Use Claude AI for personalized first lines (uses API credits)")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing output")
    parser.add_argument("--config", default=CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N leads (for testing)")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    config = load_config()
    output_path = args.output or os.path.join(OUTPUT_DIR, "recruiting_social_proof.csv")

    print(f"\nAI Recruiting Campaign Generator — Social Proof Edition")
    print(f"{'='*60}")
    print(f"Input:  {args.input}")
    print(f"Output: {output_path}")
    print(f"Enrich: {'AI (Claude Haiku)' if args.enrich else 'Template-based'}")
    if args.limit:
        print(f"Limit:  First {args.limit} leads only")
    print(f"Mode:   {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    rows = process_leads(args.input, config, enrich=args.enrich, dry_run=args.dry_run,
                         limit=args.limit)

    if args.dry_run:
        print(f"\n[DRY-RUN] Would write {len(rows)} rows to {output_path}")
        # Show first lead's sequence as preview
        if rows:
            print(f"\n--- Preview: First lead's 3-step sequence ---\n")
            lead_email = rows[0]["email"]
            for row in rows:
                if row["email"] == lead_email:
                    print(f"  Step {row['step_number']} (Day {row['delay_days']}):")
                    print(f"  Subject: {row['subject']}")
                    print(f"  First line: {row['custom_first_line']}")
                    print(f"  Body preview: {row['body'][:150]}...")
                    print()
    else:
        write_output(rows, output_path)
        print(f"\nDone! {len(rows)} email rows written to {output_path}")
        print(f"  → {len(rows) // 3} leads × 3 steps = {len(rows)} emails")
        print(f"\nNext steps:")
        print(f"  1. Review the output CSV")
        print(f"  2. Upload to Instantly:")
        print(f"     python recruiting_uploader.py --api-key YOUR_KEY --input {output_path}")
        print(f"  3. Activate the campaign in Instantly dashboard")


if __name__ == "__main__":
    main()
