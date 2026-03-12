#!/usr/bin/env python3
"""Generate personalized sales outreach emails from templates and a contacts CSV."""

import argparse
import csv
from pathlib import Path
from string import Template


def load_template(template_path: str) -> Template:
    return Template(Path(template_path).read_text())


def load_contacts(contacts_path: str) -> list[dict]:
    with open(contacts_path, newline="") as f:
        return list(csv.DictReader(f))


def generate_emails(template: Template, contacts: list[dict], output_dir: Path):
    output_dir.mkdir(parents=True, exist_ok=True)
    for contact in contacts:
        email_text = template.safe_substitute(contact)
        filename = f"{contact['first_name']}_{contact['last_name']}.txt".lower()
        out_path = output_dir / filename
        out_path.write_text(email_text)
        print(f"Generated: {out_path}")


def main():
    parser = argparse.ArgumentParser(description="Generate personalized sales emails")
    parser.add_argument(
        "--template",
        default="templates/cold_outreach.txt",
        help="Path to the email template file (default: templates/cold_outreach.txt)",
    )
    parser.add_argument(
        "--contacts",
        default="contacts.csv",
        help="Path to the contacts CSV file (default: contacts.csv)",
    )
    parser.add_argument(
        "--output",
        default="output",
        help="Output directory for generated emails (default: output)",
    )
    args = parser.parse_args()

    template = load_template(args.template)
    contacts = load_contacts(args.contacts)
    generate_emails(template, contacts, Path(args.output))
    print(f"\nDone! Generated {len(contacts)} emails in '{args.output}/'")


if __name__ == "__main__":
    main()
