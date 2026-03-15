#!/usr/bin/env python3
"""One-command automation: scale your Instantly account with free Outlook inboxes.

Run with:
    python automate_everything.py

This script walks you through the full workflow:
  1. Verify Instantly API connection
  2. Show current account status (inboxes, campaigns)
  3. Generate 15 professional Outlook email suggestions
  4. Output a pre-filled CSV (inboxes/outlook_batch.csv) -- just add passwords
  5. Wait for you to create the accounts and fill in passwords
  6. Read the CSV and bulk-add all accounts to Instantly
  7. Enable warmup on every new account
  8. Show final status
"""

import os, sys, csv, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from instantly import InstantlyClient, AccountManager

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Name pool for generating realistic sender addresses
NAME_POOL = [
    ("Dylan", "Mitchell"),
    ("Ryan", "Stephens"),
    ("Alex", "Carter"),
    ("Jordan", "Brooks"),
    ("Taylor", "Hayes"),
    ("Morgan", "Reed"),
    ("Casey", "Cole"),
    ("Riley", "Grant"),
    ("Parker", "Quinn"),
    ("Avery", "Kim"),
]

OUTLOOK_DOMAINS = ["outlook.com", "hotmail.com"]
CSV_PATH = Path(__file__).parent / "inboxes" / "outlook_batch.csv"
DAILY_LIMIT = 30

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SEPARATOR = "=" * 62
THIN_SEP = "-" * 62


def banner(text: str) -> None:
    print(f"\n{SEPARATOR}")
    print(f"  {text}")
    print(SEPARATOR)


def step_header(number: int, text: str) -> None:
    print(f"\n{THIN_SEP}")
    print(f"  STEP {number}: {text}")
    print(THIN_SEP)


def generate_email_suggestions(count: int = 15) -> list[dict]:
    """Generate professional Outlook email address suggestions.

    Returns a list of dicts with keys: email, first_name, provider.
    """
    patterns = [
        "{first}.{last}",
        "{first[0]}.{last}",
        "{first}{last}",
        "{last}.{first}",
        "{first}.{last[0]}",
    ]

    suggestions: list[dict] = []
    seen: set[str] = set()

    for first_raw, last_raw in NAME_POOL:
        first = first_raw.lower()
        last = last_raw.lower()
        for domain in OUTLOOK_DOMAINS:
            for pattern in patterns:
                try:
                    local = pattern.format(
                        first=first, last=last,
                    )
                except (IndexError, KeyError):
                    continue
                addr = f"{local}@{domain}"
                if addr not in seen:
                    seen.add(addr)
                    suggestions.append({
                        "email": addr,
                        "first_name": first_raw,
                        "provider": "outlook",
                    })
                if len(suggestions) >= count:
                    return suggestions
    return suggestions[:count]


def write_csv(suggestions: list[dict], path: Path) -> None:
    """Write email suggestions to CSV with FILL_IN passwords."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["email", "password", "first_name", "provider"]
        )
        writer.writeheader()
        for s in suggestions:
            writer.writerow({
                "email": s["email"],
                "password": "FILL_IN",
                "first_name": s["first_name"],
                "provider": s["provider"],
            })


def read_csv_accounts(path: Path) -> list[dict]:
    """Read the CSV and return only rows where the password has been filled in."""
    accounts: list[dict] = []
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pw = row.get("password", "").strip()
            if pw and pw != "FILL_IN":
                accounts.append({
                    "email": row["email"].strip(),
                    "password": pw,
                    "first_name": row.get("first_name", "").strip(),
                    "provider": row.get("provider", "outlook").strip(),
                })
    return accounts


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def main() -> None:
    banner("INSTANTLY INBOX SCALE-UP AUTOMATION")
    print("  This script helps you add free Outlook inboxes to your")
    print("  Instantly account and enable warmup -- all in one run.")

    # ------------------------------------------------------------------
    # STEP 1: Check API connection
    # ------------------------------------------------------------------
    step_header(1, "CHECKING INSTANTLY API CONNECTION")

    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("\n  ERROR: INSTANTLY_API_KEY not found in environment or .env file.")
        print("  Create a .env file with:")
        print("    INSTANTLY_API_KEY=your_api_key_here")
        sys.exit(1)

    client = InstantlyClient(api_key)
    manager = AccountManager(client)

    try:
        accounts = manager.list_all()
        print(f"  API connection: OK")
    except Exception as e:
        print(f"  API connection: FAILED")
        print(f"  Error: {e}")
        print("\n  Check your INSTANTLY_API_KEY and try again.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # STEP 2: Show current account status
    # ------------------------------------------------------------------
    step_header(2, "CURRENT ACCOUNT STATUS")

    inbox_count = len(accounts)
    # Extract emails for duplicate checking later
    existing_emails: set[str] = set()
    for acc in accounts:
        email = acc if isinstance(acc, str) else acc.get("email", "")
        if email:
            existing_emails.add(email.lower())

    try:
        campaigns = client.list_campaigns()
        campaign_count = len(campaigns)
    except Exception:
        campaign_count = 0

    print(f"  Inboxes connected:   {inbox_count}")
    print(f"  Active campaigns:    {campaign_count}")
    print(f"  Daily send capacity: ~{inbox_count * DAILY_LIMIT} emails/day "
          f"({inbox_count} inboxes x {DAILY_LIMIT}/day)")

    if inbox_count >= 30:
        print(f"\n  You already have {inbox_count} inboxes -- nice foundation.")
        print(f"  Adding 15 more will boost capacity to ~{(inbox_count + 15) * DAILY_LIMIT}/day.")

    # ------------------------------------------------------------------
    # STEP 3: Generate email suggestions
    # ------------------------------------------------------------------
    step_header(3, "GENERATING 15 OUTLOOK EMAIL SUGGESTIONS")

    suggestions = generate_email_suggestions(count=15)

    # Filter out any that already exist in Instantly
    fresh: list[dict] = []
    skipped = 0
    for s in suggestions:
        if s["email"].lower() in existing_emails:
            skipped += 1
        else:
            fresh.append(s)

    if skipped:
        print(f"  Skipped {skipped} address(es) already in Instantly.")

    # If we filtered some out, try to backfill up to 15
    if len(fresh) < 15:
        extras = generate_email_suggestions(count=30)
        for s in extras:
            if s["email"].lower() not in existing_emails and s not in fresh:
                fresh.append(s)
            if len(fresh) >= 15:
                break

    suggestions = fresh[:15]

    print(f"\n  Suggested email addresses ({len(suggestions)}):\n")
    for i, s in enumerate(suggestions, 1):
        print(f"    {i:2d}. {s['email']}")

    # ------------------------------------------------------------------
    # STEP 4: Write pre-filled CSV
    # ------------------------------------------------------------------
    step_header(4, "WRITING PRE-FILLED CSV")

    write_csv(suggestions, CSV_PATH)

    print(f"  CSV saved to: {CSV_PATH}")
    print(f"  Rows written: {len(suggestions)}")
    print(f"\n  Next steps:")
    print(f"    1. Create each Outlook account at https://signup.live.com/")
    print(f"    2. Open {CSV_PATH}")
    print(f"    3. Replace FILL_IN with the real password for each account")
    print(f"    4. Save the file")
    print(f"\n  TIPS:")
    print(f"    - Use a strong password (12+ chars, mixed case, numbers)")
    print(f"    - Space out account creation to avoid Microsoft blocks")
    print(f"    - If 2FA is on, use the App Password instead")
    print(f"    - Enable IMAP in each account: Settings > Sync email")

    # ------------------------------------------------------------------
    # STEP 5: Wait for user confirmation
    # ------------------------------------------------------------------
    step_header(5, "WAITING FOR ACCOUNT CREATION")

    print(f"\n  Create the Outlook accounts and fill in passwords in the CSV.")
    print(f"  File: {CSV_PATH}")

    while True:
        print()
        response = input("  Have you created the accounts and filled in passwords? [y/n/q]: ").strip().lower()

        if response == "q":
            print("\n  Exiting. Run this script again when you're ready.")
            sys.exit(0)
        elif response == "y":
            break
        elif response == "n":
            print("  Take your time. The CSV is waiting at:")
            print(f"    {CSV_PATH}")
        else:
            print("  Please enter y (yes), n (not yet), or q (quit).")

    # ------------------------------------------------------------------
    # STEP 6: Read CSV and bulk-add to Instantly
    # ------------------------------------------------------------------
    step_header(6, "ADDING ACCOUNTS TO INSTANTLY")

    if not CSV_PATH.exists():
        print(f"  ERROR: CSV file not found at {CSV_PATH}")
        sys.exit(1)

    accounts_to_add = read_csv_accounts(CSV_PATH)

    if not accounts_to_add:
        print("  No accounts with passwords found in the CSV.")
        print("  Make sure you replaced FILL_IN with actual passwords.")
        print(f"  File: {CSV_PATH}")
        sys.exit(1)

    print(f"  Found {len(accounts_to_add)} account(s) with passwords.\n")

    added_emails: list[str] = []
    failed_emails: list[str] = []

    for i, acc in enumerate(accounts_to_add, 1):
        email = acc["email"]
        password = acc["password"]
        first_name = acc.get("first_name") or email.split("@")[0].split(".")[0].title()
        provider = acc.get("provider", "outlook")

        print(f"  [{i}/{len(accounts_to_add)}] Adding {email}...", end=" ")

        if email.lower() in existing_emails:
            print("SKIPPED (already in Instantly)")
            continue

        try:
            manager.add_inbox(
                email=email,
                password=password,
                first_name=first_name,
                provider=provider,
                daily_limit=DAILY_LIMIT,
                warmup=True,
            )
            print("OK")
            added_emails.append(email)
            # Brief pause between API calls to avoid rate limits
            time.sleep(1)
        except Exception as e:
            print(f"FAILED ({e})")
            failed_emails.append(email)

    print(f"\n  Results: {len(added_emails)} added, {len(failed_emails)} failed")

    if failed_emails:
        print(f"\n  Failed accounts:")
        for email in failed_emails:
            print(f"    - {email}")

    # ------------------------------------------------------------------
    # STEP 7: Enable warmup on all new accounts
    # ------------------------------------------------------------------
    step_header(7, "ENABLING WARMUP")

    if not added_emails:
        print("  No new accounts to warm up.")
    else:
        warmup_ok = 0
        warmup_fail = 0
        for email in added_emails:
            try:
                manager.enable_warmup(email)
                print(f"  Warmup enabled: {email}")
                warmup_ok += 1
                time.sleep(0.5)
            except Exception as e:
                print(f"  Warmup failed for {email}: {e}")
                warmup_fail += 1

        print(f"\n  Warmup enabled on {warmup_ok}/{len(added_emails)} account(s)")

    # ------------------------------------------------------------------
    # STEP 8: Final status
    # ------------------------------------------------------------------
    step_header(8, "FINAL STATUS")

    # Re-fetch to get accurate counts
    try:
        final_accounts = manager.list_all()
        final_count = len(final_accounts)
    except Exception:
        final_count = inbox_count + len(added_emails)

    try:
        final_campaigns = client.list_campaigns()
        final_campaign_count = len(final_campaigns)
    except Exception:
        final_campaign_count = campaign_count

    print(f"  Inboxes before:      {inbox_count}")
    print(f"  New inboxes added:   {len(added_emails)}")
    print(f"  Inboxes now:         {final_count}")
    print(f"  Active campaigns:    {final_campaign_count}")
    print(f"  Daily send capacity: ~{final_count * DAILY_LIMIT} emails/day")

    if added_emails:
        print(f"\n  New accounts added:")
        for email in added_emails:
            print(f"    + {email}  (warmup ON, limit {DAILY_LIMIT}/day)")

    banner("ALL DONE")
    print(f"  Your Instantly account now has {final_count} inboxes.")
    print(f"  Warmup will take 2-3 weeks to fully ramp up deliverability.")
    print(f"\n  Next steps:")
    print(f"    - Monitor warmup progress in Instantly dashboard")
    print(f"    - After warmup, assign new inboxes to your campaigns")
    print(f"    - Consider running this script again to add more inboxes")
    print(f"\n  CSV saved at: {CSV_PATH}")
    print()


if __name__ == "__main__":
    main()
