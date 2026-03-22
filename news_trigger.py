#!/usr/bin/env python3
"""
News/PR Trigger Outreach Generator

Monitors Google News RSS feeds for target accounts, detects trigger events
(funding announcements, product launches, leadership changes, acquisitions,
expansions), and uses Claude to generate timely outreach emails tied to the news.

Usage:
    python news_trigger.py --input targets.csv --output news_triggered_emails.csv
    python news_trigger.py --input targets.csv --sender-email you@company.com --sender-name "Your Name" --product "our CRM platform" --days-back 14
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

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
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search?q={query}"
MAX_ARTICLES_PER_COMPANY = 5
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1  # seconds between requests

TRIGGER_TYPES = [
    "funding",
    "product_launch",
    "leadership_change",
    "acquisition",
    "expansion",
    "partnership",
    "other",
]


def fetch_news_feed(company_name: str, session: "requests.Session") -> list[dict]:
    """Fetch and parse Google News RSS feed for a company. Returns list of article dicts."""
    query = quote_plus(company_name)
    url = GOOGLE_NEWS_RSS_URL.format(query=query)

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT)
        if resp.status_code != 200:
            print(f"  Warning: Google News returned status {resp.status_code} for {company_name}")
            return []
    except Exception as e:
        print(f"  Warning: Failed to fetch news for {company_name}: {e}")
        return []

    articles = []
    try:
        root = ET.fromstring(resp.content)
        channel = root.find("channel")
        if channel is None:
            return []

        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            pub_date_el = item.find("pubDate")

            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.text.strip() if link_el is not None and link_el.text else ""
            pub_date_str = pub_date_el.text.strip() if pub_date_el is not None and pub_date_el.text else ""

            pub_date = None
            if pub_date_str:
                try:
                    pub_date = parsedate_to_datetime(pub_date_str)
                except Exception:
                    pub_date = None

            if title:
                articles.append({
                    "title": title,
                    "url": link,
                    "pub_date": pub_date,
                    "pub_date_str": pub_date_str,
                })
    except ET.ParseError as e:
        print(f"  Warning: Failed to parse RSS XML for {company_name}: {e}")
        return []

    return articles


def filter_recent_articles(articles: list[dict], days_back: int) -> list[dict]:
    """Filter articles to only those published within the lookback window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    recent = []
    for article in articles:
        pub_date = article.get("pub_date")
        if pub_date is None:
            # Include articles with no parseable date (let Claude decide relevance)
            recent.append(article)
        elif pub_date >= cutoff:
            recent.append(article)
    return recent[:MAX_ARTICLES_PER_COMPANY]


def classify_and_generate_email(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    articles: list[dict],
    contact_name: str | None,
    contact_title: str | None,
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> list[dict]:
    """Use Claude to classify trigger type and generate outreach for each relevant article."""
    articles_text = ""
    for i, article in enumerate(articles, 1):
        date_str = ""
        if article["pub_date"]:
            date_str = article["pub_date"].strftime("%Y-%m-%d")
        elif article["pub_date_str"]:
            date_str = article["pub_date_str"]
        articles_text += f"\n{i}. Headline: {article['title']}\n   URL: {article['url']}\n   Date: {date_str}\n"

    recipient = contact_name or "the team"
    title_line = f"Their title: {contact_title}" if contact_title else ""

    prompt = f"""You are a world-class B2B sales copywriter who specializes in trigger-based outreach.

COMPANY INFO:
- Company: {company_name}
- Domain: {domain}
- Recipient: {recipient}
{title_line}

RECENT NEWS ARTICLES:
{articles_text}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

TASK:
Analyze these news articles and identify which ones represent meaningful trigger events for sales outreach. Trigger types include:
- "funding" — funding rounds, investment announcements
- "product_launch" — new product or feature launches
- "leadership_change" — new hires, promotions, departures of executives
- "acquisition" — mergers, acquisitions, or being acquired
- "expansion" — new offices, market expansion, international growth
- "partnership" — strategic partnerships, integrations
- "other" — other newsworthy business events worth reaching out about

For each relevant article (skip articles that are not useful trigger events), generate a personalized outreach email.

RULES:
1. Only include articles that represent genuine trigger events worth outreaching about
2. Subject line must reference the specific news
3. Opening line must directly tie to the news event — no generic openers
4. Keep each email under 150 words
5. Include exactly ONE clear call-to-action: ask what days work for a call (never include a calendly or scheduling link)
6. Tone: professional but conversational, not salesy
7. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
8. Sign off with the sender's name

Return your response as a JSON array. Each element should have these exact keys:
- "article_index": the 1-based index of the article from the list above
- "trigger_type": one of {json.dumps(TRIGGER_TYPES)}
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining what specific detail you referenced and why

If none of the articles are relevant trigger events, return an empty array: []
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
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        email_results = json.loads(text)
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse Claude response as JSON for {company_name}")
        return []

    if not isinstance(email_results, list):
        return []

    # Map results back to article data
    output = []
    for item in email_results:
        idx = item.get("article_index", 0) - 1
        if idx < 0 or idx >= len(articles):
            continue

        article = articles[idx]
        date_str = ""
        if article["pub_date"]:
            date_str = article["pub_date"].strftime("%Y-%m-%d")
        elif article["pub_date_str"]:
            date_str = article["pub_date_str"]

        trigger_type = item.get("trigger_type", "other")
        if trigger_type not in TRIGGER_TYPES:
            trigger_type = "other"

        output.append({
            "company_name": company_name,
            "domain": domain,
            "contact_name": contact_name or "",
            "contact_title": contact_title or "",
            "news_headline": article["title"],
            "news_url": article["url"],
            "news_date": date_str,
            "trigger_type": trigger_type,
            "subject": item.get("subject", ""),
            "body": item.get("body", ""),
            "personalization_hook": item.get("personalization_hook", ""),
            "sender_email": sender_email,
            "sender_name": sender_name,
        })

    return output


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
    """Write generated trigger emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_title",
        "news_headline", "news_url", "news_date", "trigger_type",
        "subject", "body", "personalization_hook", "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} triggered emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(description="News/PR Trigger Outreach Generator")
    parser.add_argument("--input", required=True, help="Input CSV with target companies (must have 'domain' and 'company_name' columns)")
    parser.add_argument("--output", default="news_triggered_emails.csv", help="Output CSV path (default: news_triggered_emails.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL, help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME, help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product", help="Short description of your product/service for context")
    parser.add_argument("--days-back", type=int, default=7, help="Number of days to look back for news (default: 7)")
    args = parser.parse_args()

    # Validate dependencies
    if not HAS_REQUESTS:
        print("Error: requests and bs4 packages required. Install with: pip install requests beautifulsoup4")
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
    print(f"Looking back {args.days_back} days for news triggers\n")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; NewsTrigger/1.0)"
    })

    results = []
    for i, target in enumerate(targets, 1):
        domain = target["domain"].strip()
        company_name = target.get("company_name", domain).strip()
        contact_name = target.get("contact_name", "").strip() or None
        contact_title = target.get("contact_title", "").strip() or None

        print(f"[{i}/{len(targets)}] Processing {company_name} ({domain})...")

        # Fetch news
        print(f"  Fetching Google News RSS feed...")
        articles = fetch_news_feed(company_name, session)
        time.sleep(RATE_LIMIT_DELAY)

        if not articles:
            print(f"  No news articles found. Skipping.")
            continue

        # Filter to recent articles
        recent = filter_recent_articles(articles, args.days_back)
        print(f"  Found {len(articles)} total articles, {len(recent)} within last {args.days_back} days")

        if not recent:
            print(f"  No recent articles. Skipping.")
            continue

        # Classify triggers and generate emails
        print(f"  Classifying triggers and generating outreach...")
        emails = classify_and_generate_email(
            client=client,
            company_name=company_name,
            domain=domain,
            articles=recent,
            contact_name=contact_name,
            contact_title=contact_title,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        if emails:
            results.extend(emails)
            for email in emails:
                print(f"  + [{email['trigger_type']}] {email['news_headline'][:60]}...")
                print(f"    Subject: {email['subject']}")
        else:
            print(f"  No actionable trigger events found in recent news.")

    # Write output
    write_output_csv(args.output, results)
    print(f"\nDone! Generated {len(results)} trigger-based emails across {len(targets)} companies.")
    print("Review the generated emails before sending.")


if __name__ == "__main__":
    main()
