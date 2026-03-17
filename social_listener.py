#!/usr/bin/env python3
"""
LinkedIn/Twitter Content Monitor -> Warm Outreach Generator

Monitors public RSS feeds, blog posts, or social profiles of target prospects.
When a prospect posts about a topic related to your product, Claude generates
a reply or email that references their specific take.

Usage:
    python social_listener.py --input targets.csv --output social_outreach_emails.csv
    python social_listener.py --input targets.csv --product "our analytics platform" --topics "data,AI,automation" --days-back 30
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
DEFAULT_DAYS_BACK = 14
FEED_PATHS = ["/feed", "/rss", "/blog/feed", "/blog/rss.xml", "/feed/rss", "/feed/atom",
              "/rss.xml", "/atom.xml", "/blog/atom.xml", "/blog/rss", "/feed.xml"]
BLOG_PATHS = ["/blog", "/blog/", "/posts", "/articles", "/news", "/insights"]
MAX_CONTENT_LENGTH = 3000  # chars per post to send to Claude
MAX_POSTS_PER_PROSPECT = 5
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1  # seconds between requests to same domain

# Common RSS/Atom XML namespaces
ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}


def discover_feed_url(domain: str, session: "requests.Session",
                      blog_url: str | None = None, rss_url: str | None = None) -> str | None:
    """Try to discover an RSS/Atom feed URL for a domain."""
    base_url = f"https://{domain}"

    # If an explicit RSS URL was provided, try it first
    if rss_url:
        rss_url = rss_url.strip()
        if not rss_url.startswith("http"):
            rss_url = urljoin(base_url, rss_url)
        try:
            resp = session.get(rss_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200 and _looks_like_feed(resp.text):
                return rss_url
        except Exception:
            pass

    # If a blog URL was provided, look for feed links in its HTML
    if blog_url:
        blog_url = blog_url.strip()
        if not blog_url.startswith("http"):
            blog_url = urljoin(base_url, blog_url)
        feed_from_html = _find_feed_in_html(blog_url, session)
        if feed_from_html:
            return feed_from_html

    # Try common feed paths
    for path in FEED_PATHS:
        url = urljoin(base_url, path)
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200 and _looks_like_feed(resp.text):
                return url
        except Exception:
            pass
        time.sleep(RATE_LIMIT_DELAY)

    # Try finding feed links in blog pages
    for path in BLOG_PATHS:
        url = urljoin(base_url, path)
        feed_from_html = _find_feed_in_html(url, session)
        if feed_from_html:
            return feed_from_html
        time.sleep(RATE_LIMIT_DELAY)

    # Last resort: check homepage for feed links
    feed_from_html = _find_feed_in_html(base_url, session)
    if feed_from_html:
        return feed_from_html

    return None


def _looks_like_feed(text: str) -> bool:
    """Quick heuristic to check if response text is an RSS/Atom feed."""
    text_start = text.strip()[:500].lower()
    return any(marker in text_start for marker in
               ["<rss", "<feed", "<rdf:rdf", "<?xml", "<channel>"])


def _find_feed_in_html(url: str, session: "requests.Session") -> str | None:
    """Look for RSS/Atom feed links in an HTML page."""
    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return None
        soup = BeautifulSoup(resp.text, "html.parser")
        # Look for <link rel="alternate" type="application/rss+xml" ...>
        for link in soup.find_all("link", rel="alternate"):
            link_type = (link.get("type") or "").lower()
            if "rss" in link_type or "atom" in link_type or "xml" in link_type:
                href = link.get("href", "")
                if href:
                    return urljoin(url, href)
    except Exception:
        pass
    return None


def parse_feed(feed_url: str, session: "requests.Session",
               cutoff_date: datetime) -> list[dict]:
    """Parse an RSS or Atom feed and return recent posts."""
    try:
        resp = session.get(feed_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            return []
    except Exception:
        return []

    posts = []
    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError:
        return []

    # Detect feed type and parse accordingly
    tag = root.tag.lower()
    if "rss" in tag or root.find("channel") is not None:
        posts = _parse_rss(root, cutoff_date)
    elif "feed" in tag:
        posts = _parse_atom(root, cutoff_date)
    elif "rdf" in tag:
        posts = _parse_rss(root, cutoff_date)

    return posts[:MAX_POSTS_PER_PROSPECT]


def _parse_date(date_str: str | None) -> datetime | None:
    """Try to parse a date string from an RSS/Atom feed."""
    if not date_str:
        return None
    date_str = date_str.strip()

    # Try RFC 2822 (common in RSS)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass

    # Try ISO 8601 (common in Atom)
    for fmt in [
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ]:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue

    return None


def _parse_rss(root: ET.Element, cutoff_date: datetime) -> list[dict]:
    """Parse RSS 2.0 feed items."""
    posts = []
    for item in root.iter("item"):
        title = _el_text(item, "title")
        link = _el_text(item, "link")
        pub_date = _el_text(item, "pubDate") or _el_text(item, "dc:date")
        description = _el_text(item, "description") or _el_text(item, "content:encoded")

        parsed_date = _parse_date(pub_date)
        if parsed_date and parsed_date < cutoff_date:
            continue

        posts.append({
            "title": title or "(untitled)",
            "url": link or "",
            "date": parsed_date.isoformat() if parsed_date else "",
            "summary": _clean_html(description or "")[:MAX_CONTENT_LENGTH],
        })
    return posts


def _parse_atom(root: ET.Element, cutoff_date: datetime) -> list[dict]:
    """Parse Atom feed entries."""
    posts = []
    # Handle namespaced and non-namespaced Atom
    entries = root.findall("atom:entry", ATOM_NS)
    if not entries:
        entries = root.findall("entry")
    if not entries:
        entries = root.findall("{http://www.w3.org/2005/Atom}entry")

    for entry in entries:
        title = (_el_text_ns(entry, "title") or "(untitled)")
        link = ""
        for link_el in entry.findall("atom:link", ATOM_NS) or entry.findall("link"):
            href = link_el.get("href", "")
            rel = link_el.get("rel", "alternate")
            if rel == "alternate" and href:
                link = href
                break
            if href and not link:
                link = href
        if not link:
            # Try non-namespaced
            for link_el in entry.findall("link") + entry.findall("{http://www.w3.org/2005/Atom}link"):
                href = link_el.get("href", "")
                if href:
                    link = href
                    break

        updated = _el_text_ns(entry, "updated") or _el_text_ns(entry, "published")
        content = _el_text_ns(entry, "content") or _el_text_ns(entry, "summary")

        parsed_date = _parse_date(updated)
        if parsed_date and parsed_date < cutoff_date:
            continue

        posts.append({
            "title": title,
            "url": link,
            "date": parsed_date.isoformat() if parsed_date else "",
            "summary": _clean_html(content or "")[:MAX_CONTENT_LENGTH],
        })
    return posts


def _el_text(parent: ET.Element, tag: str) -> str | None:
    """Get text content of a child element."""
    el = parent.find(tag)
    return el.text.strip() if el is not None and el.text else None


def _el_text_ns(parent: ET.Element, tag: str) -> str | None:
    """Get text content, trying both namespaced and non-namespaced."""
    el = parent.find(f"atom:{tag}", ATOM_NS)
    if el is None:
        el = parent.find(tag)
    if el is None:
        el = parent.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
    return el.text.strip() if el is not None and el.text else None


def _clean_html(text: str) -> str:
    """Strip HTML tags from text content."""
    if "<" in text:
        try:
            soup = BeautifulSoup(text, "html.parser")
            return soup.get_text(separator=" ", strip=True)
        except Exception:
            return re.sub(r"<[^>]+>", " ", text).strip()
    return text


def scrape_blog_posts(domain: str, session: "requests.Session",
                      cutoff_date: datetime,
                      blog_url: str | None = None) -> list[dict]:
    """Fallback: scrape blog listing page directly if no feed is available."""
    base_url = f"https://{domain}"
    urls_to_try = []

    if blog_url:
        blog_url = blog_url.strip()
        if not blog_url.startswith("http"):
            blog_url = urljoin(base_url, blog_url)
        urls_to_try.append(blog_url)

    for path in BLOG_PATHS:
        url = urljoin(base_url, path)
        if url not in urls_to_try:
            urls_to_try.append(url)

    for url in urls_to_try:
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                continue
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove non-content elements
            for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
                tag.decompose()

            posts = []
            # Look for article-like elements
            articles = soup.find_all("article") or soup.find_all(class_=re.compile(
                r"post|article|blog-entry|entry|card", re.I
            ))

            for article in articles[:MAX_POSTS_PER_PROSPECT]:
                title_el = article.find(["h1", "h2", "h3", "h4"])
                title = title_el.get_text(strip=True) if title_el else ""
                link_el = article.find("a", href=True)
                link = urljoin(url, link_el["href"]) if link_el else ""
                text = article.get_text(separator=" ", strip=True)[:MAX_CONTENT_LENGTH]

                if title:
                    posts.append({
                        "title": title,
                        "url": link,
                        "date": "",
                        "summary": text,
                    })

            if posts:
                return posts

        except Exception:
            continue
        time.sleep(RATE_LIMIT_DELAY)

    return []


def analyze_and_generate_outreach(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    contact_name: str | None,
    contact_title: str | None,
    posts: list[dict],
    sender_name: str,
    sender_email: str,
    product_description: str,
    topics: list[str],
) -> list[dict]:
    """Use Claude to analyze posts for topic relevance and generate warm outreach emails."""
    if not posts:
        return []

    posts_text = ""
    for j, post in enumerate(posts, 1):
        posts_text += f"\n--- Post {j} ---\n"
        posts_text += f"Title: {post['title']}\n"
        posts_text += f"URL: {post['url']}\n"
        posts_text += f"Date: {post['date']}\n"
        posts_text += f"Content: {post['summary']}\n"

    recipient = contact_name or "the team"
    title_line = f"Their title: {contact_title}" if contact_title else ""
    topics_line = f"Topics to watch for: {', '.join(topics)}" if topics else "Topics: any topics related to the product"

    prompt = f"""You are a world-class B2B sales copywriter specializing in warm social-selling outreach.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Recipient: {recipient}
{title_line}

THEIR RECENT POSTS/CONTENT:
{posts_text}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

{topics_line}

TASK:
1. Analyze each post for relevance to the topics above and to the sender's product.
2. For EACH relevant post (up to 3), generate a warm outreach email that directly references the prospect's specific take or insight from that post.
3. The tone should feel like a genuine peer reaching out, NOT a cold sales pitch.

RULES FOR EACH EMAIL:
1. Subject line must reference the specific post topic or title
2. Opening must reference their specific take or insight — e.g. "Your post about [topic] resonated — we've seen the same thing with our customers."
3. Bridge naturally from their content to how your product relates
4. Keep each email under 150 words
5. Include exactly ONE clear call-to-action: a request for a 15-minute call
6. Tone: warm, peer-to-peer, genuinely interested in their perspective
7. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
8. Sign off with the sender's name

Return your response as a JSON array of objects, one per relevant post. Each object must have:
- "post_title": the title of the post you're referencing
- "post_url": the URL of the post
- "post_date": the date of the post
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining what specific detail you referenced and why it connects

If NO posts are relevant to the topics or product, return an empty array: []
"""

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
        results = json.loads(text)
        if not isinstance(results, list):
            results = [results]
    except json.JSONDecodeError:
        results = []

    return results


def read_input_csv(filepath: str) -> list[dict]:
    """Read target prospects from CSV. Expected columns: domain, company_name, contact_name, contact_title, blog_url (optional), rss_url (optional)."""
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
        "post_title", "post_url", "post_date",
        "subject", "body", "personalization_hook",
        "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} outreach emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="LinkedIn/Twitter Content Monitor -> Warm Outreach Generator"
    )
    parser.add_argument("--input", required=True,
                        help="Input CSV with target prospects (must have 'domain' column)")
    parser.add_argument("--output", default="social_outreach_emails.csv",
                        help="Output CSV path (default: social_outreach_emails.csv)")
    parser.add_argument("--sender-email", default=DEFAULT_SENDER_EMAIL,
                        help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})")
    parser.add_argument("--sender-name", default=DEFAULT_SENDER_NAME,
                        help=f"Your name (default: {DEFAULT_SENDER_NAME})")
    parser.add_argument("--product", default="our product",
                        help="Short description of your product/service for context")
    parser.add_argument("--days-back", type=int, default=DEFAULT_DAYS_BACK,
                        help=f"How many days back to look for posts (default: {DEFAULT_DAYS_BACK})")
    parser.add_argument("--topics", default="",
                        help="Comma-separated topics to watch for (e.g. 'AI,automation,data')")
    args = parser.parse_args()

    # Validate dependencies
    if not HAS_REQUESTS:
        print("Error: requests and beautifulsoup4 packages required.")
        print("Install with: pip install requests beautifulsoup4")
        sys.exit(1)

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Parse topics
    topics = [t.strip() for t in args.topics.split(",") if t.strip()] if args.topics else []

    # Calculate cutoff date
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=args.days_back)

    # Read targets
    targets = read_input_csv(args.input)
    print(f"Loaded {len(targets)} target prospects from {args.input}")
    print(f"Looking for posts from the last {args.days_back} days (since {cutoff_date.date()})")
    if topics:
        print(f"Watching for topics: {', '.join(topics)}")

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; SocialListener/1.0)"
    })

    results = []
    for i, target in enumerate(targets, 1):
        domain = target["domain"].strip()
        company_name = target.get("company_name", domain).strip()
        contact_name = target.get("contact_name", "").strip() or None
        contact_title = target.get("contact_title", "").strip() or None
        blog_url = target.get("blog_url", "").strip() or None
        rss_url = target.get("rss_url", "").strip() or None

        print(f"\n[{i}/{len(targets)}] Processing {company_name} ({domain})...")

        # Step 1: Discover feed
        print(f"  Discovering RSS/Atom feed...")
        feed_url = discover_feed_url(domain, session, blog_url=blog_url, rss_url=rss_url)

        posts = []
        if feed_url:
            print(f"  Found feed: {feed_url}")
            posts = parse_feed(feed_url, session, cutoff_date)
            print(f"  Parsed {len(posts)} recent posts from feed")
        else:
            print(f"  No feed found, trying direct blog scrape...")
            posts = scrape_blog_posts(domain, session, cutoff_date, blog_url=blog_url)
            print(f"  Scraped {len(posts)} posts from blog pages")

        if not posts:
            print(f"  No recent posts found for {company_name}, skipping.")
            continue

        # Step 2: Analyze content and generate outreach
        print(f"  Analyzing content and generating warm outreach...")
        emails = analyze_and_generate_outreach(
            client=client,
            company_name=company_name,
            domain=domain,
            contact_name=contact_name,
            contact_title=contact_title,
            posts=posts,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
            topics=topics,
        )

        for email in emails:
            results.append({
                "company_name": company_name,
                "domain": domain,
                "contact_name": contact_name or "",
                "contact_title": contact_title or "",
                "post_title": email.get("post_title", ""),
                "post_url": email.get("post_url", ""),
                "post_date": email.get("post_date", ""),
                "subject": email.get("subject", ""),
                "body": email.get("body", ""),
                "personalization_hook": email.get("personalization_hook", ""),
                "sender_email": args.sender_email,
                "sender_name": args.sender_name,
            })

        print(f"  Generated {len(emails)} outreach email(s) for {company_name}")
        for email in emails:
            print(f"    Subject: {email.get('subject', 'N/A')}")
            print(f"    Hook: {email.get('personalization_hook', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the generated outreach emails before sending.")


if __name__ == "__main__":
    main()
