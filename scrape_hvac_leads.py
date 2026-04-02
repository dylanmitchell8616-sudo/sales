#!/usr/bin/env python3
"""
HVAC Lead Scraper — 300+ Cold Calling Leads via Apify Google Maps
==================================================================
Scrapes HVAC businesses from Google Maps across top US metros,
extracts phone numbers and emails, outputs a cold-call-ready CSV.

Usage:
    python scrape_hvac_leads.py
    python scrape_hvac_leads.py --target 500
    python scrape_hvac_leads.py --dry-run
"""

import csv
import json
import os
import re
import sys
import time
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

APIFY_BASE = "https://api.apify.com/v2"
GOOGLE_MAPS_ACTOR = "compass~crawler-google-places"
CONTACT_SCRAPER_ACTOR = "vdrmota~contact-info-scraper"

# HVAC search queries
HVAC_QUERIES = [
    "HVAC company",
    "air conditioning repair",
    "heating and cooling",
    "AC repair",
    "furnace repair",
    "HVAC contractor",
    "air conditioning installation",
    "heating repair",
]

# Top US metros — high HVAC demand markets
LOCATIONS = [
    "Houston TX", "Dallas TX", "San Antonio TX", "Austin TX", "Fort Worth TX",
    "Phoenix AZ", "Tucson AZ", "Scottsdale AZ",
    "Miami FL", "Tampa FL", "Orlando FL", "Jacksonville FL", "Fort Lauderdale FL", "Sarasota FL",
    "Atlanta GA", "Savannah GA",
    "Charlotte NC", "Raleigh NC",
    "Nashville TN", "Memphis TN",
    "Las Vegas NV", "Henderson NV",
    "Los Angeles CA", "San Diego CA", "Riverside CA", "Sacramento CA",
    "Denver CO", "Colorado Springs CO",
    "Oklahoma City OK", "Tulsa OK",
    "San Jose CA", "Fresno CA",
    "Albuquerque NM",
    "Birmingham AL", "Huntsville AL",
    "New Orleans LA", "Baton Rouge LA",
    "Kansas City MO", "St Louis MO",
    "Indianapolis IN",
    "Columbus OH", "Cincinnati OH",
    "Louisville KY",
    "Richmond VA",
    "Charleston SC",
]

JUNK_EMAIL_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "godaddy.com", "wix.com", "wixpress.com", "squarespace.com",
    "example.com", "sentry.io", "facebook.com", "instagram.com",
    "google.com", "yelp.com", "bbb.org", "angieslist.com",
    "homeadvisor.com", "thumbtack.com", "nextdoor.com",
}

GENERIC_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "no-reply",
    "donotreply", "billing", "reception", "frontdesk", "service",
    "jobs", "careers", "hr", "webmaster", "postmaster",
}


def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def apify_request(method, url, apify_key, max_retries=4, **kwargs):
    """HTTP request with exponential backoff."""
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, timeout=60,
                                    params={"token": apify_key, **kwargs.pop("params", {})},
                                    **kwargs)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                print(f"    API error {resp.status_code}: {resp.text[:200]}")
                return None
            return resp
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"    Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"    Failed after {max_retries} attempts: {e}")
    return None


def scrape_google_maps(apify_key, search_queries, location, max_per_query=20, dry_run=False):
    """Scrape Google Maps for HVAC businesses in a location."""
    all_results = []

    for query in search_queries:
        search_term = f"{query} in {location}"
        print(f"  Scraping: {search_term}")

        if dry_run:
            print(f"    [DRY RUN] Would search for ~{max_per_query} results")
            continue

        # Start actor run
        run_url = f"{APIFY_BASE}/acts/{GOOGLE_MAPS_ACTOR}/runs"
        run_input = {
            "searchStringsArray": [search_term],
            "maxCrawledPlacesPerSearch": max_per_query,
            "language": "en",
            "maxImages": 0,
            "maxReviews": 0,
            "includeWebResults": False,
        }

        resp = apify_request("POST", run_url, apify_key, json=run_input)
        if not resp:
            continue

        run_data = resp.json()
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            print(f"    Failed to start run")
            continue

        # Poll for completion (up to 3 minutes)
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        completed = False
        for _ in range(36):
            time.sleep(5)
            s = apify_request("GET", status_url, apify_key)
            if not s:
                break
            status = s.json().get("data", {}).get("status", "")
            if status == "SUCCEEDED":
                completed = True
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"    Run {status}")
                break

        if not completed:
            continue

        # Fetch results
        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            continue

        items_resp = apify_request("GET", f"{APIFY_BASE}/datasets/{dataset_id}/items",
                                   apify_key, params={"format": "json"})
        if not items_resp:
            continue

        items = items_resp.json()
        if not isinstance(items, list):
            continue

        for item in items:
            name = (item.get("title") or "").strip()
            phone = (item.get("phone") or "").strip()
            website = (item.get("website") or item.get("url") or "").strip()
            address = (item.get("address") or "").strip()
            rating = item.get("totalScore") or 0
            reviews = item.get("reviewsCount") or 0
            category = (item.get("categoryName") or "").strip()

            if not name or not phone:
                continue

            # Clean phone
            phone_clean = re.sub(r'[^\d+]', '', phone)
            if len(phone_clean) < 10:
                continue

            all_results.append({
                "business_name": name,
                "phone": phone,
                "website": website,
                "address": address,
                "city": location,
                "rating": rating,
                "reviews": reviews,
                "category": category,
            })

        print(f"    Got {len(items)} results, {len(all_results)} total with phone")
        time.sleep(1)

    return all_results


def extract_emails_from_websites(apify_key, businesses, dry_run=False):
    """Batch scrape websites for email addresses."""
    if not businesses or dry_run:
        return businesses

    # Collect URLs
    urls = []
    url_to_biz = {}
    for biz in businesses:
        website = biz.get("website", "")
        if not website:
            continue
        if not website.startswith("http"):
            website = "https://" + website
        website = re.sub(r'\?.*$', '', website)  # Strip query params
        domain = re.sub(r'https?://(www\.)?', '', website).split("/")[0].lower()
        url_to_biz[domain] = biz
        urls.append(website)
        # Also check contact page
        urls.append(website.rstrip("/") + "/contact")

    if not urls:
        return businesses

    print(f"\n  Enriching emails from {len(url_to_biz)} websites...")

    # Process in batches of 100 URLs
    batch_size = 100
    all_contacts = {}

    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        batch_num = i // batch_size + 1
        total_batches = (len(urls) - 1) // batch_size + 1
        print(f"    Email scrape batch {batch_num}/{total_batches} ({len(batch)} URLs)...")

        run_url = f"{APIFY_BASE}/acts/{CONTACT_SCRAPER_ACTOR}/runs"
        run_input = {
            "startUrls": [{"url": u} for u in batch],
            "maxRequestsPerStartUrl": 2,
        }

        resp = apify_request("POST", run_url, apify_key, json=run_input)
        if not resp:
            continue

        run_data = resp.json()
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            continue

        # Poll (up to 5 min)
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        completed = False
        for _ in range(60):
            time.sleep(5)
            s = apify_request("GET", status_url, apify_key)
            if not s:
                break
            status = s.json().get("data", {}).get("status", "")
            if status == "SUCCEEDED":
                completed = True
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"    Batch {batch_num} {status}")
                break

        if not completed:
            continue

        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            continue

        items_resp = apify_request("GET", f"{APIFY_BASE}/datasets/{dataset_id}/items",
                                   apify_key, params={"format": "json"})
        if not items_resp:
            continue

        items = items_resp.json()
        if not isinstance(items, list):
            continue

        for item in items:
            url_str = item.get("url", "")
            domain = re.sub(r'https?://(www\.)?', '', url_str).split("/")[0].lower()
            emails = item.get("emails", [])
            if isinstance(emails, list) and emails:
                if domain not in all_contacts:
                    all_contacts[domain] = []
                all_contacts[domain].extend(emails)

        time.sleep(2)

    # Merge emails back into businesses
    enriched_count = 0
    for biz in businesses:
        website = biz.get("website", "")
        if not website:
            continue
        domain = re.sub(r'https?://(www\.)?', '', website).split("/")[0].lower()

        emails = all_contacts.get(domain, [])
        if not emails:
            continue

        # Score and pick best email
        scored = []
        for e in set(emails):
            e = e.lower().strip()
            if "@" not in e:
                continue
            local = e.split("@")[0]
            email_domain = e.split("@")[1]

            if email_domain in JUNK_EMAIL_DOMAINS:
                continue
            if any(e.endswith(ext) for ext in [".png", ".jpg", ".gif", ".svg", ".css", ".js"]):
                continue

            score = 10
            # Domain match
            if email_domain == domain:
                score += 50
            # Personal name patterns
            if "." in local and local.split(".")[0].isalpha():
                score += 30
            elif local.isalpha() and len(local) > 2 and local not in GENERIC_PREFIXES:
                score += 20
            # Generic penalty
            if local in GENERIC_PREFIXES:
                score -= 20

            scored.append((e, score))

        if scored:
            scored.sort(key=lambda x: x[1], reverse=True)
            biz["email"] = scored[0][0]
            enriched_count += 1

    print(f"    Enriched {enriched_count}/{len(businesses)} with emails")
    return businesses


def deduplicate(businesses):
    """Dedup by phone number and business name."""
    seen_phones = set()
    seen_names = set()
    unique = []

    for biz in businesses:
        phone = re.sub(r'[^\d]', '', biz.get("phone", ""))
        name_key = biz.get("business_name", "").lower().strip()

        if phone in seen_phones:
            continue
        if name_key in seen_names:
            continue

        seen_phones.add(phone)
        seen_names.add(name_key)
        unique.append(biz)

    return unique


def score_lead(biz):
    """Score lead quality for cold calling prioritization. Higher = better."""
    score = 0

    # Has phone (required for cold calling)
    if biz.get("phone"):
        score += 50

    # Has email (bonus for follow-up)
    if biz.get("email"):
        score += 20

    # Has website (real business)
    if biz.get("website"):
        score += 10

    # Google reviews signal established business
    reviews = biz.get("reviews", 0)
    if reviews >= 100:
        score += 20
    elif reviews >= 50:
        score += 15
    elif reviews >= 20:
        score += 10
    elif reviews >= 5:
        score += 5

    # Rating quality
    rating = biz.get("rating", 0)
    if rating and rating >= 4.5:
        score += 10
    elif rating and rating >= 4.0:
        score += 5

    # HVAC-specific category boost
    category = biz.get("category", "").lower()
    hvac_keywords = ["hvac", "heating", "cooling", "air conditioning", "furnace", "ac "]
    if any(k in category for k in hvac_keywords):
        score += 10

    return score


def export_csv(businesses, filename):
    """Export cold-call-ready CSV."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)

    fieldnames = [
        "business_name", "phone", "email", "website", "address", "city",
        "rating", "reviews", "category", "lead_score",
    ]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for biz in businesses:
            writer.writerow(biz)

    print(f"\n  Exported {len(businesses)} leads to {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="HVAC Lead Scraper — Cold Calling Leads via Apify")
    parser.add_argument("--target", type=int, default=350, help="Target number of leads (default: 350)")
    parser.add_argument("--max-per-query", type=int, default=15, help="Max results per search query (default: 15)")
    parser.add_argument("--enrich-emails", action="store_true", default=True, help="Scrape websites for emails")
    parser.add_argument("--no-enrich", action="store_true", help="Skip email enrichment")
    parser.add_argument("--dry-run", action="store_true", help="Preview without API calls")
    args = parser.parse_args()

    config = load_config()
    apify_key = config.get("apify_api_key", "")
    if not apify_key:
        print("Error: No apify_api_key in config.json")
        sys.exit(1)

    print("=" * 60)
    print(f"  HVAC LEAD SCRAPER — TARGET: {args.target} COLD CALLING LEADS")
    print("=" * 60)
    print(f"  Queries: {len(HVAC_QUERIES)}")
    print(f"  Locations: {len(LOCATIONS)}")
    print(f"  Max per query: {args.max_per_query}")
    print()

    all_businesses = []
    start_time = time.time()

    # Scrape across locations, rotating queries
    query_idx = 0
    for location in LOCATIONS:
        if len(all_businesses) >= args.target * 1.5:  # Overshoot for dedup loss
            break

        # Use 2 queries per location for variety
        queries = [HVAC_QUERIES[query_idx % len(HVAC_QUERIES)],
                   HVAC_QUERIES[(query_idx + 1) % len(HVAC_QUERIES)]]
        query_idx += 2

        print(f"\n--- {location} ({len(all_businesses)} leads so far) ---")
        results = scrape_google_maps(apify_key, queries, location,
                                     max_per_query=args.max_per_query,
                                     dry_run=args.dry_run)
        all_businesses.extend(results)

    print(f"\n\n{'=' * 60}")
    print(f"  RAW RESULTS: {len(all_businesses)} businesses with phone numbers")

    # Dedup
    unique = deduplicate(all_businesses)
    print(f"  AFTER DEDUP: {len(unique)} unique businesses")

    # Enrich emails
    if not args.no_enrich and not args.dry_run:
        unique = extract_emails_from_websites(apify_key, unique, dry_run=args.dry_run)

    # Score leads
    for biz in unique:
        biz["lead_score"] = score_lead(biz)

    # Sort by score (best leads first)
    unique.sort(key=lambda x: x.get("lead_score", 0), reverse=True)

    # Trim to target
    final = unique[:args.target]

    # Stats
    elapsed = time.time() - start_time
    with_email = sum(1 for b in final if b.get("email"))
    with_website = sum(1 for b in final if b.get("website"))
    avg_score = sum(b.get("lead_score", 0) for b in final) / max(1, len(final))

    print(f"\n{'=' * 60}")
    print(f"  FINAL RESULTS")
    print(f"{'=' * 60}")
    print(f"  Total leads: {len(final)}")
    print(f"  With phone: {len(final)} (100%)")
    print(f"  With email: {with_email} ({with_email * 100 // max(1, len(final))}%)")
    print(f"  With website: {with_website} ({with_website * 100 // max(1, len(final))}%)")
    print(f"  Avg lead score: {avg_score:.0f}/100")
    print(f"  Time: {elapsed:.0f}s")

    # Export
    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"hvac_cold_call_leads_{timestamp}.csv"
    export_csv(final, filename)

    # Also overwrite the main file for easy access
    export_csv(final, "hvac_leads_clay.csv")

    print(f"\n  Done! {len(final)} HVAC cold calling leads ready.")
    print(f"  Top 5 leads:")
    for i, b in enumerate(final[:5], 1):
        print(f"    {i}. {b['business_name']} | {b['phone']} | {b.get('email', 'no email')} | Score: {b['lead_score']}")


if __name__ == "__main__":
    main()
