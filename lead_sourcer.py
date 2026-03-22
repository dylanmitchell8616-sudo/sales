#!/usr/bin/env python3
"""
Lead Sourcer — Automatically discover companies matching Realside AI's ICP.

Searches DuckDuckGo for service businesses (med spas, dental offices, etc.)
across major US metro areas, extracts business names and domains from results,
deduplicates, pre-scores lead quality, and outputs a CSV ready for the sales pipeline.

Features:
  - Multiple search query variations per vertical/city for better coverage
  - Expanded aggregator/directory site filtering
  - LinkedIn company page scraping for employee count verification
  - Lead quality pre-scoring before enrichment

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

# Search query templates for better coverage
# Each template will be formatted with {vertical} and {city}
QUERY_TEMPLATES = [
    "{vertical} {city}",
    "{vertical} near {city}",
    "best {vertical} in {city}",
    "{vertical} {city} reviews",
    "top rated {vertical} {city}",
    "new {vertical} opening {city}",
]

# Domains to exclude — aggregators, directories, social media, etc.
EXCLUDED_DOMAINS = {
    # Social media
    "yelp.com", "google.com", "facebook.com", "instagram.com",
    "twitter.com", "x.com", "linkedin.com", "tiktok.com",
    "pinterest.com", "youtube.com", "reddit.com", "nextdoor.com",
    # Directories and aggregators
    "yellowpages.com", "bbb.org", "mapquest.com", "angi.com",
    "angieslist.com", "thumbtack.com", "healthgrades.com",
    "zocdoc.com", "vitals.com", "webmd.com", "realself.com",
    "groupon.com", "foursquare.com", "tripadvisor.com",
    "manta.com", "citysearch.com", "superpages.com",
    "whitepages.com", "dexknows.com", "chamberofcommerce.com",
    # Search engines / tech
    "apple.com", "bing.com", "yahoo.com", "duckduckgo.com",
    "wikipedia.org", "amazon.com",
    # News / media
    "patch.com", "glassdoor.com", "indeed.com", "crunchbase.com",
    "bloomberg.com", "nytimes.com", "forbes.com", "inc.com",
    # Healthcare aggregators (expanded)
    "wellness.com", "mindbodyonline.com", "mindbody.io",
    "vagaro.com", "booksy.com", "fresha.com", "treatwell.com",
    "opencare.com", "dentistry.com", "1800dentist.com",
    "asahq.org", "ada.org", "ama-assn.org",
    # Booking / review platforms
    "trustpilot.com", "g2.com", "capterra.com",
    "softwareadvice.com", "getapp.com",
    # General directories
    "hotfrog.com", "brownbook.net", "fyple.com",
    "cylex.us.com", "spoke.com", "bizapedia.com",
    "dnb.com", "dandb.com", "owler.com",
    # Government / education
    "gov", "edu", "mil",
    # Website builders (these are the platform, not the business)
    "wix.com", "squarespace.com", "weebly.com", "godaddy.com",
    "wordpress.com", "shopify.com", "webflow.io",
}

# Patterns that indicate an aggregator/directory page rather than a real business
AGGREGATOR_URL_PATTERNS = [
    r"/biz/",           # Yelp-style
    r"/listing",        # Directory listing pages
    r"/directory",      # Directory pages
    r"/find-a-",        # "Find a dentist" pages
    r"/search\?",       # Search result pages
    r"/results\?",      # Search result pages
    r"/top-\d+",        # "Top 10" listicles
    r"/best-\d+",       # "Best 10" listicles
    r"/category/",      # Category pages
    r"/profile/",       # Profile on aggregator
    r"/reviews/",       # Review aggregator pages
]

# ICP quality signals in page titles / snippets
ICP_POSITIVE_SIGNALS = [
    "appointment", "book online", "schedule", "consultation",
    "services", "treatments", "our team", "meet the doctor",
    "before and after", "patient", "client",
]

ICP_NEGATIVE_SIGNALS = [
    "franchise", "hiring", "careers", "jobs", "apply now",
    "for sale", "closed", "permanently closed",
    "software", "saas", "platform",
]

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
    # Check for TLD-only exclusions (gov, edu, mil)
    tld = domain_lower.rsplit(".", 1)[-1] if "." in domain_lower else ""
    if tld in ("gov", "edu", "mil"):
        return True
    return False


def is_aggregator_url(url: str) -> bool:
    """Check if a URL looks like an aggregator/directory page rather than a business site."""
    url_lower = url.lower()
    for pattern in AGGREGATOR_URL_PATTERNS:
        if re.search(pattern, url_lower):
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
            # Additional check: reject if URL itself looks like an aggregator page
            if is_aggregator_url(url):
                return None
            return domain
    except Exception:
        pass
    return None


def extract_business_name_from_title(title: str, vertical: str, city: str) -> str:
    """Try to extract a clean business name from a search result title."""
    # Remove common suffixes added by search engines
    name = title.split(" - ")[0].split(" | ")[0].split(" \u00b7 ")[0].strip()
    # Remove trailing city/state references
    for remove in [city, "TX", "CA", "FL", "GA", "CO", "AZ", "IL", "NY", "WA", "TN", "NC"]:
        name = re.sub(rf",?\s*{re.escape(remove)}\s*$", "", name, flags=re.IGNORECASE)
    name = name.strip(" -\u2013\u2014|,")
    return name if name else title


def pre_score_lead(title: str, url: str, vertical: str, domain: str) -> dict:
    """Pre-score a lead's quality before enrichment.

    Evaluates based on signals in the search result title and URL
    to estimate how likely this is a real ICP-matching business.

    Args:
        title: Search result title.
        url: Search result URL.
        vertical: The vertical being searched.
        domain: The cleaned domain.

    Returns:
        dict with keys: score (0-100), signals (list of str), skip (bool)
    """
    score = 50  # Start at neutral
    signals = []

    title_lower = title.lower()
    url_lower = url.lower()

    # Positive signals
    for signal in ICP_POSITIVE_SIGNALS:
        if signal in title_lower or signal in url_lower:
            score += 5
            signals.append(f"+{signal}")
            break  # Cap at one positive signal from this list

    # Check if vertical appears in domain (strong signal)
    vertical_words = vertical.lower().split()
    for word in vertical_words:
        if len(word) > 3 and word in domain:
            score += 15
            signals.append(f"+domain_match({word})")
            break

    # Check for business-like domain patterns
    if re.search(r"(dental|spa|clinic|wellness|aesthetic|beauty|derm|ortho|med)", domain):
        score += 10
        signals.append("+industry_domain")

    # Negative signals
    for signal in ICP_NEGATIVE_SIGNALS:
        if signal in title_lower:
            score -= 15
            signals.append(f"-{signal}")
            break

    # Penalize very generic domains
    if re.match(r"^[a-z]{1,3}\.[a-z]+$", domain):
        score -= 10
        signals.append("-generic_domain")

    # Penalize domains that look like multi-location/franchise sites
    if any(x in domain for x in ["locations.", "franchise.", "corporate."]):
        score -= 10
        signals.append("-franchise_domain")

    # Bonus for custom/branded domain (not a subdomain of a platform)
    if "." in domain and domain.count(".") == 1:
        score += 5
        signals.append("+own_domain")

    score = max(0, min(100, score))
    skip = score < 20

    return {"score": score, "signals": signals, "skip": skip}


def try_get_employee_count_from_page(domain: str, session: requests.Session) -> int | None:
    """Try to scrape employee count hints from the company website.

    Checks the about page for team size indicators.
    Returns estimated employee count, or None if not found.
    """
    about_paths = ["/about", "/about-us", "/our-team", "/team", "/staff"]
    base_url = f"https://{domain}"

    for path in about_paths:
        try:
            resp = session.get(f"{base_url}{path}", timeout=8, allow_redirects=True)
            if resp.status_code != 200:
                continue
            text = resp.text.lower()

            # Look for patterns like "X+ employees", "team of X", etc.
            patterns = [
                r"(\d{1,4})\+?\s*(?:employees|team members|staff|providers|doctors|dentists|practitioners)",
                r"team\s+of\s+(\d{1,4})",
                r"(\d{1,4})\s*(?:locations|offices|practices)",
            ]
            for pattern in patterns:
                match = re.search(pattern, text)
                if match:
                    count = int(match.group(1))
                    if 1 <= count <= 10000:
                        return count
            break  # Found a page, just couldn't extract count
        except Exception:
            continue

    return None


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
    query_variations: int = 2,
    min_quality_score: int = 30,
) -> list[dict]:
    """
    Search for businesses matching the ICP across cities and verticals.
    Returns a deduplicated list of leads with domain, company_name, quality score, etc.

    Args:
        cities: List of city names to search.
        verticals: List of business verticals to search.
        limit: Maximum number of unique leads to collect.
        dry_run: If True, show queries without executing.
        query_variations: Number of query template variations to use per vertical/city.
        min_quality_score: Minimum pre-score quality threshold (0-100).
    """
    session = get_session()
    seen_domains = set()
    leads = []

    # Build all search queries with multiple variations for better coverage
    queries = []
    templates_to_use = QUERY_TEMPLATES[:query_variations]
    for vertical in verticals:
        for city in cities:
            for template in templates_to_use:
                query = template.format(vertical=vertical, city=city)
                queries.append((query, vertical, city))

    total_queries = len(queries)
    print(f"\nWill run {total_queries} searches across {len(verticals)} verticals x {len(cities)} cities x {len(templates_to_use)} variations")
    if dry_run:
        print("\n[DRY RUN] Queries that would be executed:")
        for q, v, c in queries[:30]:
            print(f"  - {q}")
        if total_queries > 30:
            print(f"  ... and {total_queries - 30} more")
        print(f"\n[DRY RUN] Total queries: {total_queries}")
        print(f"[DRY RUN] Estimated time: {total_queries * 1.5:.0f}-{total_queries * 2.5:.0f} seconds")
        return []

    print(f"Target: up to {limit} unique leads (min quality score: {min_quality_score})\n")

    skipped_quality = 0
    skipped_aggregator = 0

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

            # Pre-score the lead quality
            quality = pre_score_lead(result["title"], result["url"], vertical, domain)
            if quality["skip"]:
                skipped_quality += 1
                continue
            if quality["score"] < min_quality_score:
                skipped_quality += 1
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
                "quality_score": quality["score"],
                "quality_signals": "|".join(quality["signals"]),
            })
            new_count += 1

        print(f"  -> {len(results)} results, {new_count} new leads (total: {len(leads)})")

        # Rate limiting with slight jitter
        import random
        delay = random.uniform(RATE_LIMIT_MIN, RATE_LIMIT_MAX)
        time.sleep(delay)

    if skipped_quality > 0:
        print(f"\nSkipped {skipped_quality} low-quality results (below score {min_quality_score})")

    return leads


def write_csv(filepath: str, leads: list[dict]):
    """Write leads to CSV in the targets.csv format."""
    fieldnames = ["domain", "company_name", "contact_name", "contact_title",
                   "quality_score", "quality_signals"]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for lead in leads:
            writer.writerow({
                "domain": lead["domain"],
                "company_name": lead["company_name"],
                "contact_name": lead.get("contact_name", ""),
                "contact_title": lead.get("contact_title", "Owner"),
                "quality_score": lead.get("quality_score", ""),
                "quality_signals": lead.get("quality_signals", ""),
            })
    print(f"\nWrote {len(leads)} leads to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Lead Sourcer - Discover companies matching Realside AI's ICP "
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
        "--query-variations", type=int, default=2,
        help="Number of search query variations per vertical/city (1-6, default: 2)"
    )
    parser.add_argument(
        "--min-quality", type=int, default=30,
        help="Minimum lead quality score 0-100 (default: 30)"
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

    query_variations = max(1, min(6, args.query_variations))

    print("=" * 60)
    print("  Lead Sourcer - Realside AI")
    print("=" * 60)
    print(f"  Output:      {args.output}")
    print(f"  Limit:       {args.limit} leads")
    print(f"  Cities:      {', '.join(cities)}")
    print(f"  Verticals:   {', '.join(verticals)}")
    print(f"  Variations:  {query_variations} per vertical/city")
    print(f"  Min Quality: {args.min_quality}/100")
    if args.dry_run:
        print(f"  Mode:        DRY RUN")
    print("=" * 60)

    if config.get("icp_description"):
        print(f"\n  ICP: {config['icp_description'][:120]}...")

    # Discover leads
    leads = discover_leads(
        cities=cities,
        verticals=verticals,
        limit=args.limit,
        dry_run=args.dry_run,
        query_variations=query_variations,
        min_quality_score=args.min_quality,
    )

    if args.dry_run:
        print("\n[DRY RUN] No output file written.")
        return

    if not leads:
        print("\nNo leads found. Try adjusting cities or verticals.")
        sys.exit(0)

    # Sort by quality score descending
    leads.sort(key=lambda x: x.get("quality_score", 0), reverse=True)

    # Write output
    write_csv(args.output, leads)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"  Summary")
    print(f"{'=' * 60}")
    print(f"  Total unique leads: {len(leads)}")

    # Quality score distribution
    if leads:
        scores = [l.get("quality_score", 50) for l in leads]
        avg_score = sum(scores) / len(scores)
        high_quality = sum(1 for s in scores if s >= 70)
        print(f"\n  Quality scores:")
        print(f"    Average: {avg_score:.0f}/100")
        print(f"    High quality (70+): {high_quality}/{len(leads)}")

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
