#!/usr/bin/env python3
"""
Apify Lead Fallback Scraper
=============================
Fallback lead source when Instantly Supersearch isn't enough.
Scrapes Google Maps via Apify to find service businesses, then
enriches with contact info scraping.

Designed to plug into the lead scaling engine as a secondary source.

Usage:
    python apify_lead_fallback.py --niches "med spa,dental" --locations "Miami FL,Dallas TX"
    python apify_lead_fallback.py --niches "dental" --locations "Houston TX" --max-leads 50
    python apify_lead_fallback.py --enrich-only --input output/apify_raw_leads.csv
    python apify_lead_fallback.py --upload --campaign-id ABC123
    python apify_lead_fallback.py --dry-run
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CACHE_FILE = os.path.join(OUTPUT_DIR, "apify_fallback_cache.json")
PROCESSED_LEADS_PATH = os.path.join(OUTPUT_DIR, "processed_leads.json")

APIFY_BASE = "https://api.apify.com/v2"
INSTANTLY_BASE = "https://api.instantly.ai/api/v2"

# Apify actors
GOOGLE_MAPS_ACTOR = "compass/crawler-google-places"
CONTACT_SCRAPER_ACTOR = "vdrmota/contact-info-scraper"

# Search query templates per niche
NICHE_QUERIES = {
    "med_spa": ["med spa", "medical spa", "medspa", "aesthetics clinic"],
    "dental": ["dental office", "dentist", "dental clinic", "family dentistry"],
    "wellness": ["wellness center", "iv therapy clinic", "holistic wellness"],
    "chiropractic": ["chiropractor", "chiropractic clinic"],
    "dermatology": ["dermatology clinic", "dermatologist"],
    "plastic_surgery": ["plastic surgery", "cosmetic surgery clinic"],
    "veterinary": ["veterinary clinic", "vet hospital", "animal hospital"],
    "physical_therapy": ["physical therapy clinic", "PT clinic"],
    "optometry": ["optometrist", "eye care clinic", "vision center"],
    "orthodontics": ["orthodontist", "braces clinic", "orthodontics"],
    "hvac": ["hvac company", "heating and air conditioning", "ac repair", "hvac contractor", "furnace repair"],
}

GENERIC_EMAIL_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "noreply", "no-reply",
    "donotreply", "do-not-reply", "billing", "reception", "frontdesk",
}

JUNK_DOMAINS = {
    "gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com",
    "godaddy.com", "wix.com", "squarespace.com", "example.com",
    "sentry.io", "facebook.com", "instagram.com",
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def api_request_with_retry(method, url, max_retries=4, **kwargs):
    """HTTP request with exponential backoff."""
    for attempt in range(max_retries):
        try:
            resp = requests.request(method, url, timeout=30, **kwargs)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                print(f"  API error {resp.status_code}: {resp.text[:200]}")
                return None
            return resp
        except requests.exceptions.RequestException as e:
            if attempt < max_retries - 1:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after {max_retries} attempts: {e}")
    return None


def load_cache() -> dict:
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_cache(cache: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def load_processed_leads() -> set:
    if os.path.exists(PROCESSED_LEADS_PATH):
        try:
            with open(PROCESSED_LEADS_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return set(data.get("emails", []))
            return set(data)
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def score_email(email: str, domain: str) -> int:
    """Score email quality. Higher = better."""
    if not email or "@" not in email:
        return 0
    local = email.split("@")[0].lower()
    email_domain = email.split("@")[1].lower()

    # Junk domains
    if email_domain in JUNK_DOMAINS:
        return 0

    score = 10  # base

    # Domain match with business
    if domain and email_domain == domain.lower():
        score += 50

    # Personal name patterns (first.last, first, flast)
    if "." in local and local.split(".")[0].isalpha():
        score += 30
    elif local.isalpha() and len(local) > 2 and local not in GENERIC_EMAIL_PREFIXES:
        score += 20

    # Generic prefixes get low score
    if local in GENERIC_EMAIL_PREFIXES:
        score = max(score - 30, 5)

    # Role-based
    role_scores = {"info": 10, "contact": 9, "office": 8, "hello": 7}
    if local in role_scores:
        score = role_scores[local]

    return score


def scrape_google_maps(apify_key: str, queries: list, location: str,
                        max_results: int = 20, dry_run: bool = False) -> list:
    """
    Scrape Google Maps for businesses using Apify.
    Returns list of business data dicts.
    """
    all_results = []
    cache = load_cache()

    for query in queries:
        search_term = f"{query} in {location}"
        cache_key = search_term.lower().replace(" ", "_")

        if cache_key in cache:
            print(f"  [CACHED] {search_term}: {len(cache[cache_key])} results")
            all_results.extend(cache[cache_key])
            continue

        print(f"  Scraping: {search_term} (max {max_results})...")

        if dry_run:
            print(f"  [DRY RUN] Would scrape Google Maps for: {search_term}")
            continue

        # Start Apify actor run
        run_url = f"{APIFY_BASE}/acts/{GOOGLE_MAPS_ACTOR}/runs"
        run_input = {
            "searchStringsArray": [search_term],
            "maxCrawledPlacesPerSearch": max_results,
            "language": "en",
            "maxImages": 0,
            "maxReviews": 0,
            "includeWebResults": False,
        }

        resp = api_request_with_retry("POST", run_url, params={"token": apify_key},
                                       json=run_input)
        if not resp:
            continue

        run_data = resp.json()
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            print(f"  Failed to start actor run")
            continue

        # Poll for completion
        print(f"  Waiting for run {run_id}...")
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        for _ in range(60):  # max 5 minutes
            time.sleep(5)
            status_resp = api_request_with_retry("GET", status_url,
                                                  params={"token": apify_key})
            if not status_resp:
                break
            status = status_resp.json().get("data", {}).get("status", "")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                print(f"  Run {status}")
                break
        else:
            print(f"  Run timed out")
            continue

        # Fetch results
        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            continue

        items_url = f"{APIFY_BASE}/datasets/{dataset_id}/items"
        items_resp = api_request_with_retry("GET", items_url,
                                             params={"token": apify_key, "format": "json"})
        if not items_resp:
            continue

        items = items_resp.json()
        if not isinstance(items, list):
            items = []

        # Parse results
        parsed = []
        for item in items:
            biz = {
                "business_name": item.get("title", ""),
                "address": item.get("address", ""),
                "phone": item.get("phone", ""),
                "website": item.get("website", item.get("url", "")),
                "rating": item.get("totalScore", ""),
                "reviews_count": item.get("reviewsCount", 0),
                "category": item.get("categoryName", ""),
                "location": location,
                "source": "apify_google_maps",
            }
            if biz["business_name"] and biz["website"]:
                parsed.append(biz)

        cache[cache_key] = parsed
        save_cache(cache)
        all_results.extend(parsed)
        print(f"  Found {len(parsed)} businesses")
        time.sleep(2)  # Rate limit between queries

    return all_results


def enrich_with_contacts(apify_key: str, businesses: list,
                          dry_run: bool = False) -> list:
    """
    Scrape contact info (emails) from business websites using Apify.
    Returns enriched business list with email fields.
    """
    if not businesses:
        return []

    urls = []
    for biz in businesses:
        website = biz.get("website", "")
        if website:
            if not website.startswith("http"):
                website = "https://" + website
            urls.append(website)
            # Also check common contact pages
            for path in ["/contact", "/about", "/team"]:
                urls.append(website.rstrip("/") + path)

    if not urls:
        return businesses

    print(f"\n  Enriching {len(businesses)} businesses ({len(urls)} URLs)...")

    if dry_run:
        print(f"  [DRY RUN] Would scrape {len(urls)} URLs for contact info")
        return businesses

    # Batch URLs (Apify contact scraper)
    batch_size = 50
    all_contacts = {}

    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        print(f"  Contact scrape batch {i // batch_size + 1}/{(len(urls) - 1) // batch_size + 1}...")

        run_url = f"{APIFY_BASE}/acts/{CONTACT_SCRAPER_ACTOR}/runs"
        run_input = {
            "startUrls": [{"url": u} for u in batch],
            "maxRequestsPerStartUrl": 3,
        }

        resp = api_request_with_retry("POST", run_url, params={"token": apify_key},
                                       json=run_input)
        if not resp:
            continue

        run_data = resp.json()
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            continue

        # Poll
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        for _ in range(60):
            time.sleep(5)
            status_resp = api_request_with_retry("GET", status_url,
                                                  params={"token": apify_key})
            if not status_resp:
                break
            status = status_resp.json().get("data", {}).get("status", "")
            if status == "SUCCEEDED":
                break
            if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                break

        # Fetch results
        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            continue

        items_resp = api_request_with_retry("GET",
                                             f"{APIFY_BASE}/datasets/{dataset_id}/items",
                                             params={"token": apify_key, "format": "json"})
        if not items_resp:
            continue

        items = items_resp.json()
        if not isinstance(items, list):
            continue

        for item in items:
            domain = ""
            url_str = item.get("url", "")
            if url_str:
                domain = re.sub(r'https?://(www\.)?', '', url_str).split("/")[0].lower()

            emails = item.get("emails", [])
            if isinstance(emails, list) and emails:
                all_contacts[domain] = emails

        time.sleep(2)

    # Merge contacts back into businesses
    enriched = []
    for biz in businesses:
        website = biz.get("website", "")
        domain = re.sub(r'https?://(www\.)?', '', website).split("/")[0].lower() if website else ""

        emails = all_contacts.get(domain, [])
        if emails:
            # Score and pick best email
            scored = [(e, score_email(e, domain)) for e in emails]
            scored.sort(key=lambda x: x[1], reverse=True)
            best_email = scored[0][0]
            biz["email"] = best_email
            biz["all_emails"] = [e for e, _ in scored[:3]]
            biz["email_score"] = scored[0][1]
        else:
            biz["email"] = ""
            biz["all_emails"] = []
            biz["email_score"] = 0

        enriched.append(biz)

    with_email = sum(1 for b in enriched if b.get("email"))
    print(f"  Enriched: {with_email}/{len(enriched)} have emails")

    return enriched


def format_for_instantly(businesses: list) -> list:
    """Convert scraped businesses to Instantly lead format."""
    leads = []
    for biz in businesses:
        email = biz.get("email", "")
        if not email:
            continue

        # Try to extract first/last name from email
        local = email.split("@")[0]
        first_name, last_name = "", ""
        if "." in local:
            parts = local.split(".")
            first_name = parts[0].capitalize()
            last_name = parts[-1].capitalize()

        leads.append({
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "company_name": biz.get("business_name", ""),
            "phone": biz.get("phone", ""),
            "website": biz.get("website", ""),
            "custom_variables": {
                "business_name": biz.get("business_name", ""),
                "category": biz.get("category", ""),
                "rating": str(biz.get("rating", "")),
                "reviews_count": str(biz.get("reviews_count", "")),
                "city": biz.get("location", ""),
                "source": "apify_fallback",
            },
        })

    return leads


def upload_to_instantly(instantly_key: str, campaign_id: str, leads: list,
                         dry_run: bool = False) -> int:
    """Upload leads to Instantly campaign."""
    if not leads:
        return 0

    print(f"\n  Uploading {len(leads)} leads to Instantly campaign {campaign_id}...")

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(leads)} leads")
        return 0

    headers = {
        "Authorization": f"Bearer {instantly_key}",
        "Content-Type": "application/json",
    }

    uploaded = 0
    batch_size = 50
    for i in range(0, len(leads), batch_size):
        batch = leads[i:i + batch_size]
        url = f"{INSTANTLY_BASE}/campaigns/{campaign_id}/leads"

        resp = api_request_with_retry("POST", url, headers=headers,
                                       json={"leads": batch})
        if resp and resp.status_code < 400:
            uploaded += len(batch)
            print(f"  Batch {i // batch_size + 1}: {len(batch)} uploaded")
        time.sleep(1)

    print(f"  Total uploaded: {uploaded}/{len(leads)}")
    return uploaded


def export_csv(businesses: list, filename: str = "apify_fallback_leads.csv"):
    """Export leads to CSV."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["email", "business_name", "phone", "website", "category",
                   "rating", "reviews_count", "location", "email_score", "source"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for biz in businesses:
            if biz.get("email"):
                writer.writerow(biz)

    with_email = sum(1 for b in businesses if b.get("email"))
    print(f"\n  Exported {with_email} leads to {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Apify Lead Fallback Scraper")
    parser.add_argument("--apify-key", help="Apify API key (or uses config.json)")
    parser.add_argument("--instantly-key", help="Instantly API key (or uses config.json)")
    parser.add_argument("--niches", required=False, help="Comma-separated niches (e.g. 'dental,med_spa')")
    parser.add_argument("--locations", required=False, help="Comma-separated locations (e.g. 'Miami FL,Dallas TX')")
    parser.add_argument("--max-leads", type=int, default=20, help="Max leads per query (default: 20)")
    parser.add_argument("--enrich-only", action="store_true", help="Only run contact enrichment")
    parser.add_argument("--input", help="Input CSV for enrich-only mode")
    parser.add_argument("--upload", action="store_true", help="Upload results to Instantly")
    parser.add_argument("--campaign-id", help="Instantly campaign ID for upload")
    parser.add_argument("--export", action="store_true", help="Export to CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making API calls")
    args = parser.parse_args()

    config = load_config()
    apify_key = args.apify_key or config.get("apify_api_key", "")
    instantly_key = args.instantly_key or config.get("instantly_api_key", "")

    if not apify_key:
        print("Error: No Apify API key. Use --apify-key or set apify_api_key in config.json")
        sys.exit(1)

    # Parse niches
    if args.niches:
        niches = [n.strip().lower().replace(" ", "_") for n in args.niches.split(",")]
    else:
        niches = ["med_spa", "dental", "wellness"]

    # Parse locations
    if args.locations:
        locations = [l.strip() for l in args.locations.split(",")]
    else:
        locations = ["Miami FL", "Dallas TX", "Houston TX", "Phoenix AZ", "Los Angeles CA"]

    print(f"\n=== Apify Lead Fallback Scraper ===")
    print(f"  Niches: {', '.join(niches)}")
    print(f"  Locations: {', '.join(locations)}")
    print(f"  Max per query: {args.max_leads}")

    # Build search queries
    all_businesses = []
    existing_emails = load_processed_leads()

    for niche in niches:
        queries = NICHE_QUERIES.get(niche, [niche.replace("_", " ")])
        for location in locations:
            print(f"\n--- {niche} in {location} ---")
            results = scrape_google_maps(apify_key, queries[:2], location,
                                          max_results=args.max_leads,
                                          dry_run=args.dry_run)
            all_businesses.extend(results)

    print(f"\n  Total businesses scraped: {len(all_businesses)}")

    # Enrich with contact info
    if all_businesses and not args.dry_run:
        all_businesses = enrich_with_contacts(apify_key, all_businesses, dry_run=args.dry_run)

    # Dedup against existing leads
    new_businesses = []
    for biz in all_businesses:
        email = biz.get("email", "").lower()
        if email and email not in existing_emails:
            existing_emails.add(email)
            new_businesses.append(biz)

    print(f"  New (after dedup): {len(new_businesses)}")

    # Export
    if args.export or not args.upload:
        export_csv(new_businesses)

    # Upload to Instantly
    if args.upload and args.campaign_id and instantly_key:
        formatted = format_for_instantly(new_businesses)
        upload_to_instantly(instantly_key, args.campaign_id, formatted, dry_run=args.dry_run)

    print(f"\n=== Done ===")


if __name__ == "__main__":
    main()
