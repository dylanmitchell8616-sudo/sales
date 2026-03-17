#!/usr/bin/env python3
"""
Inbound Lead Research + Instant Response Drafts

When a new inbound lead comes in (via CSV), this script instantly:
  - Scrapes their website and researches the company
  - Identifies their likely pain points based on the form submission + company info
  - Drafts a personalized response that references their company specifically
  - Suggests meeting times for the next 3 business days

Speed-to-lead is the #1 predictor of inbound conversion.

Usage:
    python inbound_responder.py --input leads.csv --output responses.csv
    python inbound_responder.py --input leads.csv --product "AI sales platform" --calendar-link "https://calendly.com/you/30min"
"""

import argparse
import csv
import json
import os
import sys
import time
import re
from datetime import datetime, timedelta
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


def get_next_business_days(count: int = 3) -> list[datetime]:
    """Return the next N business days from today."""
    days = []
    current = datetime.now() + timedelta(days=1)
    while len(days) < count:
        if current.weekday() < 5:  # Monday=0 through Friday=4
            days.append(current)
        current += timedelta(days=1)
    return days


def format_suggested_times(days: list[datetime], calendar_link: str | None = None) -> str:
    """Format suggested meeting times as a readable string."""
    slots = []
    for day in days:
        label = day.strftime("%A, %B %-d")
        slots.append(f"{label} at 10:00 AM or 2:00 PM")

    times_text = "; ".join(slots)
    if calendar_link:
        times_text += f" | Or book directly: {calendar_link}"
    return times_text


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
        "User-Agent": "Mozilla/5.0 (compatible; InboundResponder/1.0)"
    })

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            results[path] = content
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_company_with_anthropic(domain: str, client: anthropic.Anthropic) -> dict[str, str]:
    """Fallback: use Claude for research if requests/bs4 unavailable."""
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


def generate_response(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str,
    contact_email: str,
    contact_title: str | None,
    form_message: str,
    scraped_content: dict[str, str],
    sender_name: str,
    sender_email: str,
    product_description: str,
    suggested_times: str,
    calendar_link: str | None,
) -> dict:
    """Use Claude to analyze the inbound lead and generate a fast, personalized response."""

    content_summary = ""
    for page, text in scraped_content.items():
        content_summary += f"\n--- Content from {domain}{page} ---\n{text}\n"

    if not content_summary.strip():
        content_summary = f"(No web content was available for {domain}. Generate based on the domain name, form message, and any knowledge you have.)"

    title_line = f"- Title: {contact_title}" if contact_title else ""
    calendar_instruction = ""
    if calendar_link:
        calendar_instruction = f"\n8. Include this calendar booking link in the CTA: {calendar_link}"

    prompt = f"""You are a world-class B2B sales rep responding to an INBOUND lead. This person has already expressed interest by filling out a form. Your job is to respond quickly with a personalized, relevant reply that moves toward a meeting.

INBOUND LEAD INFO:
- Company: {company_name}
- Domain: {domain}
- Contact: {contact_name}
- Email: {contact_email}
{title_line}
- Their form submission: "{form_message}"

SCRAPED WEBSITE CONTENT (their company):
{content_summary}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product/Service: {product_description}

AVAILABLE MEETING TIMES:
{suggested_times}

RULES:
1. This is a RESPONSE to their inquiry -- acknowledge what they asked about in the form
2. Reference something SPECIFIC about their company from the scraped content to show you did your homework
3. Identify 2-3 likely pain points based on their form message + company context
4. Keep the email under 200 words
5. Suggest specific meeting times from the list above
6. Tone: warm, helpful, and responsive -- not salesy. They came to YOU.
7. Sign off with the sender's name{calendar_instruction}

Return your response as JSON with these exact keys:
- "subject": the email subject line (should reference their inquiry)
- "body": the full email body (plain text, use \\n for newlines)
- "pain_points_identified": a comma-separated list of 2-3 pain points you identified
- "personalization_hook": one sentence explaining what specific company detail you referenced and why
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
            "subject": f"Re: Your inquiry about {product_description}",
            "body": text,
            "pain_points_identified": "Could not parse structured response",
            "personalization_hook": "Could not parse structured response",
        }

    return result


def read_input_csv(filepath: str) -> list[dict]:
    """Read inbound leads from CSV. Expected columns: domain, company_name, contact_name, contact_title, contact_email, form_message."""
    rows = []
    required_columns = {"domain", "contact_email"}
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames:
            missing = required_columns - set(reader.fieldnames)
            if missing:
                print(f"Error: CSV is missing required columns: {', '.join(missing)}")
                sys.exit(1)
        for row in reader:
            rows.append(row)
    return rows


def write_output_csv(filepath: str, results: list[dict]):
    """Write generated responses to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_email",
        "subject", "body", "pain_points_identified", "suggested_times",
        "personalization_hook", "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} responses to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Inbound Lead Research + Instant Response Drafts")
    parser.add_argument("--input", required=True, help="Input CSV with inbound leads (requires: domain, contact_email)")
    parser.add_argument("--output", default="inbound_responses.csv", help="Output CSV path (default: inbound_responses.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL, help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME, help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product", help="Short description of your product/service for context")
    parser.add_argument("--calendar-link", default=None, help="Calendly or scheduling URL to include in responses")
    args = parser.parse_args()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Read inbound leads
    leads = read_input_csv(args.input)
    print(f"Loaded {len(leads)} inbound leads from {args.input}")

    # Pre-compute suggested meeting times
    business_days = get_next_business_days(3)
    suggested_times = format_suggested_times(business_days, args.calendar_link)
    print(f"Suggested meeting times: {suggested_times}")

    results = []
    for i, lead in enumerate(leads, 1):
        domain = lead["domain"].strip()
        company_name = lead.get("company_name", domain).strip()
        contact_name = lead.get("contact_name", "").strip() or "there"
        contact_title = lead.get("contact_title", "").strip() or None
        contact_email = lead["contact_email"].strip()
        form_message = lead.get("form_message", "").strip() or "General inquiry"

        print(f"\n[{i}/{len(leads)}] Processing inbound lead from {contact_name} at {company_name} ({domain})...")

        # Scrape company website
        print(f"  Scraping {domain}...")
        if HAS_REQUESTS:
            scraped = scrape_company(domain)
        else:
            print("  (requests/bs4 not installed -- using Claude for research)")
            scraped = scrape_company_with_anthropic(domain, client)

        pages_found = len(scraped)
        print(f"  Found content on {pages_found} pages")

        # Generate personalized response
        print(f"  Generating personalized response...")
        response = generate_response(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_email=contact_email,
            contact_title=contact_title,
            form_message=form_message,
            scraped_content=scraped,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
            suggested_times=suggested_times,
            calendar_link=args.calendar_link,
        )

        results.append({
            "company_name": company_name,
            "domain": domain,
            "contact_name": contact_name,
            "contact_email": contact_email,
            "subject": response.get("subject", ""),
            "body": response.get("body", ""),
            "pain_points_identified": response.get("pain_points_identified", ""),
            "suggested_times": suggested_times,
            "personalization_hook": response.get("personalization_hook", ""),
            "sender_email": args.sender_email,
            "sender_name": args.sender_name,
        })

        print(f"  Done -- Subject: {response.get('subject', 'N/A')}")
        print(f"  Pain points: {response.get('pain_points_identified', 'N/A')}")
        print(f"  Hook: {response.get('personalization_hook', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the generated responses before sending -- speed matters, but accuracy matters more.")


if __name__ == "__main__":
    main()
