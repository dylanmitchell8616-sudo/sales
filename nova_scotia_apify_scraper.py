#!/usr/bin/env python3
"""
Nova Scotia Lead Scraper via Apify Google Maps
================================================
Scrapes local business leads across all service niches in Nova Scotia
using Apify's Google Maps Scraper actor, then outputs a clean CSV
ready for campaign generation.

Usage:
    python nova_scotia_apify_scraper.py --api-key YOUR_APIFY_KEY
    python nova_scotia_apify_scraper.py --api-key YOUR_APIFY_KEY --dry-run
    python nova_scotia_apify_scraper.py --api-key YOUR_APIFY_KEY --niches "dental,hvac,roofing"
"""

import argparse
import csv
import json
import logging
import os
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ─── Nova Scotia regions to search ───────────────────────────────────────────
NS_REGIONS = [
    "Halifax, Nova Scotia",
    "Dartmouth, Nova Scotia",
    "Sydney, Nova Scotia",
    "Truro, Nova Scotia",
    "New Glasgow, Nova Scotia",
    "Glace Bay, Nova Scotia",
    "Kentville, Nova Scotia",
    "Amherst, Nova Scotia",
    "Bridgewater, Nova Scotia",
    "Yarmouth, Nova Scotia",
    "Antigonish, Nova Scotia",
    "Wolfville, Nova Scotia",
    "Windsor, Nova Scotia",
    "Stellarton, Nova Scotia",
    "Bedford, Nova Scotia",
    "Lower Sackville, Nova Scotia",
]

# ─── All niches to target ────────────────────────────────────────────────────
# Service mapping logic:
#   inbound  = high call volume, appointment-based, loses $ from missed calls
#   outbound = runs ads / has leads to follow up / dormant CRM contacts / estimates
#   recruiting = high turnover, always hiring, staffing-dependent
NICHES = {
    # ── Healthcare / Wellness ─────────────────────────────────────────────────
    "dental": {
        "queries": ["dentist", "dental office", "dental clinic"],
        "services": ["inbound", "outbound"],
        "label": "Dental",
    },
    "med_spa": {
        "queries": ["med spa", "medical spa", "aesthetic clinic", "medspa"],
        "services": ["inbound", "outbound"],
        "label": "Med Spa",
    },
    "chiropractic": {
        "queries": ["chiropractor", "chiropractic clinic"],
        "services": ["inbound"],
        "label": "Chiropractic",
    },
    "physiotherapy": {
        "queries": ["physiotherapy", "physical therapy clinic", "physio"],
        "services": ["inbound"],
        "label": "Physiotherapy",
    },
    "optometry": {
        "queries": ["optometrist", "eye clinic", "optometry"],
        "services": ["inbound"],
        "label": "Optometry",
    },
    "veterinary": {
        "queries": ["veterinarian", "vet clinic", "animal hospital"],
        "services": ["inbound"],
        "label": "Veterinary",
    },
    "pharmacy": {
        "queries": ["pharmacy", "drug store"],
        "services": ["inbound"],
        "label": "Pharmacy",
    },
    "wellness": {
        "queries": ["wellness center", "IV clinic", "naturopath"],
        "services": ["inbound", "outbound"],
        "label": "Wellness",
    },
    "mental_health": {
        "queries": ["therapist", "counseling clinic", "psychologist office", "mental health clinic"],
        "services": ["inbound"],
        "label": "Mental Health",
    },
    # ── Beauty / Personal Care ────────────────────────────────────────────────
    "salon": {
        "queries": ["hair salon", "barbershop", "beauty salon"],
        "services": ["inbound"],
        "label": "Salon & Barbershop",
    },
    "spa": {
        "queries": ["spa", "massage therapy", "day spa"],
        "services": ["inbound", "outbound"],
        "label": "Spa & Massage",
    },
    # ── Home Services / Trades ────────────────────────────────────────────────
    "hvac": {
        "queries": ["HVAC", "heating and cooling", "furnace repair"],
        "services": ["inbound", "outbound"],
        "label": "HVAC",
    },
    "plumbing": {
        "queries": ["plumber", "plumbing company"],
        "services": ["inbound", "outbound"],
        "label": "Plumbing",
    },
    "electrical": {
        "queries": ["electrician", "electrical contractor"],
        "services": ["inbound", "outbound"],
        "label": "Electrical",
    },
    "roofing": {
        "queries": ["roofing company", "roofer"],
        "services": ["inbound", "outbound"],
        "label": "Roofing",
    },
    "landscaping": {
        "queries": ["landscaping company", "lawn care"],
        "services": ["inbound", "outbound"],
        "label": "Landscaping",
    },
    "cleaning": {
        "queries": ["cleaning company", "janitorial service", "maid service"],
        "services": ["inbound", "recruiting"],
        "label": "Cleaning",
    },
    "pest_control": {
        "queries": ["pest control", "exterminator"],
        "services": ["inbound", "outbound"],
        "label": "Pest Control",
    },
    # ── Professional Services ─────────────────────────────────────────────────
    "real_estate": {
        "queries": ["real estate agency", "realtor office", "property management"],
        "services": ["inbound", "outbound"],
        "label": "Real Estate",
    },
    "insurance": {
        "queries": ["insurance agency", "insurance broker"],
        "services": ["inbound", "outbound"],
        "label": "Insurance",
    },
    "law_firm": {
        "queries": ["law firm", "lawyer", "legal office"],
        "services": ["inbound"],
        "label": "Law Firm",
    },
    "accounting": {
        "queries": ["accounting firm", "accountant", "CPA", "bookkeeper"],
        "services": ["inbound"],
        "label": "Accounting",
    },
    # ── Automotive ─────────────────────────────────────────────────────────────
    "auto_repair": {
        "queries": ["auto repair", "mechanic", "auto body shop"],
        "services": ["inbound", "outbound"],
        "label": "Auto Repair",
    },
    "car_dealership": {
        "queries": ["car dealership", "used car dealer", "auto dealer"],
        "services": ["inbound", "outbound", "recruiting"],
        "label": "Car Dealership",
    },
    # ── Fitness ───────────────────────────────────────────────────────────────
    "fitness": {
        "queries": ["gym", "fitness center", "CrossFit", "yoga studio"],
        "services": ["inbound", "outbound"],
        "label": "Fitness & Gym",
    },
    # ── Home Care / Staffing (recruiting-heavy) ──────────────────────────────
    "homecare": {
        "queries": ["home care agency", "senior care", "home health"],
        "services": ["inbound", "recruiting"],
        "label": "Home Care",
    },
    "staffing": {
        "queries": ["staffing agency", "temp agency", "employment agency"],
        "services": ["recruiting"],
        "label": "Staffing Agency",
    },
    # ── Restaurants / Hospitality ─────────────────────────────────────────────
    "restaurant": {
        "queries": ["restaurant", "catering company"],
        "services": ["recruiting"],
        "label": "Restaurant & Catering",
    },
    "hotel": {
        "queries": ["hotel", "inn", "bed and breakfast"],
        "services": ["inbound", "recruiting"],
        "label": "Hotel & Hospitality",
    },
}

# Apify actor ID for Google Maps Scraper (Compass)
APIFY_ACTOR_ID = "compass/crawler-google-places"
APIFY_BASE_URL = "https://api.apify.com/v2"


def run_apify_scrape(api_key: str, search_queries: list, max_results: int = 100) -> list:
    """Run the Apify Google Maps scraper and return results."""
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    # Build the actor input
    actor_input = {
        "searchStringsArray": search_queries,
        "maxCrawledPlacesPerSearch": max_results,
        "language": "en",
        "deeperCityScrape": False,
        "onePerDomain": False,
    }

    # Start the actor run
    url = f"{APIFY_BASE_URL}/acts/{APIFY_ACTOR_ID}/runs"
    logging.info(f"  Starting Apify run with {len(search_queries)} queries...")

    resp = requests.post(url, headers=headers, json=actor_input, timeout=60)
    if resp.status_code != 201:
        logging.error(f"  Failed to start actor: {resp.status_code} {resp.text}")
        return []

    run_data = resp.json().get("data", {})
    run_id = run_data.get("id")
    logging.info(f"  Actor run started: {run_id}")

    # Poll for completion
    status_url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
    for attempt in range(120):  # up to 10 minutes
        time.sleep(5)
        status_resp = requests.get(status_url, headers=headers, timeout=30)
        status = status_resp.json().get("data", {}).get("status")
        if status == "SUCCEEDED":
            logging.info(f"  Run completed successfully")
            break
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            logging.error(f"  Run failed with status: {status}")
            return []
    else:
        logging.error("  Run timed out after 10 minutes")
        return []

    # Fetch results from dataset
    dataset_id = status_resp.json().get("data", {}).get("defaultDatasetId")
    results_url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items?format=json&limit=10000"
    results_resp = requests.get(results_url, headers=headers, timeout=60)

    if results_resp.status_code != 200:
        logging.error(f"  Failed to fetch results: {results_resp.status_code}")
        return []

    items = results_resp.json()
    logging.info(f"  Retrieved {len(items)} places")
    return items


def parse_apify_result(item: dict, niche: str, niche_label: str, services: list = None) -> dict:
    """Parse a single Apify Google Maps result into a lead record."""
    # Extract owner/contact name from the place
    title = item.get("title", "")
    phone = item.get("phone", "")
    website = item.get("website", "")
    address = item.get("address", "")
    city = item.get("city", "")
    rating = item.get("totalScore", 0)
    reviews = item.get("reviewsCount", 0)
    category = item.get("categoryName", "")
    place_url = item.get("url", "")

    # Clean phone
    if phone:
        phone = phone.strip()

    # Extract domain from website
    domain = ""
    if website:
        domain = website.replace("https://", "").replace("http://", "").split("/")[0]

    return {
        "company_name": title,
        "phone": phone,
        "website": website,
        "domain": domain,
        "address": address,
        "city": city or "",
        "province": "Nova Scotia",
        "rating": rating,
        "reviews": reviews,
        "category": category,
        "niche": niche,
        "niche_label": niche_label,
        "services": ",".join(services or []),
        "google_maps_url": place_url,
    }


def deduplicate_leads(leads: list) -> list:
    """Deduplicate by domain or company name."""
    seen_domains = set()
    seen_names = set()
    unique = []

    for lead in leads:
        domain = lead.get("domain", "").lower().strip()
        name = lead.get("company_name", "").lower().strip()

        # Skip if we've seen this domain (and it's not empty)
        if domain and domain in seen_domains:
            continue
        # Skip if exact name match
        if name and name in seen_names:
            continue

        if domain:
            seen_domains.add(domain)
        if name:
            seen_names.add(name)
        unique.append(lead)

    return unique


def save_leads_csv(leads: list, output_path: str):
    """Save leads to CSV."""
    if not leads:
        logging.warning("No leads to save")
        return

    fieldnames = [
        "company_name", "phone", "website", "domain", "address", "city",
        "province", "rating", "reviews", "category", "niche", "niche_label",
        "services", "google_maps_url",
    ]

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(leads)

    logging.info(f"Saved {len(leads)} leads to {output_path}")


def estimate_cost(niches_to_run: dict, regions: list, max_per_search: int) -> dict:
    """Estimate Apify cost before running."""
    total_queries = 0
    for niche_key, niche_data in niches_to_run.items():
        queries_per_niche = len(niche_data["queries"]) * len(regions)
        total_queries += queries_per_niche

    # Apify pricing: $0.004 per place + $0.007 per run start
    estimated_places = total_queries * max_per_search
    cost_per_place = 0.004
    cost_per_run = 0.007

    # We batch all queries for a niche into one run
    num_runs = len(niches_to_run)
    estimated_cost = (estimated_places * cost_per_place) + (num_runs * cost_per_run)

    return {
        "total_niches": len(niches_to_run),
        "total_queries": total_queries,
        "estimated_places": estimated_places,
        "num_runs": num_runs,
        "estimated_cost_usd": round(estimated_cost, 2),
    }


def main():
    parser = argparse.ArgumentParser(description="Nova Scotia Lead Scraper via Apify")
    parser.add_argument("--api-key", required=True, help="Apify API key")
    parser.add_argument("--dry-run", action="store_true", help="Estimate cost only, don't scrape")
    parser.add_argument("--niches", default="all", help="Comma-separated niches to scrape (default: all)")
    parser.add_argument("--max-per-search", type=int, default=100, help="Max results per search query (default: 100)")
    parser.add_argument("--regions", default="all", help="Comma-separated regions (default: all)")
    args = parser.parse_args()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # Filter niches
    if args.niches == "all":
        niches_to_run = NICHES
    else:
        selected = [n.strip().lower() for n in args.niches.split(",")]
        niches_to_run = {k: v for k, v in NICHES.items() if k in selected}
        if not niches_to_run:
            logging.error(f"No matching niches found. Available: {', '.join(NICHES.keys())}")
            sys.exit(1)

    # Filter regions
    if args.regions == "all":
        regions = NS_REGIONS
    else:
        selected_regions = [r.strip() for r in args.regions.split(",")]
        regions = [r for r in NS_REGIONS if any(sr.lower() in r.lower() for sr in selected_regions)]
        if not regions:
            regions = [f"{r}, Nova Scotia" for r in selected_regions]

    # Cost estimate
    estimate = estimate_cost(niches_to_run, regions, args.max_per_search)
    logging.info("=" * 60)
    logging.info("NOVA SCOTIA LEAD SCRAPE — COST ESTIMATE")
    logging.info("=" * 60)
    logging.info(f"  Niches:            {estimate['total_niches']}")
    logging.info(f"  Search queries:    {estimate['total_queries']}")
    logging.info(f"  Est. places:       {estimate['estimated_places']:,}")
    logging.info(f"  Apify runs:        {estimate['num_runs']}")
    logging.info(f"  Estimated cost:    ${estimate['estimated_cost_usd']:.2f} USD")
    logging.info("=" * 60)

    if args.dry_run:
        logging.info("DRY RUN — no scraping performed")
        # Save estimate
        estimate_path = os.path.join(OUTPUT_DIR, "ns_scrape_estimate.json")
        with open(estimate_path, "w") as f:
            json.dump(estimate, f, indent=2)
        logging.info(f"Estimate saved to {estimate_path}")
        return

    # Run scrapes per niche
    all_leads = []
    for niche_key, niche_data in niches_to_run.items():
        logging.info(f"\n{'─' * 40}")
        logging.info(f"Scraping: {niche_data['label']}")
        logging.info(f"{'─' * 40}")

        # Build search queries: each query × each region
        search_queries = []
        for query in niche_data["queries"]:
            for region in regions:
                search_queries.append(f"{query} in {region}")

        results = run_apify_scrape(args.api_key, search_queries, args.max_per_search)

        for item in results:
            lead = parse_apify_result(item, niche_key, niche_data["label"], niche_data["services"])
            if lead["company_name"]:  # skip empty results
                all_leads.append(lead)

        logging.info(f"  {niche_data['label']}: {len(results)} raw results")

    # Deduplicate
    unique_leads = deduplicate_leads(all_leads)
    logging.info(f"\nTotal raw: {len(all_leads)} → Deduplicated: {len(unique_leads)}")

    # Save master CSV
    master_path = os.path.join(OUTPUT_DIR, "ns_leads_all.csv")
    save_leads_csv(unique_leads, master_path)

    # Save per-niche CSVs
    for niche_key in niches_to_run:
        niche_leads = [l for l in unique_leads if l["niche"] == niche_key]
        if niche_leads:
            niche_path = os.path.join(OUTPUT_DIR, f"ns_leads_{niche_key}.csv")
            save_leads_csv(niche_leads, niche_path)

    # Summary
    logging.info("\n" + "=" * 60)
    logging.info("SCRAPE COMPLETE")
    logging.info("=" * 60)
    for niche_key, niche_data in niches_to_run.items():
        count = len([l for l in unique_leads if l["niche"] == niche_key])
        logging.info(f"  {niche_data['label']:25s} {count:>5} leads")
    logging.info(f"  {'TOTAL':25s} {len(unique_leads):>5} leads")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()
