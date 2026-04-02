#!/usr/bin/env python3
"""
Automated ICP List Builder from Public Data

Scrapes public directories (YC company lists, ProductHunt launches) or takes a
manual CSV of company domains, evaluates each company against your Ideal Customer
Profile using Claude, and outputs a prioritized prospecting list with fit scores,
reasons, and personalized outreach angles.

Usage:
    python icp_list_builder.py --source yc --icp-description "B2B SaaS companies with 10-200 employees selling developer tools" --batch W24
    python icp_list_builder.py --source producthunt --icp-description "AI startups targeting enterprise customers" --limit 30
    python icp_list_builder.py --source manual --input companies.csv --icp-description "Fintech companies in Series A or later"
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from urllib.parse import urljoin, urlparse

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

try:
    import requests
    from bs4 import BeautifulSoup
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# Default config
DEFAULT_SENDER_EMAIL = "dylan.realside@gmail.com"
DEFAULT_SENDER_NAME = "Sales Team"
PAGES_TO_SCRAPE = ["/", "/about", "/about-us", "/pricing", "/products"]
MAX_CONTENT_LENGTH = 3000  # chars per page to send to Claude
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1  # seconds between requests to same domain

YC_DIRECTORY_URL = "https://www.ycombinator.com/companies"
PRODUCTHUNT_URL = "https://www.producthunt.com"


def scrape_page(url: str, session: "requests.Session") -> str | None:
    """Scrape a single page and return cleaned text content."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:MAX_CONTENT_LENGTH] if text else None
    except Exception:
        return None


def scrape_page_html(url: str, session: "requests.Session") -> "BeautifulSoup | None":
    """Scrape a single page and return the parsed BeautifulSoup object."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        return BeautifulSoup(resp.text, "html.parser")
    except Exception:
        return None


def get_session() -> "requests.Session":
    """Create a requests session with a reasonable User-Agent."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ICPListBuilder/1.0)"
    })
    return session


def scrape_company_website(domain: str, session: "requests.Session") -> dict[str, str]:
    """Scrape key pages from a company domain. Returns {page_path: content}."""
    results = {}
    base_url = f"https://{domain}"

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            results[path] = content
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_company_with_anthropic(domain: str, client: anthropic.Anthropic) -> dict[str, str]:
    """Fallback: use Claude to research a company when requests/bs4 unavailable."""
    results = {}
    base_url = f"https://{domain}"

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": f"Fetch and summarize the key content from this URL in 2-3 paragraphs. Focus on what the company does, their products/services, target market, and company size signals: {url}"
                }],
            )
            text = response.content[0].text if response.content else None
            if text:
                results[path] = text
        except Exception:
            continue
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_yc_companies(session: "requests.Session", batch_filter: str | None = None, limit: int = 50) -> list[dict]:
    """
    Scrape the YC company directory for company names and domains.
    Returns a list of dicts with 'company_name', 'domain', and 'source' keys.
    """
    companies = []
    url = YC_DIRECTORY_URL
    if batch_filter:
        url += f"?batch={batch_filter}"

    print(f"Scraping YC directory: {url}")
    soup = scrape_page_html(url, session)
    if not soup:
        print("Warning: Could not fetch YC directory page. The page may require JavaScript.")
        return companies

    # YC directory uses anchor tags linking to /companies/<slug>
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        if "/companies/" in href and href != "/companies" and href != "/companies/":
            # Extract company name from the link text or child elements
            name_tag = link.find("span") or link.find("h4") or link.find("div")
            company_name = name_tag.get_text(strip=True) if name_tag else link.get_text(strip=True)
            if not company_name or len(company_name) > 200:
                continue

            # Try to find a domain from sibling or child elements
            domain = ""
            company_url = link.get("href", "")
            # The directory page links to YC profile pages, not company sites directly
            # We'll try to extract the domain later from the company profile or website scrape

            if company_name and company_name not in [c["company_name"] for c in companies]:
                companies.append({
                    "company_name": company_name,
                    "domain": domain,
                    "source": f"yc:{batch_filter}" if batch_filter else "yc",
                    "_yc_profile": f"https://www.ycombinator.com{company_url}" if company_url.startswith("/") else company_url,
                })

            if len(companies) >= limit:
                break

    # For each company without a domain, try to get it from their YC profile page
    for company in companies:
        if not company["domain"] and company.get("_yc_profile"):
            time.sleep(RATE_LIMIT_DELAY)
            profile_soup = scrape_page_html(company["_yc_profile"], session)
            if profile_soup:
                # Look for external website link on the YC profile
                for a_tag in profile_soup.find_all("a", href=True):
                    href = a_tag.get("href", "")
                    if href.startswith("http") and "ycombinator.com" not in href:
                        parsed = urlparse(href)
                        if parsed.netloc:
                            company["domain"] = parsed.netloc.replace("www.", "")
                            break

    # Clean up internal keys
    for company in companies:
        company.pop("_yc_profile", None)

    # Filter out companies with no domain
    companies = [c for c in companies if c["domain"]]
    print(f"Found {len(companies)} YC companies with domains")
    return companies[:limit]


def scrape_producthunt_launches(session: "requests.Session", limit: int = 50) -> list[dict]:
    """
    Scrape recent ProductHunt launches for company names and domains.
    Returns a list of dicts with 'company_name', 'domain', and 'source' keys.
    """
    companies = []
    url = PRODUCTHUNT_URL

    print(f"Scraping ProductHunt: {url}")
    soup = scrape_page_html(url, session)
    if not soup:
        print("Warning: Could not fetch ProductHunt page. The page may require JavaScript.")
        return companies

    # ProductHunt lists products with links; try to extract product names and outbound links
    seen_domains = set()
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True)

        # Look for external links (getit / visit site links) or product page links
        if href.startswith("http") and "producthunt.com" not in href:
            parsed = urlparse(href)
            domain = parsed.netloc.replace("www.", "")
            if domain and domain not in seen_domains and text:
                seen_domains.add(domain)
                companies.append({
                    "company_name": text[:100],
                    "domain": domain,
                    "source": "producthunt",
                })
        elif href.startswith("/posts/") and text and len(text) < 150:
            # Product page link — store name, try to get domain from product page later
            companies.append({
                "company_name": text,
                "domain": "",
                "source": "producthunt",
                "_ph_url": f"{PRODUCTHUNT_URL}{href}",
            })

        if len(companies) >= limit * 2:  # gather extras since some may lack domains
            break

    # Resolve domains from product pages where missing
    for company in companies:
        if not company["domain"] and company.get("_ph_url"):
            time.sleep(RATE_LIMIT_DELAY)
            page_soup = scrape_page_html(company["_ph_url"], session)
            if page_soup:
                for a_tag in page_soup.find_all("a", href=True):
                    href = a_tag.get("href", "")
                    if href.startswith("http") and "producthunt.com" not in href:
                        parsed = urlparse(href)
                        if parsed.netloc:
                            domain = parsed.netloc.replace("www.", "")
                            if domain not in seen_domains:
                                company["domain"] = domain
                                seen_domains.add(domain)
                                break

    # Clean up internal keys and filter
    for company in companies:
        company.pop("_ph_url", None)

    companies = [c for c in companies if c["domain"]]

    # Deduplicate by domain
    seen = set()
    unique = []
    for c in companies:
        if c["domain"] not in seen:
            seen.add(c["domain"])
            unique.append(c)

    print(f"Found {len(unique)} ProductHunt companies with domains")
    return unique[:limit]


def read_manual_csv(filepath: str) -> list[dict]:
    """Read companies from a manual CSV. Expected columns: domain, company_name."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "domain" not in row:
                print("Error: CSV must have a 'domain' column")
                sys.exit(1)
            rows.append({
                "company_name": row.get("company_name", row["domain"]).strip(),
                "domain": row["domain"].strip(),
                "source": "manual",
            })
    return rows


def score_company(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    scraped_content: dict[str, str],
    icp_description: str,
) -> dict:
    """
    Use Claude to score a company against the ICP, provide a fit reason,
    and suggest an outreach angle. Returns dict with score, fit_reason,
    outreach_angle, and industry.
    """
    content_summary = ""
    for page, text in scraped_content.items():
        content_summary += f"\n--- Content from {domain}{page} ---\n{text}\n"

    if not content_summary.strip():
        content_summary = (
            f"(No web content was available for {domain}. "
            "Evaluate based on the domain name and any knowledge you have.)"
        )

    prompt = f"""You are a B2B sales analyst evaluating whether a company matches an Ideal Customer Profile (ICP).

COMPANY:
- Name: {company_name}
- Domain: {domain}

SCRAPED WEBSITE CONTENT:
{content_summary}

IDEAL CUSTOMER PROFILE (ICP):
{icp_description}

TASK:
1. Score this company from 1-10 on how well they match the ICP (10 = perfect match).
2. Write a concise one-liner explaining WHY they are (or aren't) a good fit.
3. If the score is 5 or above, write a specific outreach angle — a personalized hook for cold outreach based on something concrete from their website or situation. If below 5, write "Low priority - does not match ICP well."
4. Identify their primary industry in 1-3 words.

Return your response as JSON with these exact keys:
- "score": integer 1-10
- "fit_reason": one-sentence explanation of fit
- "outreach_angle": suggested personalized outreach hook
- "industry": 1-3 word industry label
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "score": 5,
            "fit_reason": "Could not parse structured response from Claude.",
            "outreach_angle": "Review manually.",
            "industry": "Unknown",
        }

    # Ensure score is an integer in range
    try:
        result["score"] = max(1, min(10, int(result["score"])))
    except (ValueError, TypeError, KeyError):
        result["score"] = 5

    return result


def write_output_csv(filepath: str, results: list[dict]):
    """Write scored companies to a prioritized CSV, sorted by score descending."""
    if not results:
        print("No results to write.")
        return

    # Sort by score descending
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    fieldnames = [
        "company_name", "domain", "score", "fit_reason",
        "outreach_angle", "industry", "source",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} prospects to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Automated ICP List Builder — scrape public directories, score companies against your ICP, and build a prioritized prospecting list."
    )
    parser.add_argument(
        "--source", required=True, choices=["yc", "producthunt", "manual"],
        help="Data source: 'yc' (YC directory), 'producthunt' (recent launches), or 'manual' (your own CSV)"
    )
    parser.add_argument(
        "--input", default=None,
        help="Input CSV with domain, company_name columns (required for --source manual)"
    )
    parser.add_argument(
        "--output", default="icp_prospects.csv",
        help="Output CSV path (default: icp_prospects.csv)"
    )
    parser.add_argument(
        "--icp-description", required=True,
        help="Description of your Ideal Customer Profile (e.g., 'B2B SaaS companies with 10-200 employees selling developer tools')"
    )
    parser.add_argument(
        "--batch", default=None,
        help="YC batch filter (e.g., 'W24', 'S23'). Only used with --source yc"
    )
    parser.add_argument(
        "--limit", type=int, default=50,
        help="Maximum number of companies to process (default: 50)"
    )
    args = parser.parse_args()

    # Validate arguments
    if args.source == "manual" and not args.input:
        print("Error: --input is required when --source is 'manual'")
        sys.exit(1)

    if not HAS_REQUESTS:
        print("Warning: requests/bs4 not installed. Web scraping will fall back to Claude.")
        print("For best results, install with: pip install requests beautifulsoup4")

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Gather companies from source
    print(f"\n=== ICP List Builder ===")
    print(f"Source: {args.source}")
    print(f"ICP: {args.icp_description}")
    print(f"Limit: {args.limit}")
    print()

    if args.source == "yc":
        if not HAS_REQUESTS:
            print("Error: requests/bs4 are required for YC scraping. Install with: pip install requests beautifulsoup4")
            sys.exit(1)
        session = get_session()
        companies = scrape_yc_companies(session, batch_filter=args.batch, limit=args.limit)
    elif args.source == "producthunt":
        if not HAS_REQUESTS:
            print("Error: requests/bs4 are required for ProductHunt scraping. Install with: pip install requests beautifulsoup4")
            sys.exit(1)
        session = get_session()
        companies = scrape_producthunt_launches(session, limit=args.limit)
    elif args.source == "manual":
        companies = read_manual_csv(args.input)
        companies = companies[:args.limit]
    else:
        print(f"Error: Unknown source '{args.source}'")
        sys.exit(1)

    if not companies:
        print("No companies found from source. Exiting.")
        sys.exit(0)

    print(f"\nEvaluating {len(companies)} companies against ICP...\n")

    results = []
    session = get_session() if HAS_REQUESTS else None

    for i, company in enumerate(companies, 1):
        domain = company["domain"]
        company_name = company["company_name"]
        source = company["source"]

        print(f"[{i}/{len(companies)}] Processing {company_name} ({domain})...")

        # Scrape company website
        print(f"  Scraping {domain}...")
        if HAS_REQUESTS:
            scraped = scrape_company_website(domain, session)
        else:
            print("  (requests/bs4 not installed — using Claude for research)")
            scraped = scrape_company_with_anthropic(domain, client)

        pages_found = len(scraped)
        print(f"  Found content on {pages_found} pages")

        # Score against ICP
        print(f"  Scoring against ICP...")
        evaluation = score_company(
            client=client,
            company_name=company_name,
            domain=domain,
            scraped_content=scraped,
            icp_description=args.icp_description,
        )

        results.append({
            "company_name": company_name,
            "domain": domain,
            "score": evaluation.get("score", 5),
            "fit_reason": evaluation.get("fit_reason", ""),
            "outreach_angle": evaluation.get("outreach_angle", ""),
            "industry": evaluation.get("industry", "Unknown"),
            "source": source,
        })

        print(f"  Score: {evaluation.get('score', 'N/A')}/10")
        print(f"  Fit: {evaluation.get('fit_reason', 'N/A')}")
        print(f"  Angle: {evaluation.get('outreach_angle', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)

    # Print summary
    if results:
        high_fit = [r for r in results if r["score"] >= 7]
        mid_fit = [r for r in results if 4 <= r["score"] < 7]
        low_fit = [r for r in results if r["score"] < 4]
        print(f"\n=== Summary ===")
        print(f"Total evaluated: {len(results)}")
        print(f"High fit (7-10): {len(high_fit)}")
        print(f"Medium fit (4-6): {len(mid_fit)}")
        print(f"Low fit (1-3): {len(low_fit)}")
        print(f"\nOutput saved to: {args.output}")
        print("Review the CSV and prioritize outreach to high-fit companies.")


if __name__ == "__main__":
    main()
