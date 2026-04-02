#!/usr/bin/env python3
"""
Gmail Outreach — Send personalized cold emails through Gmail SMTP.

Generates Claude-powered personalized emails for prospect lists and sends
them directly through Gmail using an App Password.

Usage:
    python gmail_outreach.py --prospects staffing_leads.json --dry-run
    python gmail_outreach.py --prospects staffing_leads.json --send
    python gmail_outreach.py --prospects staffing_leads.json --send --delay 60

Requirements:
    - Gmail App Password (set GMAIL_APP_PASSWORD env var or in config.json)
    - Anthropic API key (in config.json)
"""

import argparse
import json
import os
import smtplib
import sys
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from anthropic import Anthropic


def load_config(config_path="config.json"):
    with open(config_path) as f:
        return json.load(f)


def load_prospects(prospects_path):
    with open(prospects_path) as f:
        return json.load(f)


def guess_email_patterns(first_name, last_name, domain):
    """Generate likely email patterns for a prospect."""
    first = first_name.lower().strip()
    last = last_name.lower().strip()
    patterns = [
        f"{first}.{last}@{domain}",
        f"{first}{last}@{domain}",
        f"{first[0]}{last}@{domain}",
        f"{first}@{domain}",
        f"{first}_{last}@{domain}",
        f"{first[0]}.{last}@{domain}",
    ]
    return patterns


def generate_email(client, prospect, config):
    """Use Claude to generate a personalized cold email."""
    prompt = f"""Write a short, personalized cold email from {config['sender_name']} at Realside AI to {prospect['name']},
{prospect['title']} at {prospect['company']}.

Company context: {prospect['company']} is a {prospect.get('company_description', 'healthcare staffing company')}
with {prospect.get('employee_count', 'unknown')} employees and {prospect.get('revenue', 'unknown')} revenue.
Located in {prospect.get('location', 'the US')}.

Product context: {config['product_description']}

Rules:
- Subject line: short, curiosity-driven, no spam words, lowercase style
- Under 100 words in the body
- Reference something specific about their company or role
- Spark curiosity about AI handling their inbound calls/candidate outreach
- For staffing companies: angle is AI receptionist handling candidate intake calls 24/7 + AI outbound agent for candidate re-engagement
- End with a soft CTA (quick call, not "book a demo")
- Friendly, confident tone. Not salesy or robotic.
- No dashes (--), no emojis
- Sign off as {config['sender_name']}

Return ONLY valid JSON with keys: "subject", "body"
No markdown, no code blocks, just the JSON object."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=500,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    # Handle potential markdown wrapping
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def send_gmail(sender_email, app_password, to_email, subject, body, sender_name):
    """Send an email through Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject

    # Plain text version
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender_email, app_password)
        server.sendmail(sender_email, to_email, msg.as_string())

    return True


def main():
    parser = argparse.ArgumentParser(description="Gmail cold outreach sender")
    parser.add_argument("--prospects", required=True, help="Path to prospects JSON file")
    parser.add_argument("--config", default="config.json", help="Path to config file")
    parser.add_argument("--send", action="store_true", help="Actually send emails (default: dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Generate emails but don't send")
    parser.add_argument("--delay", type=int, default=45, help="Seconds between emails (default: 45)")
    parser.add_argument("--output", default="output/gmail_outreach_drafts.json", help="Output file for drafts")
    parser.add_argument("--email-pattern", type=int, default=0,
                        help="Which email pattern to use: 0=first.last, 1=firstlast, 2=flast, 3=first, 4=first_last")
    args = parser.parse_args()

    config = load_config(args.config)
    prospects = load_prospects(args.prospects)

    sender_email = config["sender_email"]
    sender_name = config["sender_name"]
    app_password = os.environ.get("GMAIL_APP_PASSWORD", config.get("gmail_app_password", ""))

    if args.send and not app_password:
        print("ERROR: Set GMAIL_APP_PASSWORD env var or gmail_app_password in config.json")
        print("Get one at: Google Account > Security > 2-Step Verification > App Passwords")
        sys.exit(1)

    client = Anthropic(api_key=config["anthropic_api_key"])

    drafts = []

    for i, prospect in enumerate(prospects):
        print(f"\n[{i+1}/{len(prospects)}] Generating email for {prospect['name']} at {prospect['company']}...")

        try:
            email_data = generate_email(client, prospect, config)
        except Exception as e:
            print(f"  ERROR generating email: {e}")
            continue

        # Determine target email
        target_email = prospect.get("email")
        if not target_email:
            name_parts = prospect["name"].replace(",", "").replace("MBA", "").replace("MPA", "").strip().split()
            first_name = name_parts[0]
            last_name = name_parts[-1] if len(name_parts) > 1 else ""
            patterns = guess_email_patterns(first_name, last_name, prospect["domain"])
            target_email = patterns[args.email_pattern] if args.email_pattern < len(patterns) else patterns[0]

        draft = {
            "name": prospect["name"],
            "company": prospect["company"],
            "title": prospect["title"],
            "to_email": target_email,
            "subject": email_data["subject"],
            "body": email_data["body"],
            "linkedin": prospect.get("linkedin", ""),
            "all_email_guesses": guess_email_patterns(
                prospect["name"].split()[0],
                prospect["name"].replace(",","").split()[-1],
                prospect["domain"]
            ) if not prospect.get("email") else [target_email]
        }
        drafts.append(draft)

        print(f"  To: {target_email}")
        print(f"  Subject: {email_data['subject']}")
        print(f"  Body preview: {email_data['body'][:80]}...")

        if args.send:
            try:
                send_gmail(sender_email, app_password, target_email,
                          email_data["subject"], email_data["body"], sender_name)
                print(f"  SENT successfully!")
                draft["status"] = "sent"
                draft["sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
            except Exception as e:
                print(f"  SEND FAILED: {e}")
                draft["status"] = "failed"
                draft["error"] = str(e)

            if i < len(prospects) - 1:
                print(f"  Waiting {args.delay}s before next email...")
                time.sleep(args.delay)
        else:
            draft["status"] = "draft"

    # Save drafts
    os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else "output", exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(drafts, f, indent=2)

    print(f"\n{'='*50}")
    print(f"Generated {len(drafts)} emails")
    print(f"Saved to {args.output}")
    if not args.send:
        print(f"\nDRY RUN — to actually send, run with --send flag")
        print(f"Make sure GMAIL_APP_PASSWORD is set first")


if __name__ == "__main__":
    main()
