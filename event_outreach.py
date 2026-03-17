#!/usr/bin/env python3
"""
Conference/Event Attendee Outreach Generator

Scrapes public speaker lists, attendee lists, and sponsor lists from conference
websites, cross-references with target accounts, and uses Claude to generate
personalized pre-event or post-event outreach emails.

Usage:
    python event_outreach.py --event-url https://conference.example.com --event-name "TechConf 2026"
    python event_outreach.py --event-url https://conference.example.com --event-name "TechConf 2026" --mode post-event --targets accounts.csv
    python event_outreach.py --event-url https://conference.example.com --event-name "TechConf 2026" --sender-email you@company.com --sender-name "Your Name"
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
EVENT_PATHS = ["/", "/speakers", "/sponsors", "/agenda", "/schedule", "/attendees", "/exhibitors", "/partners"]
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


def scrape_event(event_url: str) -> dict[str, str]:
    """Scrape key pages from an event website. Returns {page_path: content}."""
    if not HAS_REQUESTS:
        return {}

    results = {}
    parsed = urlparse(event_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    # Include the original path as well so we always hit the provided URL
    base_path = parsed.path.rstrip("/")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; EventOutreach/1.0)"
    })

    paths_to_try = list(EVENT_PATHS)
    # Also try paths relative to the event's base path (e.g. /events/conf2026/speakers)
    if base_path and base_path != "/":
        for p in EVENT_PATHS:
            combined = base_path + p
            if combined not in paths_to_try:
                paths_to_try.append(combined)

    for path in paths_to_try:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            results[path] = content
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_event_with_anthropic(event_url: str, client: anthropic.Anthropic) -> dict[str, str]:
    """Fallback: use Claude to research the event if requests/bs4 unavailable."""
    results = {}
    parsed = urlparse(event_url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"
    base_path = parsed.path.rstrip("/")

    paths_to_try = list(EVENT_PATHS)
    if base_path and base_path != "/":
        for p in EVENT_PATHS:
            combined = base_path + p
            if combined not in paths_to_try:
                paths_to_try.append(combined)

    for path in paths_to_try:
        url = urljoin(base_url, path)
        try:
            response = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": (
                        f"Fetch and summarize the key content from this URL in 2-3 paragraphs. "
                        f"Focus on speakers, sponsors, attendees, session topics, and company names: {url}"
                    ),
                }],
            )
            text = response.content[0].text if response.content else None
            if text:
                results[path] = text
        except Exception:
            continue
        time.sleep(RATE_LIMIT_DELAY)

    return results


def extract_people_and_companies(
    client: anthropic.Anthropic,
    scraped_content: dict[str, str],
    event_name: str,
) -> list[dict]:
    """Use Claude to extract speakers, sponsors, and notable attendees from scraped event content."""

    content_summary = ""
    for page, text in scraped_content.items():
        content_summary += f"\n--- Content from {page} ---\n{text}\n"

    if not content_summary.strip():
        return []

    prompt = f"""You are an expert at extracting structured data from conference websites.

EVENT: {event_name}

SCRAPED WEBSITE CONTENT:
{content_summary}

Extract every speaker, sponsor company, and attendee you can find. For each person or company, return a JSON array of objects with these keys:
- "company_name": the company/organization name
- "person_name": the person's full name (use "" if only a company/sponsor is listed)
- "role_at_event": one of "speaker", "sponsor", "exhibitor", "attendee", or "organizer"
- "session_topic": the title of their talk/session if available (use "" if not)

RULES:
1. Include ALL speakers, sponsors, and exhibitors you can identify
2. If a sponsor is listed without a specific person, still include it with an empty person_name
3. Be thorough — extract every name and company you see
4. Return ONLY the JSON array, no other text

Return your response as a JSON array."""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON from response (handle markdown code blocks)
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        people = json.loads(text)
    except json.JSONDecodeError:
        people = []

    return people


def load_target_accounts(filepath: str) -> set[str]:
    """Load target account names from a CSV file. Looks for 'company_name' or 'domain' column."""
    targets = set()
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "company_name" in row and row["company_name"].strip():
                targets.add(row["company_name"].strip().lower())
            if "domain" in row and row["domain"].strip():
                targets.add(row["domain"].strip().lower())
    return targets


def cross_reference_targets(people: list[dict], targets: set[str]) -> list[dict]:
    """Filter people/companies list to only those matching target accounts."""
    matched = []
    for person in people:
        company = person.get("company_name", "").lower()
        if any(t in company or company in t for t in targets if t and company):
            matched.append(person)
    return matched


def generate_outreach_email(
    client: anthropic.Anthropic,
    person: dict,
    event_name: str,
    mode: str,
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> dict:
    """Use Claude to generate a pre-event or post-event outreach email."""

    company_name = person.get("company_name", "Unknown Company")
    person_name = person.get("person_name", "")
    role_at_event = person.get("role_at_event", "attendee")
    session_topic = person.get("session_topic", "")

    recipient = person_name or f"the {company_name} team"
    session_line = f"- Session/Talk: {session_topic}" if session_topic else ""

    if mode == "pre-event":
        tone_guidance = (
            "This is a PRE-EVENT outreach email. The event has not happened yet. "
            "Express excitement about attending, reference their role/talk at the event, "
            "and suggest meeting up during the conference."
        )
    else:
        tone_guidance = (
            "This is a POST-EVENT follow-up email. The event has already happened. "
            "Reference their role/talk at the event, mention a specific takeaway or highlight, "
            "and suggest a follow-up conversation to continue the discussion."
        )

    prompt = f"""You are a world-class B2B sales copywriter specializing in event-based outreach.

{tone_guidance}

EVENT INFO:
- Event: {event_name}
- Recipient: {recipient}
- Company: {company_name}
- Role at event: {role_at_event}
{session_line}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

RULES:
1. Subject line must reference the event AND something specific about the person/company
2. Opening line must NOT be generic — reference the event and their specific involvement
3. Keep the email under 150 words
4. Include exactly ONE clear call-to-action
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
        json_match = re.search(r"\{.*\}", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        result = {
            "subject": f"{event_name} — connecting with {company_name}",
            "body": text,
            "personalization_hook": "Could not parse structured response",
        }

    return result


def write_output_csv(filepath: str, results: list[dict]):
    """Write generated outreach emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "person_name", "role_at_event", "event_name",
        "subject", "body", "personalization_hook", "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} outreach emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="Conference/Event Attendee Outreach Generator")
    parser.add_argument("--event-url", required=True, help="URL of the conference/event website")
    parser.add_argument("--event-name", required=True, help="Name of the conference/event")
    parser.add_argument("--mode", default="pre-event", choices=["pre-event", "post-event"],
                        help="Outreach mode: pre-event or post-event (default: pre-event)")
    parser.add_argument("--targets", default=None,
                        help="Optional CSV of target accounts to cross-reference (columns: company_name and/or domain)")
    parser.add_argument("--output", default="event_outreach_emails.csv", help="Output CSV path (default: event_outreach_emails.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL,
                        help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME,
                        help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product",
                        help="Short description of your product/service for context")
    args = parser.parse_args()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Scrape event website
    print(f"Scraping event website: {args.event_url}")
    if HAS_REQUESTS:
        scraped = scrape_event(args.event_url)
    else:
        print("  (requests/bs4 not installed — using Claude for research)")
        scraped = scrape_event_with_anthropic(args.event_url, client)

    pages_found = len(scraped)
    print(f"  Found content on {pages_found} pages")

    if not scraped:
        print("Error: Could not scrape any content from the event website.")
        print("Check the URL and try again.")
        sys.exit(1)

    # Extract people and companies from scraped content
    print(f"Extracting speakers, sponsors, and attendees...")
    people = extract_people_and_companies(client, scraped, args.event_name)
    print(f"  Found {len(people)} people/companies")

    if not people:
        print("No speakers, sponsors, or attendees found on the event website.")
        sys.exit(0)

    # Cross-reference with target accounts if provided
    if args.targets:
        print(f"Cross-referencing with target accounts from {args.targets}...")
        targets = load_target_accounts(args.targets)
        print(f"  Loaded {len(targets)} target accounts")
        matched = cross_reference_targets(people, targets)
        print(f"  {len(matched)} matches found with target accounts")
        if matched:
            people = matched
        else:
            print("  No matches found — generating outreach for all extracted contacts")

    # Generate outreach emails
    results = []
    for i, person in enumerate(people, 1):
        company_name = person.get("company_name", "Unknown Company")
        person_name = person.get("person_name", "")
        role_at_event = person.get("role_at_event", "attendee")
        display_name = person_name or company_name

        print(f"\n[{i}/{len(people)}] Generating {args.mode} outreach for {display_name} ({company_name})...")

        email = generate_outreach_email(
            client=client,
            person=person,
            event_name=args.event_name,
            mode=args.mode,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        results.append({
            "company_name": company_name,
            "person_name": person_name,
            "role_at_event": role_at_event,
            "event_name": args.event_name,
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
            "personalization_hook": email.get("personalization_hook", ""),
            "sender_email": args.sender_email,
            "sender_name": args.sender_name,
        })

        print(f"  Subject: {email.get('subject', 'N/A')}")
        print(f"  Hook: {email.get('personalization_hook', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the generated outreach emails before sending.")


if __name__ == "__main__":
    main()
