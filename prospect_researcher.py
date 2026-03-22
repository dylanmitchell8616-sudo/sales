#!/usr/bin/env python3
"""
Prospect Website Scraper + Personalized Email Generator

Takes a CSV of target company domains, scrapes their public web pages,
and uses Claude to generate hyper-personalized cold emails.

Usage:
    python prospect_researcher.py --input targets.csv --output emails.csv
    python prospect_researcher.py --input targets.csv --output emails.csv --sender-email you@company.com --sender-name "Your Name"
"""

import argparse
import csv
import json
import os
import sys
import time
import re
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
PAGES_TO_SCRAPE = ["/", "/about", "/about-us", "/blog", "/careers", "/products", "/pricing"]
MAX_CONTENT_LENGTH = 3000  # chars per page to send to Claude
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


def scrape_company(domain: str) -> dict[str, str]:
    """Scrape key pages from a company domain. Returns {page_path: content}."""
    if not HAS_REQUESTS:
        return {}

    results = {}
    base_url = f"https://{domain}"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ProspectResearcher/1.0)"
    })

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            results[path] = content
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_company_with_anthropic(domain: str, client: anthropic.Anthropic) -> dict[str, str]:
    """Fallback: use Claude's web fetch capabilities via tool_use if requests/bs4 unavailable."""
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
                    "content": f"Fetch and summarize the key content from this URL in 2-3 paragraphs. Focus on what the company does, their products/services, recent news, and any notable content: {url}"
                }],
            )
            text = response.content[0].text if response.content else None
            if text:
                results[path] = text
        except Exception:
            continue
        time.sleep(RATE_LIMIT_DELAY)

    return results


def generate_email(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    scraped_content: dict[str, str],
    contact_name: str | None,
    contact_title: str | None,
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> dict:
    """Use Claude to generate a personalized cold email based on scraped content."""

    content_summary = ""
    for page, text in scraped_content.items():
        content_summary += f"\n--- Content from {domain}{page} ---\n{text}\n"

    if not content_summary.strip():
        content_summary = f"(No web content was available for {domain}. Generate based on the domain name and any knowledge you have.)"

    recipient = contact_name or "the team"
    title_line = f"Their title: {contact_title}" if contact_title else ""

    prompt = f"""You are a world-class B2B sales copywriter. Write a short, personalized cold email to book a meeting.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Recipient: {recipient}
{title_line}

SCRAPED WEBSITE CONTENT:
{content_summary}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

RULES:
1. Subject line must reference something SPECIFIC from their website (a blog post title, product feature, job listing, company mission, etc.)
2. Opening line must NOT be "I hope this email finds you well" or any generic opener — reference their content directly
3. Keep the email under 150 words
4. Include exactly ONE clear call-to-action: ask what days work for a call (never include a calendly or scheduling link)
5. Tone: professional but conversational, not salesy
6. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
7. Sign off with the sender's name

Return your response as JSON with these exact keys:
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining what specific detail you referenced and why
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        # Try to find raw JSON
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "subject": f"Quick question about {company_name}",
            "body": text,
            "personalization_hook": "Could not parse structured response",
        }

    return result


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
    """Write generated emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_title",
        "subject", "body", "personalization_hook", "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Prospect Website Scraper + Personalized Email Generator")
    parser.add_argument("--input", required=True, help="Input CSV with target companies (must have 'domain' column)")
    parser.add_argument("--output", default="generated_emails.csv", help="Output CSV path (default: generated_emails.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL, help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME, help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product", help="Short description of your product/service for context")
    args = parser.parse_args()

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

    results = []
    for i, target in enumerate(targets, 1):
        domain = target["domain"].strip()
        company_name = target.get("company_name", domain).strip()
        contact_name = target.get("contact_name", "").strip() or None
        contact_title = target.get("contact_title", "").strip() or None

        print(f"\n[{i}/{len(targets)}] Processing {company_name} ({domain})...")

        # Scrape
        print(f"  Scraping {domain}...")
        if HAS_REQUESTS:
            scraped = scrape_company(domain)
        else:
            print("  (requests/bs4 not installed — using Claude for research)")
            scraped = scrape_company_with_anthropic(domain, client)

        pages_found = len(scraped)
        print(f"  Found content on {pages_found} pages")

        # Generate email
        print(f"  Generating personalized email...")
        email = generate_email(
            client=client,
            company_name=company_name,
            domain=domain,
            scraped_content=scraped,
            contact_name=contact_name,
            contact_title=contact_title,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        results.append({
            "company_name": company_name,
            "domain": domain,
            "contact_name": contact_name or "",
            "contact_title": contact_title or "",
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
            "personalization_hook": email.get("personalization_hook", ""),
            "sender_email": args.sender_email,
            "sender_name": args.sender_name,
        })

        print(f"  ✓ Subject: {email.get('subject', 'N/A')}")
        print(f"  ✓ Hook: {email.get('personalization_hook', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the generated emails before sending.")


if __name__ == "__main__":
    main()
