#!/usr/bin/env python3
"""
Re-process Apify results from completed runs.
Fetches all datasets, extracts emails, and merges into qualified leads.
"""

import csv
import json
import os
import re
import time
import requests

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
API_BASE = "https://api.apify.com/v2"
LEADS_FILE = "output/ns_leads_qualified.csv"
OUTPUT_FILE = "output/apify_email_results.json"

JUNK_PATTERNS = [
    'noreply', 'no-reply', 'example.com', 'sentry',
    'wixpress', 'squarespace', 'mailchimp', 'googleapis',
    'cloudflare', 'wordpress', 'godaddy', 'donotreply',
]


def api_request_with_retry(method, url, max_retries=3, **kwargs):
    """HTTP request with exponential backoff."""
    kwargs.setdefault("timeout", 30)
    for attempt in range(max_retries + 1):
        try:
            resp = requests.request(method, url, **kwargs)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_retries:
                wait = 2 ** (attempt + 1)
                print(f"  HTTP {resp.status_code}, retrying in {wait}s...")
                time.sleep(wait)
                continue
            return resp
        except requests.RequestException as e:
            if attempt < max_retries:
                wait = 2 ** (attempt + 1)
                print(f"  Request error ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise
    return resp


def get_recent_runs():
    """Get all recent actor runs."""
    url = f"{API_BASE}/actor-runs?token={APIFY_TOKEN}&limit=20&desc=true"
    resp = api_request_with_retry("GET", url)
    runs = resp.json()['data']['items']
    return [r for r in runs if r['status'] == 'SUCCEEDED']


def fetch_all_emails(runs):
    """Fetch emails from all run datasets."""
    domain_emails = {}

    for i, run in enumerate(runs):
        ds = run['defaultDatasetId']
        items_url = f"{API_BASE}/datasets/{ds}/items?token={APIFY_TOKEN}&limit=1000"
        resp = api_request_with_retry("GET", items_url)
        if resp.status_code != 200:
            print(f"  Failed to fetch dataset {ds}: {resp.status_code}")
            continue

        items = resp.json()
        print(f"  Run {i + 1}/{len(runs)}: {len(items)} items")
        for item in items:
            domain = item.get('domain', '').lower().strip()
            emails = item.get('emails', []) or []

            if not domain or not emails:
                continue

            if domain not in domain_emails:
                domain_emails[domain] = set()

            for e in emails:
                e = e.strip().lower()
                if '@' in e and not any(x in e for x in JUNK_PATTERNS):
                    domain_emails[domain].add(e)

    return {d: list(emails) for d, emails in domain_emails.items() if emails}


def score_email(email: str, domain: str) -> int:
    """Score an email for outreach quality. Higher = better."""
    score = 0
    email_lower = email.lower()
    domain_lower = domain.lower().replace('www.', '')

    if domain_lower in email_lower:
        score += 50
    if re.match(r'^[a-z]+[._]?[a-z]+@', email_lower):
        score += 20

    role_scores = {
        "info@": 10, "contact@": 9, "hello@": 8, "office@": 7,
        "admin@": 5, "reception@": 5, "sales@": 3,
    }
    for prefix, pts in role_scores.items():
        if email_lower.startswith(prefix):
            score += pts
            break
    return score


def pick_best_email(emails, domain):
    """Pick the best email from a list using scoring."""
    if not emails:
        return None
    return sorted(emails, key=lambda e: score_email(e, domain), reverse=True)[0]


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
