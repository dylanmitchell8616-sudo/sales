#!/usr/bin/env python3
"""
Automated Follow-Up Sequence Writer

Takes an existing outreach CSV (who you emailed, when, what you said) and uses
Claude to generate a 3-5 touch follow-up sequence for each prospect. Each
follow-up adds new value (case study, relevant insight, social proof) rather
than generic "bumping this" messages. Outputs calendar-ready send dates.

Usage:
    python followup_generator.py --input outreach.csv --output followup_sequences.csv
    python followup_generator.py --input outreach.csv --days-between 5
    python followup_generator.py --input outreach.csv --sender-email you@company.com --sender-name "Your Name"

Input CSV columns:
    company_name, domain, contact_name, contact_title, subject, body, sent_date

Output CSV columns:
    company_name, domain, contact_name, contact_title, followup_number, subject,
    body, scheduled_send_date, sender_email, sender_name
"""

import argparse
import csv
import json
import os
import re
import sys
from datetime import datetime, timedelta

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

# Default config
DEFAULT_SENDER_EMAIL = "dylan.realside@gmail.com"
DEFAULT_SENDER_NAME = "Sales Team"
DEFAULT_DAYS_BETWEEN = 3
RATE_LIMIT_DELAY = 1  # seconds between API calls


def read_input_csv(filepath: str) -> list[dict]:
    """Read outreach history from CSV. Expected columns: company_name, domain, contact_name, contact_title, subject, body, sent_date."""
    required_columns = {"company_name", "domain", "contact_name", "contact_title", "subject", "body", "sent_date"}
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            print("Error: CSV file is empty or has no header row")
            sys.exit(1)
        missing = required_columns - set(reader.fieldnames)
        if missing:
            print(f"Error: CSV is missing required columns: {', '.join(sorted(missing))}")
            sys.exit(1)
        for row in reader:
            rows.append(row)
    return rows


def parse_sent_date(date_str: str) -> datetime:
    """Parse a sent_date string, trying common formats."""
    date_str = date_str.strip()
    formats = [
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%B %d, %Y",
        "%b %d, %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    print(f"Warning: Could not parse date '{date_str}', using today's date")
    return datetime.now()


def generate_followup_sequence(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str,
    contact_title: str,
    original_subject: str,
    original_body: str,
    sender_name: str,
    sender_email: str,
) -> list[dict]:
    """Use Claude to generate a 3-5 touch follow-up sequence for a prospect."""

    prompt = f"""You are a world-class B2B sales copywriter specializing in follow-up sequences. Generate a follow-up email sequence for a prospect who received an initial outreach email but hasn't replied.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Contact: {contact_name}
- Title: {contact_title}

ORIGINAL EMAIL THAT WAS SENT:
Subject: {original_subject}
Body:
{original_body}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}

RULES:
1. Generate exactly 4 follow-up emails (a 4-touch sequence after the original)
2. Each email MUST add NEW value — a different angle, insight, case study, or social proof
3. NEVER use phrases like "just bumping this", "circling back", "following up on my last email", or "wanted to check in"
4. Each email should be under 120 words
5. Each email should have a unique, compelling subject line (not "Re: " prefixed)
6. Progression of the sequence:
   - Follow-up 1: Share a relevant case study or customer result
   - Follow-up 2: Offer a specific insight or data point relevant to their industry
   - Follow-up 3: Social proof — mention a similar company or competitor trend
   - Follow-up 4: Breakup email — low-pressure, give them an easy out while leaving the door open
7. Tone: professional but conversational, not salesy
8. Each email should work as a standalone message (don't assume they read previous emails)
9. Sign off with the sender's name
10. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
11. Never include a calendly or scheduling link. Instead ask what days work for a call.

Return your response as a JSON array of objects, each with these exact keys:
- "followup_number": integer (1 through 4)
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        # Try to find raw JSON array
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        result = json.loads(text)
        if not isinstance(result, list):
            raise ValueError("Expected a JSON array")
    except (json.JSONDecodeError, ValueError):
        # Fallback: return a single generic follow-up
        result = [
            {
                "followup_number": i,
                "subject": f"Quick thought for {company_name}",
                "body": f"Hi {contact_name},\n\nI wanted to share something relevant to {company_name}.\n\nWould a brief call this week make sense?\n\nBest,\n{sender_name}",
            }
            for i in range(1, 5)
        ]

    return result


def compute_send_dates(sent_date: datetime, num_followups: int, days_between: int) -> list[str]:
    """Compute scheduled send dates for each follow-up, spaced days_between apart from the original sent_date."""
    dates = []
    for i in range(1, num_followups + 1):
        send_date = sent_date + timedelta(days=days_between * i)
        # Skip weekends: push Saturday to Monday, Sunday to Monday
        if send_date.weekday() == 5:  # Saturday
            send_date += timedelta(days=2)
        elif send_date.weekday() == 6:  # Sunday
            send_date += timedelta(days=1)
        dates.append(send_date.strftime("%Y-%m-%d"))
    return dates


def write_output_csv(filepath: str, results: list[dict]):
    """Write follow-up sequences to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_title",
        "followup_number", "subject", "body", "scheduled_send_date",
        "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} follow-up emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Automated Follow-Up Sequence Writer")
    parser.add_argument("--input", required=True, help="Input CSV with outreach history")
    parser.add_argument("--output", default="followup_sequences.csv", help="Output CSV path (default: followup_sequences.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL, help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME, help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--days-between", type=int, default=DEFAULT_DAYS_BETWEEN, help=f"Days between follow-ups (default: {DEFAULT_DAYS_BETWEEN})")
    args = parser.parse_args()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Read outreach history
    prospects = read_input_csv(args.input)
    print(f"Loaded {len(prospects)} prospects from {args.input}")

    results = []
    for i, prospect in enumerate(prospects, 1):
        company_name = prospect["company_name"].strip()
        domain = prospect["domain"].strip()
        contact_name = prospect["contact_name"].strip()
        contact_title = prospect["contact_title"].strip()
        original_subject = prospect["subject"].strip()
        original_body = prospect["body"].strip()
        sent_date = parse_sent_date(prospect["sent_date"])

        print(f"\n[{i}/{len(prospects)}] Generating follow-up sequence for {contact_name} at {company_name}...")

        # Generate follow-up sequence
        followups = generate_followup_sequence(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_title=contact_title,
            original_subject=original_subject,
            original_body=original_body,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
        )

        # Compute send dates
        send_dates = compute_send_dates(sent_date, len(followups), args.days_between)

        for j, followup in enumerate(followups):
            followup_num = followup.get("followup_number", j + 1)
            scheduled_date = send_dates[j] if j < len(send_dates) else send_dates[-1]

            results.append({
                "company_name": company_name,
                "domain": domain,
                "contact_name": contact_name,
                "contact_title": contact_title,
                "followup_number": followup_num,
                "subject": followup.get("subject", ""),
                "body": followup.get("body", ""),
                "scheduled_send_date": scheduled_date,
                "sender_email": args.sender_email,
                "sender_name": args.sender_name,
            })

            print(f"  Follow-up {followup_num} | {scheduled_date} | Subject: {followup.get('subject', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the follow-up sequences before scheduling sends.")


if __name__ == "__main__":
    main()
