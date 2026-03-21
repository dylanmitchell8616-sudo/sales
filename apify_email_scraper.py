#!/usr/bin/env python3
"""
Apify Email Scraper - Scrapes contact pages of NS leads to find emails.
Uses apify/contact-details-scraper actor to extract emails from websites.
Processes in batches to stay within starter pack limits.
"""

import csv
import json
import time
import sys
import requests
import os
from urllib.parse import urlparse

APIFY_TOKEN = os.environ.get("APIFY_TOKEN", "")
ACTOR_ID = "vdrmota~contact-info-scraper"  # Contact Details Scraper
BATCH_SIZE = 50  # Domains per batch
MAX_PAGES_PER_DOMAIN = 3
INPUT_FILE = "output/ns_leads_qualified.csv"
OUTPUT_FILE = "output/apify_email_results.json"
MERGED_FILE = "output/ns_leads_qualified.csv"

API_BASE = "https://api.apify.com/v2"


def get_domains_needing_emails():
    """Load qualified leads that are missing emails and have domains."""
    leads = []
    with open(INPUT_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not row.get('email', '').strip() and row.get('domain', '').strip():
                domain = row['domain'].strip()
                # Clean domain - remove www. prefix for consistency
                clean = domain.replace('https://', '').replace('http://', '').rstrip('/')
                # Build proper URL
                if not clean.startswith('http'):
                    url = f"https://{clean}"
                else:
                    url = clean
                leads.append({
                    'company_name': row.get('company_name', ''),
                    'domain': domain,
                    'url': url,
                    'category': row.get('category', ''),
                })
    return leads


def build_start_urls(leads_batch):
    """Build start URLs for the scraper - target contact/about pages."""
    urls = []
    for lead in leads_batch:
        base = lead['url'].rstrip('/')
        urls.append({"url": base})
        # Also try common contact page patterns
        urls.append({"url": f"{base}/contact"})
        urls.append({"url": f"{base}/about"})
    return urls


def run_actor(start_urls, batch_num, total_batches):
    """Run the Apify contact details scraper actor."""
    print(f"\n--- Batch {batch_num}/{total_batches} ({len(start_urls)} URLs) ---")

    # Use the contact details scraper
    actor_input = {
        "startUrls": start_urls,
        "maxRequestsPerStartUrl": 1,
        "maxDepth": 0,  # Don't crawl beyond the given URLs
        "maxRequestsPerCrawl": len(start_urls),
        "proxyConfiguration": {"useApifyProxy": True},
    }

    # Start the actor run
    url = f"{API_BASE}/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}"
    resp = requests.post(url, json=actor_input, timeout=30)

    if resp.status_code != 201:
        print(f"  ERROR starting actor: {resp.status_code} - {resp.text[:200]}")
        return []

    run_data = resp.json()['data']
    run_id = run_data['id']
    print(f"  Run started: {run_id}")

    # Poll for completion
    for attempt in range(60):  # Max 5 minutes
        time.sleep(5)
        status_url = f"{API_BASE}/actor-runs/{run_id}?token={APIFY_TOKEN}"
        status_resp = requests.get(status_url, timeout=15)
        status = status_resp.json()['data']['status']

        if status == 'SUCCEEDED':
            print(f"  Run completed successfully")
            break
        elif status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
            print(f"  Run {status}")
            return []
        else:
            if attempt % 6 == 0:
                print(f"  Status: {status}...")
    else:
        print("  Timed out waiting for run")
        return []

    # Get results
    dataset_id = status_resp.json()['data']['defaultDatasetId']
    results_url = f"{API_BASE}/datasets/{dataset_id}/items?token={APIFY_TOKEN}"
    results_resp = requests.get(results_url, timeout=30)

    if results_resp.status_code == 200:
        items = results_resp.json()
        print(f"  Got {len(items)} results")
        return items
    else:
        print(f"  ERROR fetching results: {results_resp.status_code}")
        return []


def extract_emails_from_results(results, leads_batch):
    """Match scraped emails back to domains."""
    # Build domain -> emails mapping
    domain_emails = {}
    for item in results:
        scraped_url = item.get('url', '') or item.get('pageUrl', '')
        emails = item.get('emails', []) or []
        phones = item.get('phones', []) or item.get('phoneNumbers', []) or []

        if not scraped_url or not emails:
            continue

        # Extract domain from scraped URL
        parsed = urlparse(scraped_url)
        scraped_domain = parsed.netloc.lower().replace('www.', '')

        if scraped_domain not in domain_emails:
            domain_emails[scraped_domain] = {
                'emails': set(),
                'phones': set(),
            }

        for email in emails:
            e = email.strip().lower() if isinstance(email, str) else str(email).strip().lower()
            # Filter out generic/spam emails
            if '@' in e and not any(x in e for x in ['noreply', 'no-reply', 'example.com', 'sentry', 'wixpress']):
                domain_emails[scraped_domain]['emails'].add(e)

        for phone in phones:
            p = str(phone).strip()
            if p:
                domain_emails[scraped_domain]['phones'].add(p)

    # Match back to leads
    matched = {}
    for lead in leads_batch:
        domain = lead['domain'].lower().replace('www.', '').replace('https://', '').replace('http://', '').rstrip('/')
        if domain in domain_emails:
            info = domain_emails[domain]
            matched[lead['domain']] = {
                'company_name': lead['company_name'],
                'domain': lead['domain'],
                'emails': list(info['emails']),
                'phones': list(info['phones']),
            }

    return matched


def merge_emails_into_leads(all_matches):
    """Merge found emails back into the qualified leads CSV."""
    # Build domain -> best email mapping
    domain_email_map = {}
    for domain, info in all_matches.items():
        clean_domain = domain.lower().replace('www.', '').replace('https://', '').replace('http://', '').rstrip('/')
        emails = info.get('emails', [])
        if emails:
            # Prefer info@, contact@, office@, then first available
            best = emails[0]
            for e in emails:
                if any(prefix in e for prefix in ['info@', 'contact@', 'office@', 'hello@', 'admin@']):
                    best = e
                    break
            domain_email_map[clean_domain] = best

    # Read and update leads
    rows = []
    updated = 0
    with open(MERGED_FILE, 'r') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        for row in reader:
            if not row.get('email', '').strip() and row.get('domain', '').strip():
                domain = row['domain'].lower().replace('www.', '').replace('https://', '').replace('http://', '').rstrip('/')
                if domain in domain_email_map:
                    row['email'] = domain_email_map[domain]
                    updated += 1
            rows.append(row)

    # Write back
    with open(MERGED_FILE, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nMerged {updated} emails into {MERGED_FILE}")
    return updated


def main():
    dry_run = '--dry-run' in sys.argv

    print("=== Apify Email Scraper for NS Leads ===\n")

    # Load leads
    leads = get_domains_needing_emails()
    print(f"Found {len(leads)} qualified leads missing emails with domains")

    if not leads:
        print("No leads to process!")
        return

    # Check account usage first
    usage_url = f"{API_BASE}/users/me/usage/monthly?token={APIFY_TOKEN}"
    try:
        usage_resp = requests.get(usage_url, timeout=10)
        if usage_resp.status_code == 200:
            usage = usage_resp.json()['data']
            print(f"Monthly usage: ${usage.get('totalUsageUsd', 0):.2f}")
    except Exception as e:
        print(f"Could not check usage: {e}")

    if dry_run:
        print(f"\n[DRY RUN] Would scrape {len(leads)} domains in {(len(leads) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
        for i, lead in enumerate(leads[:10]):
            print(f"  {i+1}. {lead['domain']} ({lead['company_name']})")
        if len(leads) > 10:
            print(f"  ... and {len(leads) - 10} more")
        return

    # Process in batches
    all_matches = {}
    total_batches = (len(leads) + BATCH_SIZE - 1) // BATCH_SIZE

    for batch_num in range(total_batches):
        start = batch_num * BATCH_SIZE
        end = min(start + BATCH_SIZE, len(leads))
        batch = leads[start:end]

        start_urls = build_start_urls(batch)
        results = run_actor(start_urls, batch_num + 1, total_batches)

        if results:
            matches = extract_emails_from_results(results, batch)
            all_matches.update(matches)
            print(f"  Found emails for {len(matches)}/{len(batch)} domains in this batch")

        # Small delay between batches
        if batch_num < total_batches - 1:
            time.sleep(2)

    # Save raw results
    with open(OUTPUT_FILE, 'w') as f:
        json.dump(all_matches, f, indent=2)
    print(f"\nSaved {len(all_matches)} email matches to {OUTPUT_FILE}")

    # Merge into leads
    if all_matches:
        updated = merge_emails_into_leads(all_matches)

    # Final summary
    total_with_email = 0
    total_leads = 0
    with open(MERGED_FILE, 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            total_leads += 1
            if row.get('email', '').strip():
                total_with_email += 1

    print(f"\n=== Final Summary ===")
    print(f"Qualified leads: {total_leads}")
    print(f"With email: {total_with_email}")
    print(f"Still missing: {total_leads - total_with_email}")
    print(f"Email coverage: {total_with_email/total_leads*100:.1f}%")


if __name__ == '__main__':
    main()
