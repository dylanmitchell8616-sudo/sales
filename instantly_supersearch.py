#!/usr/bin/env python3
"""
Instantly Supersearch + Perplexity Lead Finder
================================================
Uses Instantly's Supersearch (powered by Perplexity AI) to find and enrich
leads from their 300M+ contact database. Supports custom waterfall enrichment
— tries cheapest data source first, cascades to more expensive ones.

Usage:
    python instantly_supersearch.py --search "med spa owner Texas"
    python instantly_supersearch.py --bulk-search --niches "dental,med spa,wellness" --locations "Texas,Florida,California"
    python instantly_supersearch.py --enrich --input output/leads_to_enrich.csv
    python instantly_supersearch.py --waterfall --campaign-id ABC123 --target 100
    python instantly_supersearch.py --dry-run
"""

import argparse
import csv
import json
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
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
SEARCH_LOG_PATH = os.path.join(OUTPUT_DIR, "supersearch_log.json")
PROCESSED_LEADS_PATH = os.path.join(OUTPUT_DIR, "processed_leads.json")

BASE_URL = "https://api.instantly.ai/api/v2"

# Niche-specific search configurations
NICHE_CONFIGS = {
    "med_spa": {
        "keywords": ["med spa", "medical spa", "medspa", "aesthetics clinic", "cosmetic clinic"],
        "titles": ["owner", "founder", "ceo", "medical director", "practice manager"],
        "industries": ["health, wellness & fitness", "cosmetics", "medical practice"],
    },
    "dental": {
        "keywords": ["dental office", "dentist", "dental practice", "dental clinic", "orthodontics"],
        "titles": ["owner", "founder", "dentist", "practice manager", "office manager"],
        "industries": ["medical practice", "hospital & health care"],
    },
    "wellness": {
        "keywords": ["wellness center", "iv therapy", "chiropractic", "physical therapy", "holistic health"],
        "titles": ["owner", "founder", "director", "practice manager", "wellness director"],
        "industries": ["health, wellness & fitness", "alternative medicine"],
    },
    "plastic_surgery": {
        "keywords": ["plastic surgery", "cosmetic surgery", "plastic surgeon", "aesthetic surgery"],
        "titles": ["owner", "surgeon", "medical director", "practice manager"],
        "industries": ["medical practice", "hospital & health care"],
    },
    "dermatology": {
        "keywords": ["dermatology", "dermatologist", "skin care clinic", "derm practice"],
        "titles": ["owner", "dermatologist", "medical director", "practice manager"],
        "industries": ["medical practice", "health, wellness & fitness"],
    },
    "veterinary": {
        "keywords": ["veterinary", "vet clinic", "animal hospital", "veterinarian"],
        "titles": ["owner", "veterinarian", "hospital director", "practice manager"],
        "industries": ["veterinary"],
    },
}

# US metro areas with highest concentration of service businesses
TOP_METROS = [
    "New York", "Los Angeles", "Miami", "Houston", "Dallas", "Chicago",
    "Phoenix", "San Diego", "San Antonio", "Austin", "Denver", "Seattle",
    "Tampa", "Orlando", "Atlanta", "Las Vegas", "Nashville", "Charlotte",
    "San Francisco", "Portland", "Scottsdale", "Beverly Hills", "Boca Raton",
]


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def api_request(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    for attempt in range(4):
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            elif method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "PATCH":
                resp = requests.patch(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                print(f"  API error {resp.status_code}: {resp.text[:300]}")
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json() if resp.text else {}
        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after 4 attempts: {e}")
                return {"error": str(e)}
    return {"error": "Max retries exceeded"}


def load_processed_leads() -> set:
    """Load already-processed emails to avoid dupes."""
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


def load_search_log() -> dict:
    if os.path.exists(SEARCH_LOG_PATH):
        try:
            with open(SEARCH_LOG_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"searches": [], "total_leads_found": 0, "total_credits_used": 0}


def save_search_log(log: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(SEARCH_LOG_PATH, "w") as f:
        json.dump(log, f, indent=2)


GENERIC_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "enquiries", "reception",
    "frontdesk", "billing", "noreply", "no-reply", "donotreply",
}


def is_quality_lead(lead: dict) -> bool:
    """Filter for quality leads — personal email, has name, valid domain."""
    email = lead.get("email", "")
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    if local in GENERIC_PREFIXES:
        return False
    # Must have a name
    if not lead.get("first_name") and not lead.get("last_name"):
        return False
    # Skip free email domains
    domain = email.split("@")[1].lower()
    free_domains = {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"}
    if domain in free_domains:
        return False
    return True


def supersearch(api_key: str, niche: str = None, location: str = None,
                custom_query: str = None, limit: int = 50,
                filters: dict = None) -> list:
    """
    Run Instantly Supersearch with Perplexity AI enrichment.
    Returns enriched leads with verified emails.
    """
    if custom_query:
        print(f"\n  Supersearch: '{custom_query}' (limit: {limit})")
    else:
        print(f"\n  Supersearch: {niche or 'all niches'} in {location or 'all locations'} (limit: {limit})")

    # Build search payload
    niche_config = NICHE_CONFIGS.get(niche, {}) if niche else {}
    search_filters = filters or {}

    payload = {
        "limit": limit,
    }

    # Apply niche-specific filters
    if niche_config:
        payload["titles"] = niche_config.get("titles", [])
        payload["industry"] = niche_config.get("industries", [])
        payload["keywords"] = niche_config.get("keywords", [])

    # Override with custom filters
    if search_filters.get("titles"):
        payload["titles"] = search_filters["titles"]
    if search_filters.get("industries"):
        payload["industry"] = search_filters["industries"]
    if search_filters.get("keywords"):
        payload["keywords"] = search_filters["keywords"]

    # Location filtering
    if location:
        payload["location"] = [location]
    elif search_filters.get("locations"):
        payload["location"] = search_filters["locations"]

    # Employee range
    payload["employee_range"] = search_filters.get("employee_ranges", ["11-50", "51-200"])

    # Free text search query
    if custom_query:
        payload["query"] = custom_query

    # Try lead search endpoints
    result = api_request("POST", "lead-search", api_key, payload)
    if "error" in result:
        result = api_request("POST", "leads/search", api_key, payload)
        if "error" in result:
            # Fall back to lead finder
            result = api_request("POST", "lead-finder", api_key, payload)
            if "error" in result:
                print(f"  Search failed: {result.get('error', 'unknown')}")
                return []

    leads = result.get("items", result.get("leads", result.get("data", [])))
    if isinstance(leads, dict):
        leads = leads.get("items", [])

    if not isinstance(leads, list):
        leads = []

    # Filter for quality
    quality_leads = [l for l in leads if is_quality_lead(l)]
    print(f"  Found {len(leads)} total, {len(quality_leads)} quality leads")

    return quality_leads


def bulk_search(api_key: str, niches: list, locations: list,
                leads_per_combo: int = 25, dry_run: bool = False) -> list:
    """
    Run Supersearch across multiple niche x location combinations.
    This is the scaling engine — finds leads across all your target markets.
    """
    all_leads = []
    existing_emails = load_processed_leads()
    search_log = load_search_log()

    total_combos = len(niches) * len(locations)
    print(f"\n=== Bulk Supersearch: {len(niches)} niches x {len(locations)} locations = {total_combos} searches ===\n")

    combo_num = 0
    for niche in niches:
        niche_key = niche.lower().replace(" ", "_")
        if niche_key not in NICHE_CONFIGS:
            print(f"  Warning: Unknown niche '{niche}', using generic search")

        for location in locations:
            combo_num += 1
            print(f"\n--- [{combo_num}/{total_combos}] {niche} in {location} ---")

            if dry_run:
                print(f"  [DRY RUN] Would search for {leads_per_combo} leads")
                continue

            leads = supersearch(api_key, niche=niche_key, location=location, limit=leads_per_combo)

            # Dedup against existing
            new_leads = []
            for lead in leads:
                email = lead.get("email", "").lower()
                if email and email not in existing_emails:
                    existing_emails.add(email)
                    new_leads.append(lead)

            all_leads.extend(new_leads)
            print(f"  New (deduped): {len(new_leads)}")

            # Log this search
            search_log["searches"].append({
                "niche": niche,
                "location": location,
                "found": len(leads),
                "new": len(new_leads),
                "timestamp": datetime.now().isoformat(),
            })

            # Rate limit between searches
            time.sleep(1)

    search_log["total_leads_found"] += len(all_leads)
    save_search_log(search_log)

    print(f"\n=== Bulk Search Complete ===")
    print(f"  Total new leads: {len(all_leads)}")

    return all_leads


def waterfall_enrich(api_key: str, leads: list, campaign_id: str = None,
                     dry_run: bool = False) -> list:
    """
    Custom waterfall enrichment — tries cheapest source first, cascades.
    Order: Instantly DB → Perplexity enrich → Apify scrape (external).
    """
    print(f"\n=== Waterfall Enrichment ({len(leads)} leads) ===\n")

    enriched = []
    needs_external = []

    for i, lead in enumerate(leads):
        email = lead.get("email", "")
        has_phone = bool(lead.get("phone") or lead.get("phone_number"))
        has_company = bool(lead.get("company_name") or lead.get("company"))
        has_website = bool(lead.get("website") or lead.get("company_url"))

        # Score completeness
        completeness = sum([
            bool(email),
            bool(lead.get("first_name")),
            bool(lead.get("last_name")),
            has_company,
            bool(lead.get("title")),
            has_phone,
            has_website,
        ])

        if completeness >= 5:
            # Good enough from Instantly DB
            enriched.append(lead)
        else:
            # Needs more enrichment
            needs_external.append(lead)

    print(f"  Complete from Instantly: {len(enriched)}")
    print(f"  Need external enrichment: {len(needs_external)}")

    # Try Perplexity enrichment for incomplete leads
    if needs_external and not dry_run:
        print(f"\n  Running Perplexity enrichment on {len(needs_external)} leads...")
        for lead in needs_external:
            company = lead.get("company_name", lead.get("company", ""))
            if company:
                enrich_result = api_request("POST", "leads/enrich", api_key, {
                    "email": lead.get("email", ""),
                    "company_name": company,
                })
                if "error" not in enrich_result:
                    lead.update({k: v for k, v in enrich_result.items() if v})
            enriched.append(lead)
            time.sleep(0.5)  # Rate limit

    # Upload to campaign if specified
    if campaign_id and enriched and not dry_run:
        upload_leads_to_campaign(api_key, campaign_id, enriched)

    return enriched


def upload_leads_to_campaign(api_key: str, campaign_id: str, leads: list):
    """Upload enriched leads to an Instantly campaign."""
    print(f"\n  Uploading {len(leads)} leads to campaign {campaign_id}...")

    # Format leads for Instantly API
    formatted = []
    for lead in leads:
        formatted.append({
            "email": lead.get("email", ""),
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company_name", lead.get("company", "")),
            "personalization": lead.get("title", ""),
            "phone": lead.get("phone", lead.get("phone_number", "")),
            "website": lead.get("website", lead.get("company_url", "")),
            "custom_variables": {
                "title": lead.get("title", ""),
                "industry": lead.get("industry", ""),
                "city": lead.get("city", ""),
                "state": lead.get("state", ""),
                "employee_count": str(lead.get("employee_count", "")),
                "source": "supersearch",
            },
        })

    # Upload in batches of 50
    batch_size = 50
    uploaded = 0
    for i in range(0, len(formatted), batch_size):
        batch = formatted[i:i + batch_size]
        result = api_request("POST", f"campaigns/{campaign_id}/leads", api_key, {"leads": batch})
        if "error" not in result:
            uploaded += len(batch)
            print(f"  Uploaded batch {i // batch_size + 1}: {len(batch)} leads")
        else:
            print(f"  Batch {i // batch_size + 1} failed: {result['error'][:200]}")
        time.sleep(1)

    print(f"  Total uploaded: {uploaded}/{len(formatted)}")


def export_leads_csv(leads: list, filename: str = "supersearch_leads.csv"):
    """Export leads to CSV for review or manual import."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, filename)

    fieldnames = ["email", "first_name", "last_name", "company_name", "title",
                   "phone", "website", "industry", "city", "state", "employee_count"]

    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            row = {
                "email": lead.get("email", ""),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company_name": lead.get("company_name", lead.get("company", "")),
                "title": lead.get("title", ""),
                "phone": lead.get("phone", lead.get("phone_number", "")),
                "website": lead.get("website", lead.get("company_url", "")),
                "industry": lead.get("industry", ""),
                "city": lead.get("city", ""),
                "state": lead.get("state", ""),
                "employee_count": lead.get("employee_count", ""),
            }
            writer.writerow(row)

    print(f"\n  Exported {len(leads)} leads to {path}")
    return path


def main():
    parser = argparse.ArgumentParser(description="Instantly Supersearch + Perplexity Lead Finder")
    parser.add_argument("--api-key", help="Instantly API key (or uses config.json)")
    parser.add_argument("--search", metavar="QUERY", help="Free-text search query")
    parser.add_argument("--bulk-search", action="store_true", help="Search across all niches x locations")
    parser.add_argument("--niches", help="Comma-separated niches (default: all)")
    parser.add_argument("--locations", help="Comma-separated locations (default: top metros)")
    parser.add_argument("--limit", type=int, default=25, help="Leads per search (default: 25)")
    parser.add_argument("--enrich", action="store_true", help="Run waterfall enrichment on results")
    parser.add_argument("--waterfall", action="store_true", help="Full waterfall: search + enrich + upload")
    parser.add_argument("--campaign-id", help="Campaign ID to upload leads to")
    parser.add_argument("--target", type=int, default=100, help="Target number of leads for waterfall")
    parser.add_argument("--export", action="store_true", help="Export results to CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    config = load_config()
    api_key = args.api_key or config.get("instantly_api_key", "")
    if not api_key:
        print("Error: No API key. Use --api-key or set instantly_api_key in config.json")
        sys.exit(1)

    # Parse niches and locations
    if args.niches:
        niches = [n.strip() for n in args.niches.split(",")]
    else:
        niches = list(NICHE_CONFIGS.keys())

    if args.locations:
        locations = [l.strip() for l in args.locations.split(",")]
    else:
        locations = TOP_METROS[:10]  # Top 10 by default

    # Single search
    if args.search:
        leads = supersearch(api_key, custom_query=args.search, limit=args.limit)
        if leads:
            for i, l in enumerate(leads[:15], 1):
                name = f"{l.get('first_name', '')} {l.get('last_name', '')}".strip()
                company = l.get("company_name", l.get("company", "?"))
                print(f"  {i}. {name} — {l.get('title', '?')} @ {company} ({l.get('email', '?')})")
            if args.export:
                export_leads_csv(leads)
        return

    # Bulk search
    if args.bulk_search:
        leads = bulk_search(api_key, niches, locations,
                            leads_per_combo=args.limit, dry_run=args.dry_run)
        if leads and args.export:
            export_leads_csv(leads, "bulk_supersearch_leads.csv")
        if leads and args.enrich:
            waterfall_enrich(api_key, leads, campaign_id=args.campaign_id, dry_run=args.dry_run)
        return

    # Full waterfall pipeline
    if args.waterfall:
        if not args.campaign_id:
            print("Error: --waterfall requires --campaign-id")
            sys.exit(1)

        print(f"\n=== Waterfall Pipeline: Target {args.target} leads ===\n")

        all_leads = []
        # Search across niches until we hit target
        for niche in niches:
            if len(all_leads) >= args.target:
                break
            remaining = args.target - len(all_leads)
            per_location = max(5, remaining // len(locations))

            for location in locations:
                if len(all_leads) >= args.target:
                    break
                leads = supersearch(api_key, niche=niche, location=location,
                                    limit=min(per_location, 50))
                all_leads.extend(leads)
                time.sleep(1)

        print(f"\n  Collected {len(all_leads)} leads, enriching...")
        enriched = waterfall_enrich(api_key, all_leads, campaign_id=args.campaign_id,
                                     dry_run=args.dry_run)
        if args.export:
            export_leads_csv(enriched, "waterfall_leads.csv")
        return

    # Default: show help
    parser.print_help()
    print("\n\nExamples:")
    print('  python instantly_supersearch.py --search "med spa owner Miami"')
    print('  python instantly_supersearch.py --bulk-search --niches "dental,med_spa" --locations "Miami,Dallas"')
    print('  python instantly_supersearch.py --waterfall --campaign-id ABC123 --target 200 --export')


if __name__ == "__main__":
    main()
