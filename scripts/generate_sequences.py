#!/usr/bin/env python3
"""
Realside AI - Email Sequence Generator for Instantly
Reads ICP config + sequence templates, generates personalized email campaigns
ready to import into Instantly as CSV.
"""

import json
import csv
import os
import sys
import argparse
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
TEMPLATES_DIR = BASE_DIR / "templates" / "email_sequences"
OUTPUT_DIR = BASE_DIR / "output" / "campaigns"


def load_json(filepath):
    with open(filepath, "r") as f:
        return json.load(f)


def load_contacts(csv_path):
    """Load contacts from Apollo CSV export."""
    contacts = []
    with open(csv_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            contact = {
                "first_name": row.get("First Name", row.get("first_name", "")).strip(),
                "last_name": row.get("Last Name", row.get("last_name", "")).strip(),
                "email": row.get("Email", row.get("email", "")).strip(),
                "company_name": row.get("Company", row.get("company_name", row.get("Organization Name", ""))).strip(),
                "industry": row.get("Industry", row.get("industry", "")).strip(),
                "title": row.get("Title", row.get("title", "")).strip(),
                "location": row.get("City", row.get("location", "")).strip(),
                "linkedin_url": row.get("LinkedIn Url", row.get("linkedin_url", "")).strip(),
            }
            if contact["email"] and contact["first_name"]:
                contacts.append(contact)
    return contacts


def personalize_template(template_text, contact, sender_config):
    """Replace all {{variables}} in template with contact data."""
    replacements = {
        "{{first_name}}": contact.get("first_name", ""),
        "{{last_name}}": contact.get("last_name", ""),
        "{{email}}": contact.get("email", ""),
        "{{company_name}}": contact.get("company_name", "there"),
        "{{industry}}": contact.get("industry", "your industry"),
        "{{title}}": contact.get("title", ""),
        "{{location}}": contact.get("location", ""),
        "{{sender_name}}": sender_config.get("name", ""),
        "{{sender_title}}": sender_config.get("title", ""),
        "{{sender_email}}": sender_config.get("email", ""),
        "{{sender_phone}}": sender_config.get("phone", ""),
        "{{calendly_link}}": sender_config.get("calendly_link", ""),
    }
    result = template_text
    for key, value in replacements.items():
        result = result.replace(key, value)
    return result


def generate_instantly_csv(contacts, sequence, sender_config, output_path):
    """
    Generate CSV in Instantly import format.
    Instantly format: email, first_name, last_name, company_name, custom variables...
    Each step becomes a separate campaign CSV.
    """
    os.makedirs(output_path, exist_ok=True)
    files_created = []

    for step in sequence["steps"]:
        step_num = step["step"]
        filename = f"step_{step_num}_day_{step['delay_days']}.csv"
        filepath = os.path.join(output_path, filename)

        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "email", "first_name", "last_name", "company_name",
                "industry", "title", "personalized_subject", "personalized_body"
            ])

            for contact in contacts:
                subject = personalize_template(step["subject"], contact, sender_config)
                body = personalize_template(step["body"], contact, sender_config)

                writer.writerow([
                    contact["email"],
                    contact["first_name"],
                    contact.get("last_name", ""),
                    contact.get("company_name", ""),
                    contact.get("industry", ""),
                    contact.get("title", ""),
                    subject,
                    body,
                ])

        files_created.append(filepath)
        print(f"  ✓ Created {filename} ({len(contacts)} contacts)")

    return files_created


def generate_master_contact_list(contacts, output_path):
    """Generate a master contact list with dedup."""
    os.makedirs(output_path, exist_ok=True)
    filepath = os.path.join(output_path, "master_contacts.csv")

    seen_emails = set()
    unique_contacts = []
    for c in contacts:
        if c["email"].lower() not in seen_emails:
            seen_emails.add(c["email"].lower())
            unique_contacts.append(c)

    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "first_name", "last_name", "email", "company_name",
            "industry", "title", "location", "linkedin_url"
        ])
        writer.writeheader()
        writer.writerows(unique_contacts)

    print(f"  ✓ Master list: {len(unique_contacts)} unique contacts (deduped from {len(contacts)})")
    return filepath


def main():
    parser = argparse.ArgumentParser(description="Generate personalized email sequences for Instantly")
    parser.add_argument("contacts_csv", help="Path to Apollo CSV export with contacts")
    parser.add_argument("--sequence", choices=["crm_reactivation", "voice_agent", "combo"],
                        default="crm_reactivation",
                        help="Which email sequence to use")
    parser.add_argument("--sender-name", required=True, help="Your name")
    parser.add_argument("--sender-email", required=True, help="Your sending email")
    parser.add_argument("--sender-title", default="", help="Your title")
    parser.add_argument("--calendly-link", default="", help="Your Calendly booking link")
    parser.add_argument("--output-dir", default=None, help="Custom output directory")

    args = parser.parse_args()

    sender_config = {
        "name": args.sender_name,
        "email": args.sender_email,
        "title": args.sender_title,
        "calendly_link": args.calendly_link,
    }

    # Load sequence template
    sequence_map = {
        "crm_reactivation": "crm_reactivation_sequence.json",
        "voice_agent": "voice_agent_sequence.json",
        "combo": "combo_sequence.json",
    }
    sequence_file = TEMPLATES_DIR / sequence_map[args.sequence]
    sequence = load_json(sequence_file)

    print(f"\n{'='*60}")
    print(f"Realside AI - Email Sequence Generator")
    print(f"{'='*60}")
    print(f"Sequence: {sequence['sequence_name']}")
    print(f"Sender: {sender_config['name']} <{sender_config['email']}>")

    # Load contacts
    contacts = load_contacts(args.contacts_csv)
    print(f"Contacts loaded: {len(contacts)}")

    if not contacts:
        print("ERROR: No valid contacts found in CSV. Check column headers.")
        sys.exit(1)

    # Set output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    campaign_name = f"{args.sequence}_{timestamp}"
    output_path = args.output_dir or str(OUTPUT_DIR / campaign_name)

    print(f"\nGenerating campaign: {campaign_name}")
    print(f"Output: {output_path}\n")

    # Generate CSVs
    print("Email sequence files:")
    files = generate_instantly_csv(contacts, sequence, sender_config, output_path)

    print("\nContact list:")
    master = generate_master_contact_list(contacts, output_path)

    # Summary
    print(f"\n{'='*60}")
    print(f"DONE! {len(files)} sequence files generated.")
    print(f"\nNext steps:")
    print(f"  1. Review generated emails in: {output_path}")
    print(f"  2. Import step_1 CSV into Instantly as a new campaign")
    print(f"  3. Set up follow-up steps with the delay days shown")
    print(f"  4. Set sending schedule: Mon-Thu, 8-11am recipient timezone")
    print(f"  5. Enable Instantly warmup on all sending accounts")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
