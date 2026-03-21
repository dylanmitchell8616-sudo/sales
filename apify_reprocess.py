#!/usr/bin/env python3
"""
Re-process Apify results from completed runs.
Fetches all datasets, extracts emails, and merges into qualified leads.
"""

import csv
import json
import os
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
API_BASE = "https://api.apify.com/v2"
LEADS_FILE = "output/ns_leads_qualified.csv"
OUTPUT_FILE = "output/apify_email_results.json"


def get_recent_runs():
    """Get all recent actor runs."""
    url = f"{API_BASE}/actor-runs?token={APIFY_TOKEN}&limit=20&desc=true"
    resp = requests.get(url, timeout=15)
    runs = resp.json()['data']['items']
    # Filter to succeeded runs from our contact-info-scraper
    return [r for r in runs if r['status'] == 'SUCCEEDED']


def fetch_all_emails(runs):
    """Fetch emails from all run datasets."""
    domain_emails = {}

    for run in runs:
        ds = run['defaultDatasetId']
        items_url = f"{API_BASE}/datasets/{ds}/items?token={APIFY_TOKEN}&limit=1000"
        resp = requests.get(items_url, timeout=30)
        if resp.status_code != 200:
            continue

        items = resp.json()
        for item in items:
            domain = item.get('domain', '').lower().strip()
            emails = item.get('emails', []) or []

            if not domain or not emails:
                continue

            if domain not in domain_emails:
                domain_emails[domain] = set()

            for e in emails:
                e = e.strip().lower()
                # Filter junk emails
                if '@' in e and not any(x in e for x in [
                    'noreply', 'no-reply', 'example.com', 'sentry',
                    'wixpress', 'squarespace', 'mailchimp', 'googleapis',
                    'cloudflare', 'wordpress'
                ]):
                    domain_emails[domain].add(e)

    # Convert sets to lists
    return {d: list(emails) for d, emails in domain_emails.items() if emails}


def pick_best_email(emails, domain):
    """Pick the best email from a list - prefer info@, contact@, etc."""
    # Priority prefixes
    prefixes = ['info@', 'contact@', 'office@', 'hello@', 'admin@', 'reception@']

    # First, prefer emails that match the domain
    domain_clean = domain.replace('www.', '')
    matching = [e for e in emails if domain_clean in e]
    other = [e for e in emails if domain_clean not in e]

    for email_list in [matching, other]:
        for prefix in prefixes:
            for e in email_list:
                if e.startswith(prefix):
                    return e
        if email_list:
            return email_list[0]

    return emails[0] if emails else None


def merge_into_leads(domain_emails):
    """Merge found emails into the qualified leads CSV."""
    # Read leads
    with open(LEADS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    updated = 0
    for row in rows:
        if row.get('email', '').strip():
            continue  # Already has email

        domain = row.get('domain', '').strip().lower()
        if not domain:
            continue

        # Try matching with various domain forms
        domain_clean = domain.replace('www.', '').replace('https://', '').replace('http://', '').rstrip('/')

        matched_emails = domain_emails.get(domain_clean)
        if not matched_emails:
            # Try with www
            matched_emails = domain_emails.get(f'www.{domain_clean}')
        if not matched_emails:
            # Try original
            matched_emails = domain_emails.get(domain)

        if matched_emails:
            best = pick_best_email(matched_emails, domain_clean)
            if best:
                row['email'] = best
                updated += 1

    # Write back
    with open(LEADS_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    return updated


def main():
    print("=== Re-processing Apify Results ===\n")

    # Get runs
    runs = get_recent_runs()
    print(f"Found {len(runs)} completed runs")

    # Fetch all emails
    domain_emails = fetch_all_emails(runs)
    print(f"Found emails for {len(domain_emails)} unique domains")

    # Show some examples
    for domain, emails in list(domain_emails.items())[:10]:
        print(f"  {domain}: {emails}")

    # Save raw results
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(domain_emails, f, indent=2)
    print(f"\nSaved to {OUTPUT_FILE}")

    # Merge
    updated = merge_into_leads(domain_emails)
    print(f"\nMerged {updated} new emails into leads")

    # Final count
    total = 0
    with_email = 0
    with open(LEADS_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total += 1
            if row.get('email', '').strip():
                with_email += 1

    print(f"\n=== Final ===")
    print(f"Qualified leads: {total}")
    print(f"With email: {with_email}")
    print(f"Missing email: {total - with_email}")
    print(f"Coverage: {with_email/total*100:.1f}%")


if __name__ == '__main__':
    main()
