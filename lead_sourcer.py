#!/usr/bin/env python3
"""
Lead Sourcer — Automatically discover companies matching Realside AI's ICP.

Searches DuckDuckGo for service businesses (med spas, dental offices, etc.)
across major US metro areas, extracts business names and domains from results,
deduplicates, and outputs a CSV ready for the sales pipeline.

Usage:
    python lead_sourcer.py --output targets_auto.csv --limit 100
    python lead_sourcer.py --output targets_auto.csv --cities "Dallas,Houston,Austin" --verticals "med spa,dental office"
    python lead_sourcer.py --output targets_auto.csv --limit 50 --dry-run
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urlparse, quote_plus

try:
    import requests
    from bs4 import BeautifulSoup
except ImportError:
    print("Error: requests and beautifulsoup4 are required.")
    print("Install with: pip install requests beautifulsoup4")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Defaults from ICP
# ---------------------------------------------------------------------------

DEFAULT_CITIES = [
    "Dallas", "Houston", "Austin", "Los Angeles", "Miami",
    "Atlanta", "Denver", "Phoenix", "Chicago", "New York",
    "San Francisco", "Seattle", "Nashville", "Charlotte", "Tampa",
]

DEFAULT_VERTICALS = [
    "med spa", "dental office", "aesthetic clinic",
    "wellness center", "IV clinic", "plastic surgery practice",
]

# Domains to exclude — aggregators, directories, social media, etc.
EXCLUDED_DOMAINS = {
    "yelp.com", "google.com", "facebook.com", "yellowpages.com",
    "instagram.com", "twitter.com", "x.com", "linkedin.com",
    "tiktok.com", "pinterest.com", "youtube.com", "reddit.com",
    "bbb.org", "mapquest.com", "angi.com", "angieslist.com",
    "thumbtack.com", "healthgrades.com", "zocdoc.com", "vitals.com",
    "webmd.com", "realself.com", "groupon.com", "foursquare.com",
    "tripadvisor.com", "nextdoor.com", "manta.com", "citysearch.com",
    "superpages.com", "whitepages.com", "dexknows.com",
    "apple.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "wikipedia.org", "amazon.com", "patch.com", "glassdoor.com",
    "indeed.com", "crunchbase.com", "bloomberg.com",
    "nytimes.com", "forbes.com", "inc.com",
}

REQUEST_TIMEOUT = 15
RATE_LIMIT_MIN = 1.0   # minimum seconds between searches
RATE_LIMIT_MAX = 2.0   # maximum seconds between searches

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config():
    """Load config.json if available, for defaults."""
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def get_session():
    """Create a requests session with a browser-like User-Agent."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return session


def is_excluded_domain(domain: str) -> bool:
    """Check if a domain belongs to an excluded aggregator/directory site."""
    domain_lower = domain.lower()
    for excluded in EXCLUDED_DOMAINS:
        if domain_lower == excluded or domain_lower.endswith("." + excluded):
            return True
    return False


def clean_domain(url: str) -> str | None:
    """Extract and clean a domain from a URL. Returns None if invalid."""
    try:
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path.split("/")[0]
        domain = domain.lower().strip()
        domain = re.sub(r"^www\.", "", domain)
        # Basic validation
        if "." in domain and len(domain) > 3 and not is_excluded_domain(domain):
            return domain
    except Exception:
        pass
    return None


def extract_business_name_from_title(title: str, vertical: str, city: str) -> str:
    """Try to extract a clean business name from a search result title."""
    # Remove common suffixes added by search engines
    name = title.split(" - ")[0].split(" | ")[0].split(" · ")[0].strip()
    # Remove trailing city/state references
    for remove in [city, "TX", "CA", "FL", "GA", "CO", "AZ", "IL", "NY", "WA", "TN", "NC"]:
        name = re.sub(rf",?\s*{re.escape(remove)}\s*$", "", name, flags=re.IGNORECASE)
    name = name.strip(" -–—|,")
    return name if name else title


def search_duckduckgo(query: str, session: requests.Session) -> list[dict]:
    """
    Search DuckDuckGo HTML and extract result titles + URLs.
    Returns list of dicts with 'title' and 'url' keys.
    """
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
    results = []

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            return results

        soup = BeautifulSoup(resp.text, "html.parser")

        # DuckDuckGo HTML results are in <a class="result__a"> tags
        for link in soup.select("a.result__a"):
            title = link.get_text(strip=True)
            href = link.get("href", "")

            if not href or not title:
                continue

            # DuckDuckGo wraps URLs in a redirect; extract the actual URL
            # The href might be a direct URL or a //duckduckgo.com/l/?uddg= redirect
            if "uddg=" in href:
                from urllib.parse import parse_qs, urlparse as _urlparse
                parsed = _urlparse(href)
                params = parse_qs(parsed.query)
                if "uddg" in params:
                    href = params["uddg"][0]

            results.append({"title": title, "url": href})

    except requests.RequestException as e:
        print(f"    Warning: Search request failed: {e}")
    except Exception as e:
        print(f"    Warning: Error parsing results: {e}")

    return results


def discover_leads(
    cities: list[str],
    verticals: list[str],
    limit: int,
    dry_run: bool = False,
) -> list[dict]:
    """
    Search for businesses matching the ICP across cities and verticals.
    Returns a deduplicated list of leads with domain, company_name, etc.
    """
    session = get_session()
    seen_domains = set()
    leads = []

    # Build all search queries
    queries = []
    for vertical in verticals:
        for city in cities:
            queries.append((f"{vertical} {city}", vertical, city))

    total_queries = len(queries)
    print(f"\nWill run {total_queries} searches across {len(verticals)} verticals x {len(cities)} cities")
    if dry_run:
        print("\n[DRY RUN] Queries that would be executed:")
        for q, v, c in queries:
            print(f"  - {q}")
        print(f"\n[DRY RUN] Total queries: {total_queries}")
        print(f"[DRY RUN] Estimated time: {total_queries * 1.5:.0f}-{total_queries * 2.5:.0f} seconds")
        return []

    print(f"Target: up to {limit} unique leads\n")

    for i, (query, vertical, city) in enumerate(queries, 1):
        if len(leads) >= limit:
            print(f"\nReached limit of {limit} leads. Stopping early.")
            break

        print(f"[{i}/{total_queries}] Searching: \"{query}\"", end="")

        results = search_duckduckgo(query, session)
        new_count = 0

        for result in results:
            if len(leads) >= limit:
                break

            domain = clean_domain(result["url"])
            if not domain or domain in seen_domains:
                continue

            seen_domains.add(domain)
            company_name = extract_business_name_from_title(result["title"], vertical, city)

            leads.append({
                "domain": domain,
                "company_name": company_name,
                "contact_name": "",
                "contact_title": "Owner",
                "source_query": query,
                "source_city": city,
                "source_vertical": vertical,
            })
            new_count += 1

        print(f"  -> {len(results)} results, {new_count} new leads (total: {len(leads)})")

        # Rate limiting with slight jitter
        import random
        delay = random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX)
        time.sleep(delay)

    return leads


def write_csv(filepath: str, leads: list[dict]):
    """Write leads to CSV in the targets.csv format."""
    fieldnames = ["domain", "company_name", "contact_name", "contact_title"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                "domain": lead["domain"],
                "company_name": lead["company_name"],
                "contact_name": lead.get("contact_name", ""),
                "contact_title": lead.get("contact_title", "Owner"),
            })
    print(f"\nWrote {len(leads)} leads to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Lead Sourcer — Discover companies matching Realside AI's ICP "
            "by searching DuckDuckGo for service businesses across US metro areas."
        )
    )
    parser.add_argument(
        "--output", default="targets_auto.csv",
        help="Output CSV file path (default: targets_auto.csv)"
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Maximum number of unique leads to collect (default: 100)"
    )
    parser.add_argument(
        "--cities", default=None,
        help="Comma-separated list of cities to search (default: 15 major US metros)"
    )
    parser.add_argument(
        "--verticals", default=None,
        help="Comma-separated list of business verticals to search (default: med spa, dental office, etc.)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what searches would be performed without actually running them"
    )
    args = parser.parse_args()

    # Load config for context
    config = load_config()

    # Parse cities and verticals
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    else:
        cities = DEFAULT_CITIES

    if args.verticals:
        verticals = [v.strip() for v in args.verticals.split(",") if v.strip()]
    else:
        verticals = DEFAULT_VERTICALS

    print("=" * 60)
    print("  Lead Sourcer — Realside AI")
    print("=" * 60)
    print(f"  Output:    {args.output}")
    print(f"  Limit:     {args.limit} leads")
    print(f"  Cities:    {', '.join(cities)}")
    print(f"  Verticals: {', '.join(verticals)}")
    if args.dry_run:
        print(f"  Mode:      DRY RUN")
    print("=" * 60)

    if config.get("icp_description"):
        print(f"\n  ICP: {config['icp_description'][:120]}...")

    # Discover leads
    leads = discover_leads(
        cities=cities,
        verticals=verticals,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        print("\n[DRY RUN] No output file written.")
        return

    if not leads:
        print("\nNo leads found. Try adjusting cities or verticals.")
        sys.exit(0)

    # Write output
    write_csv(args.output, leads)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"  Total unique leads: {len(leads)}")

    # Breakdown by vertical
    by_vertical = {}
    for lead in leads:
        v = lead.get("source_vertical", "unknown")
        by_vertical[v] = by_vertical.get(v, 0) + 1
    print(f"\n  By vertical:")
    for v, count in sorted(by_vertical.items(), key=lambda x: -x[1]):
        print(f"    {v}: {count}")

    # Breakdown by city
    by_city = {}
    for lead in leads:
        c = lead.get("source_city", "unknown")
        by_city[c] = by_city.get(c, 0) + 1
    print(f"\n  By city:")
    for c, count in sorted(by_city.items(), key=lambda x: -x[1]):
        print(f"    {c}: {count}")

    print(f"\n  Output: {args.output}")
    print(f"  Ready to feed into the pipeline via targets.csv")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
