#!/usr/bin/env python3
"""
Job Board Monitor + Outreach Generator

Scrapes public career pages for target companies, looking for job postings
that match keywords related to your product space. When a company posts a
relevant job, that's a buying signal -- this script uses Claude to generate
targeted outreach referencing the specific job posting.

Usage:
    python job_signal_monitor.py --input targets.csv --keywords "data engineer,analytics,ETL" --product "our data integration platform"
    python job_signal_monitor.py --input targets.csv --output signals.csv --keywords "devops,SRE,platform engineer" --sender-email you@company.com --sender-name "Your Name"

Intended to run daily via cron. Outputs new leads + draft emails as CSV.

Input CSV format: domain, company_name, contact_name, contact_title
Output CSV columns: company_name, domain, contact_name, contact_title, job_title, job_url, subject, body, personalization_hook, sender_email, sender_name
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
CAREERS_PATHS = ["/careers", "/jobs", "/open-positions", "/careers/openings", "/jobs/openings", "/join", "/join-us", "/work-with-us"]
MAX_CONTENT_LENGTH = 5000  # chars per page to send to Claude
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1  # seconds between requests to same domain


def scrape_page(url: str, session: "requests.Session") -> str | None:
    """Scrape a single page and return cleaned text content."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove script/style/nav/footer elements
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "iframe"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # Collapse whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:MAX_CONTENT_LENGTH] if text else None
    except Exception:
        return None


def extract_job_links(url: str, session: "requests.Session") -> list[dict]:
    """Extract job listing links from a careers page. Returns list of {title, url}."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "html.parser")
        jobs = []
        # Look for links that likely point to individual job postings
        for a_tag in soup.find_all("a", href=True):
            link_text = a_tag.get_text(strip=True)
            href = a_tag["href"]
            # Skip empty or very short link texts (icons, logos, etc.)
            if not link_text or len(link_text) < 3:
                continue
            # Skip navigation-style links
            if link_text.lower() in ("home", "about", "contact", "blog", "login", "sign up"):
                continue
            # Resolve relative URLs
            full_url = urljoin(url, href)
            jobs.append({"title": link_text, "url": full_url})
        return jobs
    except Exception:
        return []


def scrape_careers_page(domain: str) -> dict:
    """
    Scrape career pages for a company domain.
    Returns {careers_url, page_content, job_links} for the first careers path that works.
    """
    if not HAS_REQUESTS:
        return {}

    base_url = f"https://{domain}"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; JobSignalMonitor/1.0)"
    })

    for path in CAREERS_PATHS:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            job_links = extract_job_links(url, session)
            time.sleep(RATE_LIMIT_DELAY)
            return {
                "careers_url": url,
                "page_content": content,
                "job_links": job_links,
            }
        time.sleep(RATE_LIMIT_DELAY)

    return {}


def scrape_careers_with_anthropic(domain: str, client: anthropic.Anthropic) -> dict:
    """Fallback: use Claude to research careers pages if requests/bs4 unavailable."""
    base_url = f"https://{domain}"

    for path in CAREERS_PATHS:
        url = urljoin(base_url, path)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Fetch and list all job openings from this URL: {url}\n"
                        "For each job, provide the title and URL if available. "
                        "If this page doesn't exist or has no jobs, say 'NO_JOBS_FOUND'."
                    ),
                }],
            )
            text = response.content[0].text if response.content else None
            if text and "NO_JOBS_FOUND" not in text:
                return {
                    "careers_url": url,
                    "page_content": text,
                    "job_links": [],
                }
        except Exception:
            continue
        time.sleep(RATE_LIMIT_DELAY)

    return {}


def filter_jobs_by_keywords(careers_data: dict, keywords: list[str]) -> list[dict]:
    """
    Filter job listings that match any of the provided keywords.
    Checks both extracted job links and raw page content.
    Returns list of {title, url} for matching jobs.
    """
    if not careers_data:
        return []

    keywords_lower = [kw.strip().lower() for kw in keywords if kw.strip()]
    matches = []
    seen_titles = set()

    # Check extracted job links
    for job in careers_data.get("job_links", []):
        title_lower = job["title"].lower()
        for kw in keywords_lower:
            if kw in title_lower:
                if job["title"] not in seen_titles:
                    matches.append({"title": job["title"], "url": job["url"]})
                    seen_titles.add(job["title"])
                break

    # If no links matched, scan page content for keyword mentions
    if not matches:
        page_content = careers_data.get("page_content", "")
        content_lower = page_content.lower()
        for kw in keywords_lower:
            if kw in content_lower:
                # Found keyword in page content but no specific link; use careers page URL
                matches.append({
                    "title": f"[Keyword match: {kw}]",
                    "url": careers_data.get("careers_url", ""),
                })
                break

    return matches


def generate_outreach_email(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str | None,
    contact_title: str | None,
    matching_jobs: list[dict],
    careers_content: str,
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> list[dict]:
    """
    Use Claude to analyze matching job postings and generate targeted outreach emails.
    Returns one email dict per matching job.
    """
    results = []

    jobs_summary = "\n".join(
        f"- {job['title']} ({job['url']})" for job in matching_jobs
    )

    recipient = contact_name or "the hiring manager"
    title_line = f"Their title: {contact_title}" if contact_title else ""

    prompt = f"""You are a world-class B2B sales copywriter specializing in signal-based selling.
A target company has posted job listings that indicate they may need our product.
Write a personalized cold email that references the specific job posting as a buying signal.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Recipient: {recipient}
{title_line}

MATCHING JOB POSTINGS (buying signals):
{jobs_summary}

CAREERS PAGE CONTEXT:
{careers_content[:3000]}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

RULES:
1. Subject line must reference the job posting or hiring signal directly
2. Opening line must connect their hiring activity to a pain point your product solves
3. Keep the email under 150 words
4. Include exactly ONE clear call-to-action: a request for a 15-minute call
5. Tone: professional but conversational, not salesy
6. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
7. Sign off with the sender's name

For EACH matching job posting, return a JSON object. Return a JSON array of objects, each with these exact keys:
- "job_title": the job title that triggered this signal
- "job_url": the URL of the job posting
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining what buying signal you identified and why it matters

Return ONLY the JSON array, no other text.
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        # Try to find raw JSON array
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            parsed = [parsed]
        results = parsed
    except json.JSONDecodeError:
        # Fallback: return one result per matching job with raw text
        for job in matching_jobs:
            results.append({
                "job_title": job["title"],
                "job_url": job["url"],
                "subject": f"Noticed you're hiring: {job['title']}",
                "body": text,
                "personalization_hook": "Could not parse structured response",
            })

    return results


def read_input_csv(filepath: str) -> list[dict]:
    """Read target companies from CSV. Expected columns: domain, company_name (optional: contact_name, contact_title)."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "domain" not in row:
                print("Error: CSV must have a 'domain' column")
                sys.exit(1)
            rows.append(row)
    return rows


def write_output_csv(filepath: str, results: list[dict]):
    """Write generated outreach emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_title",
        "job_title", "job_url", "subject", "body", "personalization_hook",
        "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} outreach emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Job Board Monitor + Outreach Generator: detect hiring signals and generate targeted outreach"
    )
    parser.add_argument("--input", required=True, help="Input CSV with target companies (must have 'domain' column)")
    parser.add_argument("--output", default="job_signal_emails.csv", help="Output CSV path (default: job_signal_emails.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL, help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME, help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product", help="Short description of your product/service for context")
    parser.add_argument("--keywords", required=True, help="Comma-separated list of job title keywords to watch for (e.g. 'data engineer,analytics,ETL')")
    args = parser.parse_args()

    # Parse keywords
    keywords = [kw.strip() for kw in args.keywords.split(",") if kw.strip()]
    if not keywords:
        print("Error: --keywords must contain at least one keyword")
        sys.exit(1)

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Read targets
    targets = read_input_csv(args.input)
    print(f"Loaded {len(targets)} target companies from {args.input}")
    print(f"Watching for keywords: {', '.join(keywords)}")

    results = []
    signals_found = 0

    for i, target in enumerate(targets, 1):
        domain = target["domain"].strip()
        company_name = target.get("company_name", domain).strip()
        contact_name = target.get("contact_name", "").strip() or None
        contact_title = target.get("contact_title", "").strip() or None

        print(f"\n[{i}/{len(targets)}] Scanning {company_name} ({domain})...")

        # Scrape careers pages
        print(f"  Checking careers pages for {domain}...")
        if HAS_REQUESTS:
            careers_data = scrape_careers_page(domain)
        else:
            print("  (requests/bs4 not installed -- using Claude for research)")
            careers_data = scrape_careers_with_anthropic(domain, client)

        if not careers_data:
            print(f"  No careers page found for {domain}")
            continue

        print(f"  Found careers page: {careers_data.get('careers_url', 'N/A')}")
        link_count = len(careers_data.get("job_links", []))
        print(f"  Extracted {link_count} job links")

        # Filter by keywords
        matching_jobs = filter_jobs_by_keywords(careers_data, keywords)
        if not matching_jobs:
            print(f"  No keyword matches found for {domain}")
            continue

        print(f"  ** {len(matching_jobs)} matching job signal(s) detected! **")
        for job in matching_jobs:
            print(f"     - {job['title']}")
        signals_found += len(matching_jobs)

        # Generate outreach emails
        print(f"  Generating outreach emails...")
        emails = generate_outreach_email(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_title=contact_title,
            matching_jobs=matching_jobs,
            careers_content=careers_data.get("page_content", ""),
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        for email in emails:
            results.append({
                "company_name": company_name,
                "domain": domain,
                "contact_name": contact_name or "",
                "contact_title": contact_title or "",
                "job_title": email.get("job_title", ""),
                "job_url": email.get("job_url", ""),
                "subject": email.get("subject", ""),
                "body": email.get("body", ""),
                "personalization_hook": email.get("personalization_hook", ""),
                "sender_email": args.sender_email,
                "sender_name": args.sender_name,
            })

        for email in emails:
            print(f"  -> Subject: {email.get('subject', 'N/A')}")
            print(f"     Hook: {email.get('personalization_hook', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print(f"\nScan complete. Found {signals_found} buying signal(s) across {len(targets)} companies.")
    print("Review the generated emails before sending.")


if __name__ == "__main__":
    main()
