#!/usr/bin/env python3
"""Automated Outlook Inbox Setup for Instantly.

Generates Outlook/Hotmail email addresses, guides you through
quick account creation, and auto-connects everything to Instantly
with warmup enabled.

Usage:
    python setup_outlook_inboxes.py

What this automates:
    1. Generates professional email variations using your name
    2. Opens signup pages in your browser for fast account creation
    3. As you create each account, enter the password and it auto-adds to Instantly
    4. Enables warmup on all new inboxes
    5. Saves everything to a registry for tracking
"""

import os
import sys
import json
import time
import webbrowser
import subprocess
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from instantly import InstantlyClient, AccountManager

# ─── Configuration ──────────────────────────────────────────────
FIRST_NAMES = ["dylan", "ryan", "alex", "jordan", "taylor", "morgan", "casey", "riley"]
LAST_NAMES = ["mitchell", "stephens", "carter", "brooks", "hayes", "reed", "cole", "grant"]
DOMAINS = ["outlook.com", "hotmail.com"]
DAILY_LIMIT = 30
REGISTRY_FILE = "inboxes/outlook_auto_registry.json"

SMTP = {"host": "smtp-mail.outlook.com", "port": 587}
IMAP = {"host": "outlook.office365.com", "port": 993}
SIGNUP_URL = "https://signup.live.com/signup?mkt=en-us&lic=1"
# ────────────────────────────────────────────────────────────────


def generate_email_addresses(count: int = 10) -> list[str]:
    """Generate unique professional email address suggestions."""
    addresses = []
    patterns = [
        "{f}.{l}",
        "{f}{l}",
        "{f[0]}.{l}",
        "{f}.{l[0]}",
        "{f[0]}{l}",
        "{l}.{f}",
        "{f}_{l}",
    ]

    for first in FIRST_NAMES:
        for last in LAST_NAMES:
            for domain in DOMAINS:
                for pattern in patterns:
                    try:
                        local = pattern.format(f=first, l=last)
                        addr = f"{local}@{domain}"
                        if addr not in addresses:
                            addresses.append(addr)
                    except (IndexError, KeyError):
                        continue
                    if len(addresses) >= count * 3:
                        break

    return addresses[:count]


def load_registry() -> dict:
    """Load or create the inbox registry."""
    path = Path(REGISTRY_FILE)
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"created": [], "added_to_instantly": [], "failed": []}


def save_registry(registry: dict):
    """Save the registry."""
    path = Path(REGISTRY_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(registry, f, indent=2)


def add_to_instantly(client: InstantlyClient, email: str, password: str,
                     first_name: str) -> bool:
    """Add a single Outlook inbox to Instantly with warmup."""
    try:
        manager = AccountManager(client)
        manager.add_inbox(
            email=email,
            password=password,
            first_name=first_name,
            provider="outlook",
            daily_limit=DAILY_LIMIT,
            warmup=True,
        )
        print(f"  ✓ Added to Instantly: {email}")
        print(f"    Warmup: ENABLED | Daily limit: {DAILY_LIMIT}")
        return True
    except Exception as e:
        print(f"  ✗ Failed to add {email}: {e}")
        return False


def open_signup():
    """Open the Outlook signup page."""
    try:
        webbrowser.open(SIGNUP_URL)
    except Exception:
        print(f"\n  Open this URL manually: {SIGNUP_URL}")


def run_interactive_setup():
    """Interactive setup - create accounts one by one."""
    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("ERROR: INSTANTLY_API_KEY not set in .env")
        sys.exit(1)

    client = InstantlyClient(api_key)
    registry = load_registry()

    # Check existing inboxes to avoid duplicates
    existing = set()
    try:
        accounts = client.list_accounts()
        for acc in accounts:
            email = acc if isinstance(acc, str) else acc.get("email", "")
            existing.add(email.lower())
        print(f"\n  Currently {len(existing)} inboxes in Instantly")
    except Exception as e:
        print(f"  Warning: Could not fetch existing accounts: {e}")

    already_created = {e["email"].lower() for e in registry.get("created", [])}

    # Generate suggestions
    suggestions = generate_email_addresses(count=20)
    # Filter out already existing
    new_suggestions = [
        s for s in suggestions
        if s.lower() not in existing and s.lower() not in already_created
    ]

    print(f"\n{'='*60}")
    print(f"  OUTLOOK INBOX AUTO-SETUP FOR INSTANTLY")
    print(f"{'='*60}")
    print(f"\n  {len(new_suggestions)} new inbox suggestions ready")
    print(f"  Each one you create will be auto-added to Instantly\n")

    print("  How it works:")
    print("  1. I'll suggest an email address")
    print("  2. I'll open the Outlook signup page")
    print("  3. You create the account (takes ~60 seconds)")
    print("  4. Enter the password here")
    print("  5. It auto-connects to Instantly with warmup\n")

    created_count = 0
    for i, email in enumerate(new_suggestions):
        print(f"\n{'─'*60}")
        print(f"  Inbox {i+1}/{len(new_suggestions)}: {email}")
        print(f"{'─'*60}")

        action = input("\n  [c]reate this one, [s]kip, [q]uit, [o]pen signup page: ").strip().lower()

        if action == "q":
            break
        elif action == "s":
            continue
        elif action == "o":
            open_signup()
            action = input("  Page opened. Press [c] when account is created, [s] to skip: ").strip().lower()
            if action != "c":
                continue

        if action == "c":
            # If they haven't opened signup yet, open it
            print(f"\n  → Create this account at signup.live.com:")
            print(f"    Email: {email}")
            print(f"    (Use any strong password, then paste it below)")

            open_now = input("\n  Open signup page? [y/n]: ").strip().lower()
            if open_now == "y":
                open_signup()
                input("  Press Enter when the account is created...")

            password = input(f"  Enter password for {email}: ").strip()
            if not password:
                print("  Skipped (no password entered)")
                continue

            # Extract first name from email
            local = email.split("@")[0]
            first_name = local.split(".")[0].split("_")[0].title()

            # Add to Instantly
            success = add_to_instantly(client, email, password, first_name)

            # Save to registry
            entry = {
                "email": email,
                "password": password,
                "first_name": first_name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "added_to_instantly": success,
            }

            if success:
                registry["added_to_instantly"].append(entry)
                created_count += 1
            else:
                registry["failed"].append(entry)

            registry["created"].append(entry)
            save_registry(registry)

            print(f"\n  Progress: {created_count} new inbox(es) added to Instantly")

    print(f"\n{'='*60}")
    print(f"  SETUP COMPLETE")
    print(f"  Created & added: {created_count} new inbox(es)")
    print(f"  Total in Instantly: {len(existing) + created_count}")
    print(f"  Registry saved to: {REGISTRY_FILE}")
    print(f"{'='*60}\n")


def run_batch_mode(csv_path: str):
    """Batch mode - add accounts from a CSV file.

    CSV format: email,password,first_name
    """
    import csv

    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("ERROR: INSTANTLY_API_KEY not set in .env")
        sys.exit(1)

    client = InstantlyClient(api_key)
    registry = load_registry()

    accounts = []
    with open(csv_path, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("password") and row["password"] != "FILL_IN":
                accounts.append(row)

    print(f"\n  Batch adding {len(accounts)} inbox(es) to Instantly...\n")

    success = 0
    for acc in accounts:
        email = acc["email"]
        password = acc["password"]
        first_name = acc.get("first_name", email.split("@")[0].split(".")[0].title())

        ok = add_to_instantly(client, email, password, first_name)
        entry = {
            "email": email,
            "password": password,
            "first_name": first_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "added_to_instantly": ok,
        }
        registry["created"].append(entry)
        if ok:
            registry["added_to_instantly"].append(entry)
            success += 1
        else:
            registry["failed"].append(entry)

    save_registry(registry)
    print(f"\n  Done: {success}/{len(accounts)} added successfully")


def run_quick_add():
    """Quick add - paste email and password, instantly adds to account."""
    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("ERROR: INSTANTLY_API_KEY not set in .env")
        sys.exit(1)

    client = InstantlyClient(api_key)
    registry = load_registry()

    print(f"\n{'='*60}")
    print(f"  QUICK ADD MODE")
    print(f"  Paste email and password to instantly add to your account")
    print(f"  Type 'done' to finish")
    print(f"{'='*60}\n")

    count = 0
    while True:
        email = input("  Email (or 'done'): ").strip()
        if email.lower() == "done":
            break

        password = input("  Password: ").strip()
        if not password:
            continue

        first_name = email.split("@")[0].split(".")[0].split("_")[0].title()

        ok = add_to_instantly(client, email, password, first_name)
        entry = {
            "email": email,
            "password": password,
            "first_name": first_name,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "added_to_instantly": ok,
        }
        registry["created"].append(entry)
        if ok:
            registry["added_to_instantly"].append(entry)
            count += 1

        save_registry(registry)

    print(f"\n  Added {count} inbox(es). Registry saved.")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Outlook Inbox Auto-Setup for Instantly")
    parser.add_argument("--mode", choices=["interactive", "batch", "quick", "generate"],
                        default="interactive", help="Setup mode")
    parser.add_argument("--csv", help="CSV file for batch mode")
    parser.add_argument("--count", type=int, default=20, help="Number of emails to generate")
    args = parser.parse_args()

    if args.mode == "generate":
        print("\nSuggested Outlook email addresses:\n")
        for i, addr in enumerate(generate_email_addresses(args.count), 1):
            print(f"  {i:2d}. {addr}")
        print(f"\nRun with --mode interactive to start creating them")

    elif args.mode == "batch":
        if not args.csv:
            print("ERROR: --csv required for batch mode")
            sys.exit(1)
        run_batch_mode(args.csv)

    elif args.mode == "quick":
        run_quick_add()

    else:
        run_interactive_setup()
