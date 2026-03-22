#!/usr/bin/env python3
"""
Apify Email Scraper - Scrapes contact pages of NS leads to find emails.
Uses apify/contact-details-scraper actor to extract emails from websites.
Processes in batches to stay within starter pack limits.
"""

import csv
import json
import re
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
CACHE_FILE = "output/apify_email_cache.json"

API_BASE = "https://api.apify.com/v2"

# Basic email validation
EMAIL_REGEX = re.compile(r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$')


def api_request_with_retry(method, url, max_retries=3, **kwargs):
    """HTTP request with exponential backoff retry."""
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


def validate_email(email: str) -> bool:
    """Validate email format."""
    if not email or not EMAIL_REGEX.match(email):
        return False
    if len(email) > 254:
        return False
    return True


def load_email_cache() -> dict:
    """Load previously scraped email results."""
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_email_cache(cache: dict):
    """Save email results to cache."""
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


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
    """Run the Apify contact details scraper actor with retry logic."""
    print(f"\n--- Batch {batch_num}/{total_batches} ({len(start_urls)} URLs) ---")

    actor_input = {
        "startUrls": start_urls,
        "maxRequestsPerStartUrl": 1,
        "maxDepth": 0,
        "maxRequestsPerCrawl": len(start_urls),
        "proxyConfiguration": {"useApifyProxy": True},
    }

    url = f"{API_BASE}/acts/{ACTOR_ID}/runs?token={APIFY_TOKEN}"
    resp = api_request_with_retry("POST", url, json=actor_input)

    if resp.status_code != 201:
        print(f"  ERROR starting actor: {resp.status_code} - {resp.text[:200]}")
        return []

    run_data = resp.json()['data']
    run_id = run_data['id']
    start_time = time.time()
    print(f"  Run started: {run_id}")

    # Poll for completion
    for attempt in range(60):
        time.sleep(5)
        status_url = f"{API_BASE}/actor-runs/{run_id}?token={APIFY_TOKEN}"
        try:
            status_resp = api_request_with_retry("GET", status_url, timeout=15)
            status = status_resp.json()['data']['status']
        except (requests.RequestException, KeyError, ValueError) as e:
            print(f"  Poll error: {e}")
            continue

        elapsed = int(time.time() - start_time)
        if status == 'SUCCEEDED':
            print(f"  Run completed in {elapsed}s")
            break
        elif status in ('FAILED', 'ABORTED', 'TIMED-OUT'):
            print(f"  Run {status} after {elapsed}s")
            return []
        elif attempt % 6 == 0:
            print(f"  Status: {status}... ({elapsed}s)")
    else:
        print("  Timed out waiting for run")
        return []

    dataset_id = status_resp.json()['data']['defaultDatasetId']
    results_url = f"{API_BASE}/datasets/{dataset_id}/items?token={APIFY_TOKEN}"
    results_resp = api_request_with_retry("GET", results_url)

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


def score_email(email: str, domain: str) -> int:
    """Score an email for outreach quality. Higher = better."""
    score = 0
    email_lower = email.lower()
    domain_lower = domain.lower().replace('www.', '')

    # Emails matching the business domain
    if domain_lower in email_lower:
        score += 50

    # Personal emails (owner names) are best for B2B
    if re.match(r'^[a-z]+[._]?[a-z]+@', email_lower):
        score += 20

    # Role-based email ranking
    role_scores = {
        "info@": 10, "contact@": 9, "hello@": 8, "office@": 7,
        "admin@": 5, "reception@": 5, "sales@": 3, "support@": 2,
    }
    for prefix, pts in role_scores.items():
        if email_lower.startswith(prefix):
            score += pts
            break

    return score


def merge_emails_into_leads(all_matches):
    """Merge found emails back into the qualified leads CSV."""
    domain_email_map = {}
    for domain, info in all_matches.items():
        clean_domain = domain.lower().replace('www.', '').replace('https://', '').replace('http://', '').rstrip('/')
        emails = [e for e in info.get('emails', []) if validate_email(e)]
        if emails:
            # Score and pick best email
            best = sorted(emails, key=lambda e: score_email(e, clean_domain), reverse=True)[0]
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

    # Load cache to skip already-scraped domains
    email_cache = load_email_cache()
    cached_count = 0
    uncached_leads = []
    for lead in leads:
        domain_key = lead['domain'].lower().replace('www.', '').rstrip('/')
        if domain_key in email_cache:
            cached_count += 1
        else:
            uncached_leads.append(lead)

    if cached_count:
        print(f"Skipping {cached_count} already-cached domains, {len(uncached_leads)} to scrape")

    if dry_run:
        print(f"\n[DRY RUN] Would scrape {len(uncached_leads)} domains in {(len(uncached_leads) + BATCH_SIZE - 1) // BATCH_SIZE} batches")
        for i, lead in enumerate(uncached_leads[:10]):
            print(f"  {i+1}. {lead['domain']} ({lead['company_name']})")
        if len(uncached_leads) > 10:
            print(f"  ... and {len(uncached_leads) - 10} more")
        return

    # Process uncached leads in batches
    all_matches = {}
    total_batches = max(1, (len(uncached_leads) + BATCH_SIZE - 1) // BATCH_SIZE)
    scrape_start = time.time()

    for batch_num in range(total_batches):
        start_idx = batch_num * BATCH_SIZE
        end_idx = min(start_idx + BATCH_SIZE, len(uncached_leads))
        batch = uncached_leads[start_idx:end_idx]

        if not batch:
            break

        start_urls = build_start_urls(batch)
        results = run_actor(start_urls, batch_num + 1, total_batches)

        if results:
            matches = extract_emails_from_results(results, batch)
            all_matches.update(matches)
            # Update cache with new results
            for domain, info in matches.items():
                domain_key = domain.lower().replace('www.', '').rstrip('/')
                email_cache[domain_key] = info
            print(f"  Found emails for {len(matches)}/{len(batch)} domains in this batch")

        # Progress estimate
        elapsed = time.time() - scrape_start
        if batch_num > 0:
            avg_per_batch = elapsed / (batch_num + 1)
            remaining = avg_per_batch * (total_batches - batch_num - 1)
            print(f"  Progress: {batch_num + 1}/{total_batches} batches, ~{int(remaining)}s remaining")

        if batch_num < total_batches - 1:
            time.sleep(2)

    # Save cache and raw results
    save_email_cache(email_cache)
    # Merge cached results into all_matches for the merge step
    for domain_key, info in email_cache.items():
        if domain_key not in all_matches:
            all_matches[domain_key] = info

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

    scrape_elapsed = int(time.time() - scrape_start)
    print(f"\n{'=' * 40}")
    print(f"SCRAPE COMPLETE — SUMMARY")
    print(f"{'=' * 40}")
    print(f"  Qualified leads:   {total_leads}")
    print(f"  With email:        {total_with_email}")
    print(f"  Still missing:     {total_leads - total_with_email}")
    print(f"  Email coverage:    {total_with_email/total_leads*100:.1f}%")
    print(f"  Domains cached:    {len(email_cache)}")
    print(f"  Time elapsed:      {scrape_elapsed}s")
    print(f"{'=' * 40}")


if __name__ == '__main__':
    main()
