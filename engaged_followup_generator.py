#!/usr/bin/env python3
"""
Engaged Prospect Follow-Up Sequence Writer

Takes a CSV of prospects who replied positively but haven't booked yet, and uses
Claude to generate an 8-touch warm follow-up sequence. Each follow-up uses a
different angle (value add, case study, video, social proof, pain point, direct
ask, alternative offer, breakup). Outputs calendar-ready send dates with
multi-channel touchpoint suggestions.

This is DIFFERENT from followup_generator.py (which handles cold follow-ups for
people who never replied). This handles WARM follow-ups for engaged prospects.

Usage:
    python engaged_followup_generator.py --input engaged_prospects.csv --output engaged_followups.csv
    python engaged_followup_generator.py --input engaged_prospects.csv --config config.json

Input CSV columns:
    company_name, domain, contact_name, contact_email, contact_title,
    original_message, prospect_reply, engagement_date

Output CSV columns:
    company_name, domain, contact_name, contact_email, contact_title,
    followup_number, subject, body, scheduled_send_date, sender_email,
    sender_name, channel
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
DEFAULT_SENDER_NAME = "Dylan Mitchell"
DEFAULT_CONFIG_PATH = "config.json"
RATE_LIMIT_DELAY = 1  # seconds between API calls

# Channel mapping for each follow-up touch
CHANNEL_MAP = {
    1: "email",
    2: "email + call",
    3: "email + whatsapp",
    4: "email + linkedin",
    5: "email + call",
    6: "email + text",
    7: "email",
    8: "email",
}


def load_config(config_path: str) -> dict:
    """Load configuration from JSON file."""
    if not os.path.exists(config_path):
        print(f"Warning: Config file '{config_path}' not found, using defaults")
        return {}
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def load_case_studies(case_studies_path: str) -> str:
    """Load all case studies from a directory into a single string for prompt context."""
    if not os.path.isdir(case_studies_path):
        print(f"Warning: Case studies directory '{case_studies_path}' not found")
        return ""
    studies = []
    for filename in sorted(os.listdir(case_studies_path)):
        filepath = os.path.join(case_studies_path, filename)
        if os.path.isfile(filepath):
            with open(filepath, encoding="utf-8") as f:
                studies.append(f.read().strip())
    return "\n\n---\n\n".join(studies)


def read_input_csv(filepath: str) -> list[dict]:
    """Read engaged prospects from CSV."""
    required_columns = {
        "company_name", "domain", "contact_name", "contact_email",
        "contact_title", "original_message", "prospect_reply", "engagement_date",
    }
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


def parse_engagement_date(date_str: str) -> datetime:
    """Parse an engagement_date string, trying common formats."""
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


def compute_send_dates(engagement_date: datetime, num_followups: int) -> list[str]:
    """Compute scheduled send dates, one per business day starting the day after engagement."""
    dates = []
    current = engagement_date + timedelta(days=1)
    while len(dates) < num_followups:
        if current.weekday() < 5:  # Monday-Friday
            dates.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)
    return dates


def generate_engaged_followup_sequence(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str,
    contact_email: str,
    contact_title: str,
    original_message: str,
    prospect_reply: str,
    sender_name: str,
    sender_email: str,
    calendar_link: str,
    product_description: str,
    case_studies_text: str,
) -> list[dict]:
    """Use Claude to generate an 8-touch warm follow-up sequence for an engaged prospect."""

    prompt = f"""You are a world-class B2B sales copywriter specializing in warm follow-up sequences. Generate an 8-email follow-up sequence for a prospect who REPLIED POSITIVELY to our outreach but hasn't booked a meeting yet. These are warm leads who showed interest.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Contact: {contact_name}
- Email: {contact_email}
- Title: {contact_title}

ORIGINAL OUTREACH MESSAGE:
{original_message}

PROSPECT'S POSITIVE REPLY:
{prospect_reply}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Calendar link: {calendar_link}

PRODUCT DESCRIPTION:
{product_description}

CASE STUDIES FOR SOCIAL PROOF:
{case_studies_text}

FOLLOW-UP SEQUENCE (8 touches, each with a different angle):

1. Quick value add — reference their reply, share a quick stat or insight relevant to their business
2. Case study — share a relevant success story from the case studies above
3. Video/Loom approach — "recorded a quick video for you" showing how it would work for their business
4. Social proof — mention similar companies in their industry that are benefiting
5. Pain point amplifier — highlight the cost of inaction (missed calls, lost revenue, slow follow-up)
6. Direct ask — straightforward "are you still interested in exploring this?"
7. Alternative offer — "even if timing isn't right, here's a free resource" (audit, guide, etc.)
8. Breakup email — "no hard feelings, door is always open"

RULES:
1. Generate exactly 8 follow-up emails
2. Each email MUST be under 120 words
3. Tone: friendly, confident, conversational. Not pushy or salesy
4. NEVER use '--' (double dashes) anywhere in the messaging
5. Each email should work as a standalone message
6. ALWAYS include the calendar link ({calendar_link}) in every email
7. Reference their original reply where relevant to show you remember the conversation
8. NEVER use phrases like "bumping this", "circling back", "just following up", "checking in"
9. Sign off with the sender's name (just first name is fine)
10. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
11. Each email needs a unique, compelling subject line (not "Re:" prefixed)

Return your response as a JSON array of objects, each with these exact keys:
- "followup_number": integer (1 through 8)
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
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
        # Fallback: return generic follow-ups
        result = [
            {
                "followup_number": i,
                "subject": f"Quick thought for {company_name}",
                "body": f"Hi {contact_name},\n\nThanks for your reply! I wanted to share something relevant to {company_name}.\n\nWould love to show you how this works. Grab a time here: {calendar_link}\n\nBest,\n{sender_name}",
            }
            for i in range(1, 9)
        ]

    return result


def write_output_csv(filepath: str, results: list[dict]):
    """Write follow-up sequences to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_email", "contact_title",
        "followup_number", "subject", "body", "scheduled_send_date",
        "sender_email", "sender_name", "channel",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} follow-up emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Engaged Prospect Follow-Up Sequence Writer"
    )
    parser.add_argument(
        "--input", required=True,
        help="Input CSV with engaged prospects",
    )
    parser.add_argument(
        "--output", default="engaged_followups.csv",
        help="Output CSV path (default: engaged_followups.csv)",
    )
    parser.add_argument(
        "--config", default=DEFAULT_CONFIG_PATH,
        help=f"Config JSON path (default: {DEFAULT_CONFIG_PATH})",
    )
    args = parser.parse_args()

    # Load config
    config = load_config(args.config)

    sender_email = config.get("sender_email", DEFAULT_SENDER_EMAIL)
    sender_name = config.get("sender_name", DEFAULT_SENDER_NAME)
    calendar_link = config.get("calendar_link", "")
    product_description = config.get("product_description", "")
    case_studies_path = config.get("case_studies_path", "case_studies")

    # Load case studies
    case_studies_text = load_case_studies(case_studies_path)

    # Resolve API key: config first, then env var
    api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: Anthropic API key not found in config.json or ANTHROPIC_API_KEY environment variable")
        print("Set it in config.json as 'anthropic_api_key' or with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Read engaged prospects
    prospects = read_input_csv(args.input)
    print(f"Loaded {len(prospects)} engaged prospects from {args.input}")

    results = []
    for i, prospect in enumerate(prospects, 1):
        company_name = prospect["company_name"].strip()
        domain = prospect["domain"].strip()
        contact_name = prospect["contact_name"].strip()
        contact_email = prospect["contact_email"].strip()
        contact_title = prospect["contact_title"].strip()
        original_message = prospect["original_message"].strip()
        prospect_reply = prospect["prospect_reply"].strip()
        engagement_date = parse_engagement_date(prospect["engagement_date"])

        print(f"\n[{i}/{len(prospects)}] Generating warm follow-up sequence for {contact_name} at {company_name}...")

        # Generate follow-up sequence
        followups = generate_engaged_followup_sequence(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_title=contact_title,
            original_message=original_message,
            prospect_reply=prospect_reply,
            sender_name=sender_name,
            sender_email=sender_email,
            calendar_link=calendar_link,
            product_description=product_description,
            case_studies_text=case_studies_text,
        )

        # Compute send dates (one per business day)
        send_dates = compute_send_dates(engagement_date, len(followups))

        for j, followup in enumerate(followups):
            followup_num = followup.get("followup_number", j + 1)
            scheduled_date = send_dates[j] if j < len(send_dates) else send_dates[-1]
            channel = CHANNEL_MAP.get(followup_num, "email")

            results.append({
                "company_name": company_name,
                "domain": domain,
                "contact_name": contact_name,
                "contact_email": contact_email,
                "contact_title": contact_title,
                "followup_number": followup_num,
                "subject": followup.get("subject", ""),
                "body": followup.get("body", ""),
                "scheduled_send_date": scheduled_date,
                "sender_email": sender_email,
                "sender_name": sender_name,
                "channel": channel,
            })

            print(f"  Follow-up {followup_num} | {scheduled_date} | {channel} | Subject: {followup.get('subject', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the follow-up sequences before scheduling sends.")


if __name__ == "__main__":
    main()
