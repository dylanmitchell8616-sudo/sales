#!/usr/bin/env python3
"""
AI Recruiting Campaign Generator — Hyper-Personalized Edition
================================================================
Uses Claude to write the ENTIRE 3-email sequence per lead, fully custom
to their name, company, industry, size, location, and role.

Processes leads in parallel batches using Claude Haiku for speed + cost efficiency.

Usage:
    python recruiting_hyper_personalized.py --input output/recruiting_leads_apollo.csv
    python recruiting_hyper_personalized.py --input output/recruiting_leads_apollo.csv --dry-run --limit 5
    python recruiting_hyper_personalized.py --input output/recruiting_leads_apollo.csv --workers 10
    python recruiting_hyper_personalized.py --input output/recruiting_leads_apollo.csv --batch-start 0 --batch-end 500
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
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

SYSTEM_PROMPT = """You are a world-class cold email copywriter for Realside AI, which sells AI recruiting automation to staffing agencies, homecare companies, and healthcare organizations.

Your job: write a 3-email sequence that is HYPER-PERSONALIZED to each lead. Every email must feel like it was written by a human who deeply researched this specific person and company.

RULES:
- ALWAYS use the person's first name in every email (greeting + at least once in the body)
- Under 80 words per email body (excluding signature)
- No generic filler ("I hope this finds you well", "I came across your company")
- No flattery ("love what you're doing", "impressive growth")
- Reference specific details: their industry, employee count, location, title, company growth, revenue context
- Tone: direct, peer-to-peer, conversational. Like a text from a smart friend who happens to know their industry
- Each email should have a DIFFERENT angle — don't repeat the same pitch
- End each email with a soft CTA pointing to the calendar link
- Never use '--' in messaging
- Use line breaks for readability (short paragraphs, 1-2 sentences each)
- Do NOT include "Subject:" prefix in subject lines

PRODUCT (weave in naturally, don't dump features):
- AI that handles recruiting from application to final interview automatically
- Screens candidates, asks qualifying questions, checks availability, books interviews
- Contacts applicants within seconds of applying (vs industry avg of 2+ days)
- Recruiters only talk to pre-qualified, ready-to-start candidates
- Calendar link: {calendar_link}
- Sender: {sender_name}

INDUSTRY STATS (use sparingly, pick the most relevant per lead):
- 77% annual caregiver turnover (entire staff replaced every 14 months)
- 43% interview no-show rate in staffing
- Only 9.6% of homecare applicants get hired
- 16+ hours of screening per open position
- 89% of providers denied care due to staffing shortages
- Conversion drops 8x when follow-up delayed by 5 minutes
- $2,600-$5,000 cost per hire, 25-45 days to fill
- $240/day lost revenue per unfilled shift

OUTPUT FORMAT (strict JSON):
{{
  "step1_subject": "short punchy subject under 50 chars",
  "step1_body": "the full email body",
  "step2_subject": "different angle subject",
  "step2_body": "follow-up email body",
  "step3_subject": "final touch subject",
  "step3_body": "breakup email body"
}}"""

USER_PROMPT_TEMPLATE = """Write a hyper-personalized 3-email cold sequence for this lead:

PERSON:
- Name: {first_name} {last_name}
- Title: {title}
- LinkedIn Headline: {headline}
- Seniority: {seniority}
- Location: {city}, {state}, {country}
- LinkedIn: {linkedin}

COMPANY:
- Company: {company}
- Industry: {industry}
- Keywords: {keywords}
- Employees: {employees}
- HQ: {company_city}, {company_state}
- Website: {domain}
- Founded: {founded}
- Annual Revenue: {revenue}
- Headcount Growth (6mo): {growth_6m}
- Headcount Growth (12mo): {growth_12m}
- Company LinkedIn: {company_linkedin}

Use ALL of this context to make each email feel like you spent 10 minutes researching this person. Reference their specific headline, industry keywords, location, company age, growth trajectory, or revenue where natural. The more specific and relevant the detail, the better.

Sign off as:
{sender_name}

Calendar link to include: {calendar_link}

Return ONLY the JSON object, no other text."""


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def detect_columns(headers):
    """Map Apollo CSV headers to our field names."""
    header_lower = {h.lower().strip(): h for h in headers}
    mapping = {}

    field_candidates = {
        "email": ["email", "contact_email", "work email"],
        "first_name": ["first name", "first_name", "firstname"],
        "last_name": ["last name", "last_name", "lastname"],
        "full_name": ["full name", "full_name", "name"],
        "company": ["company name", "company", "company_name", "organization"],
        "title": ["title", "job_title", "job title", "person title"],
        "domain": ["website", "domain", "company_domain"],
        "employees": ["# employees", "employees", "employee_count", "number of employees"],
        "industry": ["industry", "company_industry"],
        "city": ["city", "person city"],
        "state": ["state", "person state"],
        "company_city": ["company city"],
        "company_state": ["company state"],
        "linkedin": ["person linkedin url", "linkedin", "linkedin url"],
        "seniority": ["seniority", "person seniority"],
        "email_status": ["email status", "email_status"],
        "headline": ["headline", "person headline"],
        "founded": ["company founded year", "founded year", "founded"],
        "revenue": ["annual revenue", "revenue"],
        "growth_6m": ["company headcount six month growth"],
        "growth_12m": ["company headcount twelve month growth"],
        "keywords": ["keywords", "company keywords"],
        "languages": ["languages"],
        "company_linkedin": ["company linkedin url"],
        "facebook": ["facebook url"],
        "twitter": ["twitter url"],
        "company_phone": ["company phone"],
        "country": ["country"],
    }

    for field, candidates in field_candidates.items():
        for c in candidates:
            if c in header_lower:
                mapping[field] = header_lower[c]
                break

    return mapping


def format_revenue(rev_str):
    """Format revenue number to human readable."""
    if not rev_str:
        return ""
    try:
        rev = float(str(rev_str).replace(",", "").replace("$", ""))
        if rev >= 1_000_000_000:
            return f"${rev/1_000_000_000:.1f}B"
        if rev >= 1_000_000:
            return f"${rev/1_000_000:.0f}M"
        if rev >= 1_000:
            return f"${rev/1_000:.0f}K"
        return f"${rev:.0f}"
    except (ValueError, TypeError):
        return rev_str


def format_growth(growth_str):
    """Format growth percentage."""
    if not growth_str:
        return ""
    try:
        g = float(growth_str)
        sign = "+" if g > 0 else ""
        return f"{sign}{g*100:.1f}%"
    except (ValueError, TypeError):
        return growth_str


def generate_emails_for_lead(lead, config, retries=2):
    """Call Claude to generate a full 3-email sequence for one lead."""
    api_key = config.get("anthropic_api_key", "")
    calendar_link = config.get("calendar_link", "https://calendly.com/realsideai")
    sender_name = config.get("sender_name", "Dylan Mitchell")

    system = SYSTEM_PROMPT.format(
        calendar_link=calendar_link,
        sender_name=sender_name,
    )

    user_msg = USER_PROMPT_TEMPLATE.format(
        first_name=lead.get("first_name", "there"),
        last_name=lead.get("last_name", ""),
        title=lead.get("title", ""),
        company=lead.get("company", ""),
        industry=lead.get("industry", ""),
        employees=lead.get("employees", ""),
        city=lead.get("city", ""),
        state=lead.get("state", ""),
        country=lead.get("country", ""),
        company_city=lead.get("company_city", ""),
        company_state=lead.get("company_state", ""),
        domain=lead.get("domain", ""),
        founded=lead.get("founded", ""),
        revenue=format_revenue(lead.get("revenue", "")),
        growth_6m=format_growth(lead.get("growth_6m", "")),
        growth_12m=format_growth(lead.get("growth_12m", "")),
        headline=lead.get("headline", ""),
        seniority=lead.get("seniority", ""),
        keywords=lead.get("keywords", ""),
        linkedin=lead.get("linkedin", ""),
        company_linkedin=lead.get("company_linkedin", ""),
        sender_name=sender_name,
        calendar_link=calendar_link,
    )

    for attempt in range(retries + 1):
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
                    "max_tokens": 1200,
                    "system": system,
                    "messages": [{"role": "user", "content": user_msg}],
                },
                timeout=30,
            )

            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                logging.warning(f"Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                logging.warning(f"API error {resp.status_code} for {lead.get('email')}: {resp.text[:100]}")
                if attempt < retries:
                    time.sleep(2)
                    continue
                return None

            data = resp.json()
            text = data.get("content", [{}])[0].get("text", "").strip()

            # Parse JSON from response (handle markdown code blocks)
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()

            result = json.loads(text)

            # Validate required fields
            required = ["step1_subject", "step1_body", "step2_subject", "step2_body",
                        "step3_subject", "step3_body"]
            if all(k in result for k in required):
                return result
            else:
                logging.warning(f"Missing fields for {lead.get('email')}: {[k for k in required if k not in result]}")
                if attempt < retries:
                    continue
                return None

        except json.JSONDecodeError as e:
            logging.warning(f"JSON parse error for {lead.get('email')}: {e}")
            if attempt < retries:
                time.sleep(1)
                continue
            return None
        except Exception as e:
            logging.warning(f"Error generating for {lead.get('email')}: {e}")
            if attempt < retries:
                time.sleep(2)
                continue
            return None

    return None


def process_lead(lead, config, sender_name, sender_email, calendar_link):
    """Process a single lead: generate emails and return output rows."""
    result = generate_emails_for_lead(lead, config)

    if not result:
        # Fallback: use a simple template
        return generate_fallback_emails(lead, sender_name, sender_email, calendar_link)

    rows = []
    for step_num in [1, 2, 3]:
        delay = {1: 0, 2: 3, 3: 7}[step_num]
        rows.append({
            "email": lead["email"],
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company", ""),
            "contact_title": lead.get("title", ""),
            "domain": lead.get("domain", ""),
            "step_number": step_num,
            "delay_days": delay,
            "subject": result[f"step{step_num}_subject"],
            "body": result[f"step{step_num}_body"],
            "custom_first_line": "",
            "personalization_hook": lead.get("industry", ""),
            "sender_email": sender_email,
            "sender_name": sender_name,
        })

    return rows


def generate_fallback_emails(lead, sender_name, sender_email, calendar_link):
    """Simple fallback if AI generation fails."""
    first = lead.get("first_name", "there")
    company = lead.get("company", "your company")
    employees = lead.get("employees", "")
    industry = lead.get("industry", "staffing")

    emp_note = f" with {employees} employees" if employees else ""

    rows = []
    steps = [
        {
            "num": 1, "delay": 0,
            "subject": f"{first}, quick question about {company}'s hiring process",
            "body": f"{first},\n\nRunning {company}{emp_note} in {industry} means your team is probably spending more time screening than actually placing.\n\n43% of interviews in staffing are no-shows. By the time most recruiters call back, the best candidates have moved on.\n\nWe built an AI that screens applicants the moment they apply, qualifies them, and books the interview. Your team only talks to ready-to-start candidates.\n\nWorth a 15-minute look?\n\n{calendar_link}\n\n{sender_name}",
        },
        {
            "num": 2, "delay": 3,
            "subject": f"The math behind {company}'s open roles",
            "body": f"Hey {first},\n\nQuick follow-up with one number: every day a role sits open costs ~$240 in lost revenue per shift.\n\nWith 77% annual turnover in this industry, that adds up fast. Our AI cuts time-to-fill by contacting applicants within seconds instead of days.\n\nHappy to walk through how it'd work for {company} specifically.\n\n{calendar_link}\n\n{sender_name}",
        },
        {
            "num": 3, "delay": 7,
            "subject": f"Last note, {first}",
            "body": f"{first},\n\nTotally get it if the timing is off. Just didn't want {company} to keep burning recruiter hours on the 90% of applicants who won't get hired.\n\nIf you're ever curious, the offer stands: 15 minutes and I'll show you exactly how it works.\n\n{calendar_link}\n\n{sender_name}",
        },
    ]

    for step in steps:
        rows.append({
            "email": lead["email"],
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": company,
            "contact_title": lead.get("title", ""),
            "domain": lead.get("domain", ""),
            "step_number": step["num"],
            "delay_days": step["delay"],
            "subject": step["subject"],
            "body": step["body"],
            "custom_first_line": "",
            "personalization_hook": lead.get("industry", ""),
            "sender_email": sender_email,
            "sender_name": sender_name,
        })

    return rows


def read_leads(input_csv, limit=0, batch_start=0, batch_end=0):
    """Read and parse leads from Apollo CSV."""
    with open(input_csv, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []
        col_map = detect_columns(headers)
        logging.info(f"Detected columns: {list(col_map.keys())}")

        if "email" not in col_map:
            logging.error("No email column found!")
            sys.exit(1)

        rows = list(reader)

    # Apply batch range
    if batch_end > 0:
        rows = rows[batch_start:batch_end]
    elif batch_start > 0:
        rows = rows[batch_start:]

    if limit:
        rows = rows[:limit]

    leads = []
    skipped = 0

    for row in rows:
        email = row.get(col_map.get("email", ""), "").strip()
        if not email or "@" not in email:
            skipped += 1
            continue

        first_name = row.get(col_map.get("first_name", ""), "").strip()
        last_name = row.get(col_map.get("last_name", ""), "").strip()

        if not first_name and "full_name" in col_map:
            full = row.get(col_map["full_name"], "").strip()
            if full:
                parts = full.split(" ", 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ""

        city = row.get(col_map.get("city", ""), "").strip()
        state = row.get(col_map.get("state", ""), "").strip()

        leads.append({
            "email": email,
            "first_name": first_name or "there",
            "last_name": last_name,
            "company": row.get(col_map.get("company", ""), "").strip() or "your company",
            "title": row.get(col_map.get("title", ""), "").strip(),
            "domain": row.get(col_map.get("domain", ""), "").strip(),
            "employees": row.get(col_map.get("employees", ""), "").strip(),
            "industry": row.get(col_map.get("industry", ""), "").strip(),
            "city": city,
            "state": state,
            "company_city": row.get(col_map.get("company_city", ""), "").strip(),
            "company_state": row.get(col_map.get("company_state", ""), "").strip(),
            "linkedin": row.get(col_map.get("linkedin", ""), "").strip(),
            "seniority": row.get(col_map.get("seniority", ""), "").strip(),
            "headline": row.get(col_map.get("headline", ""), "").strip(),
            "founded": row.get(col_map.get("founded", ""), "").strip(),
            "revenue": row.get(col_map.get("revenue", ""), "").strip(),
            "growth_6m": row.get(col_map.get("growth_6m", ""), "").strip(),
            "growth_12m": row.get(col_map.get("growth_12m", ""), "").strip(),
            "keywords": row.get(col_map.get("keywords", ""), "").strip(),
            "company_linkedin": row.get(col_map.get("company_linkedin", ""), "").strip(),
            "country": row.get(col_map.get("country", ""), "").strip(),
        })

    if skipped:
        logging.info(f"Skipped {skipped} leads with no/invalid email")
    logging.info(f"Loaded {len(leads)} leads")
    return leads


def main():
    parser = argparse.ArgumentParser(description="AI Recruiting — Hyper-Personalized Generator")
    parser.add_argument("--input", required=True, help="Path to Apollo leads CSV")
    parser.add_argument("--output", default=None, help="Output CSV path")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--limit", type=int, default=0, help="Process only first N leads")
    parser.add_argument("--workers", type=int, default=8, help="Parallel workers (default: 8)")
    parser.add_argument("--batch-start", type=int, default=0, help="Start index for batch processing")
    parser.add_argument("--batch-end", type=int, default=0, help="End index for batch processing")
    parser.add_argument("--append", action="store_true", help="Append to existing output file")

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)

    config = load_config()
    output_path = args.output or os.path.join(OUTPUT_DIR, "recruiting_social_proof.csv")
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    calendar_link = config.get("calendar_link", "https://calendly.com/realsideai")
    sender_name = config.get("sender_name", "Dylan Mitchell")
    sender_email = config.get("sender_email", "dylan.realside@gmail.com")

    print(f"\nAI Recruiting — Hyper-Personalized Generator")
    print(f"{'='*60}")
    print(f"Input:   {args.input}")
    print(f"Output:  {output_path}")
    print(f"Workers: {args.workers}")
    if args.batch_start or args.batch_end:
        print(f"Batch:   [{args.batch_start}:{args.batch_end}]")
    if args.limit:
        print(f"Limit:   {args.limit}")
    print(f"Mode:    {'DRY-RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    leads = read_leads(args.input, limit=args.limit,
                       batch_start=args.batch_start, batch_end=args.batch_end)

    if not leads:
        print("No leads to process.")
        return

    print(f"Generating hyper-personalized emails for {len(leads)} leads...\n")

    all_rows = []
    success = 0
    failed = 0
    start_time = time.time()

    def worker(lead):
        return process_lead(lead, config, sender_name, sender_email, calendar_link)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(worker, lead): lead for lead in leads}

        for i, future in enumerate(as_completed(futures)):
            lead = futures[future]
            try:
                rows = future.result()
                if rows:
                    all_rows.extend(rows)
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logging.error(f"Worker error for {lead.get('email')}: {e}")
                failed += 1

            total = success + failed
            if total % 50 == 0:
                elapsed = time.time() - start_time
                rate = total / elapsed if elapsed > 0 else 0
                eta = (len(leads) - total) / rate if rate > 0 else 0
                print(f"  Progress: {total}/{len(leads)} ({success} ok, {failed} failed) "
                      f"| {rate:.1f} leads/sec | ETA: {eta:.0f}s")

    elapsed = time.time() - start_time
    print(f"\nDone in {elapsed:.0f}s — {success} succeeded, {failed} failed")

    # Sort by email + step number for clean output
    all_rows.sort(key=lambda r: (r["email"], r["step_number"]))

    if args.dry_run:
        print(f"\n[DRY-RUN] Would write {len(all_rows)} rows ({success} leads x 3 steps)")
        # Show preview
        if all_rows:
            seen_emails = set()
            preview_count = 0
            for row in all_rows:
                if row["email"] not in seen_emails and preview_count < 2:
                    seen_emails.add(row["email"])
                    preview_count += 1
                    print(f"\n{'='*50}")
                    print(f"Lead: {row['first_name']} {row['last_name']} @ {row['company_name']}")
                    print(f"{'='*50}")
                if row["email"] in seen_emails and len(seen_emails) <= 2:
                    print(f"\n  Step {row['step_number']} (Day {row['delay_days']}):")
                    print(f"  Subject: {row['subject']}")
                    print(f"  Body:\n{row['body']}")
        return

    # Write output
    if not all_rows:
        print("No rows generated. Check API key and errors above.")
        return

    fieldnames = list(all_rows[0].keys())
    mode = "a" if args.append else "w"
    write_header = not args.append or not os.path.exists(output_path) or os.path.getsize(output_path) == 0

    with open(output_path, mode, newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        writer.writerows(all_rows)

    print(f"\nWrote {len(all_rows)} rows to {output_path}")
    print(f"  {success} leads x 3 steps = {len(all_rows)} emails")
    print(f"\nNext: upload with recruiting_uploader.py")


if __name__ == "__main__":
    main()
