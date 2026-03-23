#!/usr/bin/env python3
"""
Scrape Indeed for HVAC companies hiring receptionists/dispatchers.
Saves raw company list for Apollo enrichment (no Google Maps).

Usage:
    python scrape_hiring_companies.py
    python scrape_hiring_companies.py --target 100 --cities 20
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests required. pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

APIFY_BASE = "https://api.apify.com/v2"
INDEED_ACTOR = "hMvNSpz3JnHgl5jkh"

HIRING_QUERIES = [
    "HVAC receptionist",
    "HVAC office manager",
    "HVAC customer service representative",
    "HVAC dispatcher",
    "heating and cooling receptionist",
    "air conditioning office admin",
    "plumbing receptionist",
    "plumbing dispatcher",
    "HVAC front desk",
    "HVAC call center",
]

# 60 cities — hot HVAC markets
CITIES = [
    "Phoenix, AZ", "Dallas, TX", "Houston, TX", "Miami, FL", "Atlanta, GA",
    "Las Vegas, NV", "Tampa, FL", "Austin, TX", "Nashville, TN", "Charlotte, NC",
    "Chicago, IL", "Denver, CO", "Orlando, FL", "San Antonio, TX", "Raleigh, NC",
    "Jacksonville, FL", "Indianapolis, IN", "Columbus, OH", "San Diego, CA",
    "Sacramento, CA", "Memphis, TN", "Oklahoma City, OK", "Tucson, AZ",
    "Birmingham, AL", "New Orleans, LA", "Knoxville, TN", "Greenville, SC",
    "Baton Rouge, LA", "Tulsa, OK", "Omaha, NE",
    "Fort Worth, TX", "St. Louis, MO", "Kansas City, MO", "Cincinnati, OH",
    "Pittsburgh, PA", "Louisville, KY", "Richmond, VA", "Virginia Beach, VA",
    "Albuquerque, NM", "Fresno, CA", "Bakersfield, CA", "El Paso, TX",
    "McAllen, TX", "Savannah, GA", "Charleston, SC", "Wichita, KS",
    "Des Moines, IA", "Little Rock, AR", "Mobile, AL", "Chattanooga, TN",
    "Lexington, KY", "Dayton, OH", "Akron, OH", "Lakeland, FL",
    "Cape Coral, FL", "Pensacola, FL", "Huntsville, AL", "Shreveport, LA",
    "Fayetteville, AR", "Colorado Springs, CO",
]

# Junk companies to filter out
JUNK_KEYWORDS = [
    "staffing", "temp agency", "manpower", "adecco", "kelly services", "robert half",
    "panera", "hotel", "marriott", "hilton", "hyatt", "mcdonald", "burger",
    "wendy", "chili", "applebee", "olive garden", "subway", "pizza",
    "walmart", "target", "amazon", "fedex", "ups", "usps",
    "university", "college", "school district", "hospital", "medical center",
    "dental", "orthodont", "veterinar", "insurance", "bank", "credit union",
    "real estate", "realty", "property management", "apartment",
    "church", "ymca", "goodwill", "salvation army", "non-profit",
    "spa", "salon", "nail", "beauty", "barber",
]

# Keywords that confirm HVAC-related company
HVAC_KEYWORDS = [
    "hvac", "heating", "cooling", "air condition", "furnace", "plumb",
    "mechanical", "refrigerat", "duct", "ventilat", "boiler",
    "comfort", "climate", "temp", "energy", "home service",
    "fire", "electric", "restoration", "roofing", "construction",
    "contractor", "maintenance", "repair", "service",
]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def run_apify_actor(apify_key, actor_id, run_input, timeout_mins=4):
    """Run an Apify actor and return results."""
    try:
        resp = requests.post(
            f"{APIFY_BASE}/acts/{actor_id}/runs",
            params={"token": apify_key},
            json=run_input,
            timeout=30,
        )
    except requests.exceptions.RequestException as e:
        print(f"    Network error: {e}")
        return []

    if resp.status_code not in (200, 201):
        print(f"    Error: {resp.status_code} {resp.text[:200]}")
        return []

    run_id = resp.json().get("data", {}).get("id")
    if not run_id:
        return []

    max_polls = timeout_mins * 12
    for _ in range(max_polls):
        time.sleep(5)
        try:
            sr = requests.get(
                f"{APIFY_BASE}/actor-runs/{run_id}",
                params={"token": apify_key},
                timeout=10,
            )
            status = sr.json().get("data", {}).get("status")
        except requests.exceptions.RequestException:
            continue

        if status == "SUCCEEDED":
            dataset_id = sr.json().get("data", {}).get("defaultDatasetId")
            try:
                items_resp = requests.get(
                    f"{APIFY_BASE}/datasets/{dataset_id}/items",
                    params={"token": apify_key, "limit": 200},
                    timeout=15,
                )
                items = items_resp.json()
                return items if isinstance(items, list) else []
            except requests.exceptions.RequestException:
                return []
        elif status in ("FAILED", "ABORTED", "TIMED-OUT"):
            print(f"    Actor run {status}")
            return []

    print("    Timed out")
    return []


def is_junk_company(company_name):
    """Filter out non-HVAC companies."""
    name_lower = company_name.lower()
    for junk in JUNK_KEYWORDS:
        if junk in name_lower:
            return True
    return False


def is_likely_hvac(company_name, job_title):
    """Check if company or job title suggests HVAC/trade."""
    combined = f"{company_name} {job_title}".lower()
    for kw in HVAC_KEYWORDS:
        if kw in combined:
            return True
    return False


def scrape_indeed(apify_key, cities, target):
    """Scrape Indeed for HVAC companies hiring receptionists."""
    companies = {}  # company_name -> info dict
    total_listings = 0

    for city in cities:
        if len(companies) >= target:
            break

        query = random.choice(HIRING_QUERIES)
        print(f"  [{len(companies)}/{target}] Indeed: '{query}' in {city}...")

        run_input = {
            "position": query,
            "location": city,
            "maxItems": 25,
            "parseCompanyDetails": False,
            "saveOnlyUniqueItems": True,
            "maxConcurrency": 5,
        }

        results = run_apify_actor(apify_key, INDEED_ACTOR, run_input, timeout_mins=3)
        total_listings += len(results)
        print(f"    {len(results)} listings")

        for job in results:
            company = job.get("company", "") or job.get("companyName", "")
            job_title = job.get("positionName", "") or job.get("title", "") or job.get("position", "")
            job_location = job.get("location", city)
            job_url = job.get("url", "") or job.get("externalUrl", "")

            if not company or len(company) < 3:
                continue

            # Dedupe
            company_key = company.strip().lower()
            if company_key in companies:
                continue

            # Filter junk
            if is_junk_company(company):
                continue

            companies[company_key] = {
                "company_name": company.strip(),
                "job_title_hiring": job_title,
                "location": job_location,
                "city": city.split(",")[0].strip(),
                "state": city.split(",")[-1].strip() if "," in city else "",
                "job_url": job_url,
                "is_hvac_confirmed": is_likely_hvac(company, job_title),
            }

        time.sleep(1)

    return list(companies.values()), total_listings


def main():
    parser = argparse.ArgumentParser(description="Scrape Indeed for HVAC hiring companies")
    parser.add_argument("--target", type=int, default=200, help="Target companies (default: 200)")
    parser.add_argument("--cities", type=int, default=30, help="Number of cities to scrape (default: 30)")
    args = parser.parse_args()

    config = load_config()
    apify_key = config["apify_api_key"]

    print(f"\n{'='*60}")
    print(f"  HVAC HIRING INTENT SCRAPE — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    print(f"  Target: {args.target} companies")
    print(f"  Cities: {args.cities}")

    # Shuffle cities for variety
    cities = CITIES[:args.cities]
    random.shuffle(cities)

    companies, total_listings = scrape_indeed(apify_key, cities, args.target)

    # Separate confirmed HVAC from unconfirmed
    confirmed = [c for c in companies if c["is_hvac_confirmed"]]
    unconfirmed = [c for c in companies if not c["is_hvac_confirmed"]]

    print(f"\n{'='*60}")
    print(f"  RESULTS")
    print(f"{'='*60}")
    print(f"  Total Indeed listings: {total_listings}")
    print(f"  Unique companies: {len(companies)}")
    print(f"  Confirmed HVAC/trade: {len(confirmed)}")
    print(f"  Unconfirmed (need review): {len(unconfirmed)}")

    # Save results
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    output_path = os.path.join(OUTPUT_DIR, "hvac_hiring_companies.json")
    output = {
        "scraped_at": datetime.now().isoformat(),
        "total_listings": total_listings,
        "total_companies": len(companies),
        "confirmed_hvac": len(confirmed),
        "companies": companies,
    }
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"  Saved: {output_path}")

    # Also save a simple CSV for review
    csv_path = os.path.join(OUTPUT_DIR, "hvac_hiring_companies.csv")
    import csv
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "company_name", "job_title_hiring", "location", "city", "state",
            "is_hvac_confirmed", "job_url",
        ])
        writer.writeheader()
        writer.writerows(companies)
    print(f"  Saved: {csv_path}")

    print(f"\n  Next step: Enrich with Apollo to get owner names + emails")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
