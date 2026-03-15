#!/usr/bin/env python3
"""Cold email sender using Gmail SMTP.

Usage:
    python send_emails.py --template templates/cold_outreach.txt --contacts contacts.csv
    python send_emails.py --template templates/follow_up.txt --contacts contacts.csv --dry-run
"""

import argparse
import csv
import json
import smtplib
import sys
import time
from email.mime.text import MIMEText
from pathlib import Path
from string import Template


CONFIG_PATH = Path(__file__).parent / "config.json"


def load_config():
    """Load Gmail credentials from config.json."""
    if not CONFIG_PATH.exists():
        print(f"Error: {CONFIG_PATH} not found.")
        print("Create config.json with your Gmail credentials. See config.example.json.")
        sys.exit(1)
    with open(CONFIG_PATH) as f:
        config = json.load(f)
    required = ["gmail_address", "gmail_app_password"]
    for key in required:
        if key not in config:
            print(f"Error: '{key}' missing from config.json")
            sys.exit(1)
    return config


def load_template(template_path):
    """Load and parse an email template. Returns (subject, body) using ${var} syntax."""
    text = Path(template_path).read_text()
    lines = text.strip().split("\n")

    subject = ""
    body_lines = []
    if lines[0].startswith("Subject:"):
        subject = lines[0].replace("Subject:", "").strip()
        body_lines = lines[1:]
    else:
        body_lines = lines

    body = "\n".join(body_lines).strip()
    return subject, body


def load_contacts(contacts_path):
    """Load contacts from a CSV file."""
    contacts = []
    with open(contacts_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contacts.append(row)
    return contacts


def personalize(template_str, contact):
    """Replace ${placeholders} with contact data."""
    t = Template(template_str)
    return t.safe_substitute(contact)


def send_email(smtp_conn, from_addr, to_addr, subject, body):
    """Send a single email via an existing SMTP connection."""
    msg = MIMEText(body, "plain")
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    smtp_conn.sendmail(from_addr, to_addr, msg.as_string())


def main():
    parser = argparse.ArgumentParser(description="Send cold emails via Gmail")
    parser.add_argument(
        "--template",
        default="templates/cold_outreach.txt",
        help="Path to email template file (default: templates/cold_outreach.txt)",
    )
    parser.add_argument(
        "--contacts",
        default="contacts.csv",
        help="Path to contacts CSV (default: contacts.csv)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview emails without sending",
    )
    parser.add_argument(
        "--delay",
        type=int,
        default=5,
        help="Seconds between emails to avoid rate limits (default: 5)",
    )
    args = parser.parse_args()

    config = load_config()
    gmail_address = config["gmail_address"]
    app_password = config["gmail_app_password"]

    subject_template, body_template = load_template(args.template)
    contacts = load_contacts(args.contacts)

    if not contacts:
        print("No contacts found in CSV.")
        sys.exit(1)

    print(f"Template: {args.template}")
    print(f"Contacts: {len(contacts)} loaded")
    print(f"From: {gmail_address}")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE SEND'}")
    print("-" * 50)

    if not args.dry_run:
        smtp = smtplib.SMTP("smtp.gmail.com", 587)
        smtp.starttls()
        smtp.login(gmail_address, app_password)
        print("Connected to Gmail SMTP successfully.\n")

    sent = 0
    for i, contact in enumerate(contacts):
        to_email = contact.get("email", "")
        if not to_email:
            print(f"Skipping contact with no email: {contact}")
            continue

        subject = personalize(subject_template, contact)
        body = personalize(body_template, contact)

        if args.dry_run:
            print(f"--- Email {i + 1} ---")
            print(f"To: {to_email}")
            print(f"Subject: {subject}")
            print(f"Body:\n{body}")
            print()
        else:
            try:
                send_email(smtp, gmail_address, to_email, subject, body)
                sent += 1
                print(f"[{sent}] Sent to {to_email}")
                if i < len(contacts) - 1:
                    time.sleep(args.delay)
            except Exception as e:
                print(f"Failed to send to {to_email}: {e}")

    if not args.dry_run:
        smtp.quit()
        print(f"\nDone. {sent}/{len(contacts)} emails sent.")
    else:
        print(f"Dry run complete. {len(contacts)} emails previewed.")


if __name__ == "__main__":
    main()
