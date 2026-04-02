#!/usr/bin/env python3
"""
Competitor Review Mining → Displacement Outreach Generator

Scrapes public review sites (G2, Capterra) for negative reviews of your
competitors, identifies common pain points, and uses Claude to generate
displacement outreach emails targeting companies that expressed dissatisfaction.

Usage:
    python competitor_review_miner.py --competitors "salesforce,hubspot"
    python competitor_review_miner.py --competitors "salesforce,hubspot" --targets prospects.csv --output emails.csv
    python competitor_review_miner.py --competitors "zendesk" --product "our AI-powered support platform" --sender-email you@company.com --sender-name "Your Name"

Input (--targets CSV, optional):
    Expected columns: prospect_company, prospect_contact (optional: contact_title, domain)

Output CSV columns:
    competitor, pain_point, prospect_company, prospect_contact, subject, body, personalization_hook, sender_email, sender_name
"""

import argparse
import csv
import json
import os
import re
import sys
import time
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
MAX_CONTENT_LENGTH = 5000  # chars of review content to send to Claude
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 2  # seconds between requests to avoid rate limiting
MAX_REVIEW_PAGES = 3  # max pages of reviews to scrape per competitor


def scrape_g2_reviews(competitor: str, session: "requests.Session") -> list[str]:
    """Scrape review content from G2 for a given competitor.

    Returns a list of review text strings.
    """
    reviews = []
    slug = competitor.lower().strip().replace(" ", "-")
    base_url = f"https://www.g2.com/products/{slug}/reviews"

    for page in range(1, MAX_REVIEW_PAGES + 1):
        url = base_url if page == 1 else f"{base_url}?page={page}"
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code != 200:
                print(f"    G2 page {page} returned status {resp.status_code}")
                break
            soup = BeautifulSoup(resp.text, "html.parser")

            # G2 review content is typically in review body divs
            review_divs = soup.find_all("div", attrs={"class": re.compile(r"review-content|review-body|ri-body", re.I)})
            if not review_divs:
                # Fallback: look for common review text containers
                review_divs = soup.find_all("div", attrs={"itemprop": "reviewBody"})
            if not review_divs:
                # Broader fallback: any div with "dislike" or "problems" content
                review_divs = soup.find_all("div", attrs={"class": re.compile(r"dislike|cons|negative", re.I)})
            if not review_divs:
                # Last resort: grab all paragraph text from the page
                review_divs = soup.find_all("p")

            for div in review_divs:
                text = div.get_text(separator=" ", strip=True)
                if text and len(text) > 20:
                    reviews.append(text)

            time.sleep(RATE_LIMIT_DELAY)
        except Exception as e:
            print(f"    Error scraping G2 page {page}: {e}")
            break

    return reviews


def scrape_capterra_reviews(competitor: str, session: "requests.Session") -> list[str]:
    """Scrape review content from Capterra for a given competitor.

    Returns a list of review text strings.
    """
    reviews = []
    slug = competitor.lower().strip().replace(" ", "-")
    url = f"https://www.capterra.com/p/reviews/{slug}/"

    try:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        if resp.status_code != 200:
            print(f"    Capterra returned status {resp.status_code}")
            return reviews
        soup = BeautifulSoup(resp.text, "html.parser")

        # Capterra review containers
        review_divs = soup.find_all("div", attrs={"class": re.compile(r"review-content|cons|negative|review-text", re.I)})
        if not review_divs:
            review_divs = soup.find_all("span", attrs={"class": re.compile(r"review|cons", re.I)})
        if not review_divs:
            review_divs = soup.find_all("p")

        for div in review_divs:
            text = div.get_text(separator=" ", strip=True)
            if text and len(text) > 20:
                reviews.append(text)

    except Exception as e:
        print(f"    Error scraping Capterra: {e}")

    return reviews


def scrape_competitor_reviews(competitor: str) -> dict[str, list[str]]:
    """Scrape reviews from multiple review sites for a competitor.

    Returns {source: [review_texts]}.
    """
    if not HAS_REQUESTS:
        return {}

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; CompetitorReviewMiner/1.0)"
    })

    results = {}

    print(f"    Scraping G2 reviews...")
    g2_reviews = scrape_g2_reviews(competitor, session)
    if g2_reviews:
        results["g2"] = g2_reviews
    print(f"    Found {len(g2_reviews)} review snippets on G2")

    time.sleep(RATE_LIMIT_DELAY)

    print(f"    Scraping Capterra reviews...")
    capterra_reviews = scrape_capterra_reviews(competitor, session)
    if capterra_reviews:
        results["capterra"] = capterra_reviews
    print(f"    Found {len(capterra_reviews)} review snippets on Capterra")

    return results


def scrape_reviews_with_anthropic(competitor: str, client: anthropic.Anthropic) -> dict[str, list[str]]:
    """Fallback: use Claude to summarize known reviews when requests/bs4 unavailable."""
    results = {}
    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": (
                    f"Based on your knowledge of {competitor}, list the most common "
                    f"negative reviews and complaints from public review sites like G2 "
                    f"and Capterra. For each complaint, describe the pain point in 1-2 "
                    f"sentences as if quoting a real reviewer. List at least 5 complaints "
                    f"if possible. Return ONLY a JSON array of strings, each string being "
                    f"a review-style complaint."
                )
            }],
        )
        text = response.content[0].text.strip()
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            complaints = json.loads(json_match.group(0))
            results["claude_knowledge"] = [str(c) for c in complaints]
    except Exception as e:
        print(f"    Error using Claude for review research: {e}")

    return results


def analyze_reviews_and_generate_emails(
    client: anthropic.Anthropic,
    competitor: str,
    reviews: dict[str, list[str]],
    targets: list[dict],
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> list[dict]:
    """Use Claude to analyze reviews, extract pain points, and generate displacement emails."""

    # Combine all reviews into a single text block, truncated to max length
    all_reviews = []
    for source, review_list in reviews.items():
        for review in review_list:
            all_reviews.append(f"[{source}] {review}")

    reviews_text = "\n\n".join(all_reviews)
    if len(reviews_text) > MAX_CONTENT_LENGTH:
        reviews_text = reviews_text[:MAX_CONTENT_LENGTH] + "\n... (truncated)"

    if not reviews_text.strip():
        reviews_text = (
            f"(No review content was scraped for {competitor}. Use your knowledge "
            f"of common complaints about {competitor} to identify likely pain points.)"
        )

    # Build target info for the prompt
    if targets:
        target_info = "TARGET PROSPECTS (generate one email per prospect):\n"
        for t in targets:
            company = t.get("prospect_company", "Unknown Company")
            contact = t.get("prospect_contact", "")
            title = t.get("contact_title", "")
            target_info += f"- Company: {company}, Contact: {contact or 'unknown'}, Title: {title or 'unknown'}\n"
    else:
        target_info = (
            "No specific targets provided. Generate 3 template emails that could be "
            "sent to companies likely using this competitor. Use placeholder names like "
            "[Company Name] and [Contact Name]."
        )

    prompt = f"""You are an expert B2B sales strategist specializing in competitive displacement.

TASK: Analyze these reviews of {competitor}, identify the top pain points, and generate
personalized displacement outreach emails.

COMPETITOR REVIEWS:
{reviews_text}

{target_info}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

INSTRUCTIONS:
1. First, identify the 3-5 most common/severe pain points from the reviews
2. For each target prospect (or template if no targets), generate a displacement email that:
   - References a SPECIFIC pain point from the reviews
   - Does NOT trash-talk the competitor — be professional
   - Positions your product as solving that specific pain
   - Keeps the email under 150 words
   - Includes ONE clear CTA: ask what days work for a call (never include a calendly or scheduling link)
   - Tone: empathetic and helpful, not pushy

Return your response as a JSON array of objects, each with these exact keys:
- "competitor": the competitor name
- "pain_point": the specific pain point being addressed (1-2 sentences)
- "prospect_company": the target company name
- "prospect_contact": the contact name
- "subject": email subject line referencing the pain point
- "body": full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining the displacement angle used
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    text = response.content[0].text.strip()

    # Extract JSON array from response
    json_match = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)
    else:
        json_match = re.search(r"\[.*\]", text, re.DOTALL)
        if json_match:
            text = json_match.group(0)

    try:
        results = json.loads(text)
    except json.JSONDecodeError:
        print(f"    Warning: Could not parse Claude's response as JSON for {competitor}")
        results = [{
            "competitor": competitor,
            "pain_point": "Could not parse structured response",
            "prospect_company": "",
            "prospect_contact": "",
            "subject": f"Considering alternatives to {competitor}?",
            "body": text,
            "personalization_hook": "Unparsed response",
        }]

    # Ensure all results have the right keys and add sender info
    cleaned = []
    for r in results:
        cleaned.append({
            "competitor": r.get("competitor", competitor),
            "pain_point": r.get("pain_point", ""),
            "prospect_company": r.get("prospect_company", ""),
            "prospect_contact": r.get("prospect_contact", ""),
            "subject": r.get("subject", ""),
            "body": r.get("body", ""),
            "personalization_hook": r.get("personalization_hook", ""),
            "sender_email": sender_email,
            "sender_name": sender_name,
        })

    return cleaned


def read_targets_csv(filepath: str) -> list[dict]:
    """Read target prospects from CSV.

    Expected columns: prospect_company, prospect_contact
    Optional columns: contact_title, domain
    """
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if "prospect_company" not in row:
                print("Error: targets CSV must have a 'prospect_company' column")
                sys.exit(1)
            rows.append(row)
    return rows


def write_output_csv(filepath: str, results: list[dict]):
    """Write generated displacement emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "competitor", "pain_point", "prospect_company", "prospect_contact",
        "subject", "body", "personalization_hook", "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} displacement emails to {filepath}")


def main():
    parser = argparse.ArgumentParser(
        description="Competitor Review Mining + Displacement Outreach Generator"
    )
    parser.add_argument(
        "--competitors", required=True,
        help="Comma-separated list of competitor names (e.g. 'salesforce,hubspot')"
    )
    parser.add_argument(
        "--targets", default=None,
        help="Optional CSV of target prospects (must have 'prospect_company' column)"
    )
    parser.add_argument(
        "--output", default="displacement_emails.csv",
        help="Output CSV path (default: displacement_emails.csv)"
    )
    parser.add_argument(
        "--sender-email", default=DEFAULT_SENDER_EMAIL,
        help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})"
    )
    parser.add_argument(
        "--sender-name", default=DEFAULT_SENDER_NAME,
        help=f"Your name (default: {DEFAULT_SENDER_NAME})"
    )
    parser.add_argument(
        "--product", default="our product",
        help="Short description of your product/service for context"
    )
    args = parser.parse_args()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Parse competitors
    competitors = [c.strip() for c in args.competitors.split(",") if c.strip()]
    if not competitors:
        print("Error: no competitors specified")
        sys.exit(1)

    print(f"Competitors to analyze: {', '.join(competitors)}")

    # Read targets if provided
    targets = []
    if args.targets:
        targets = read_targets_csv(args.targets)
        print(f"Loaded {len(targets)} target prospects from {args.targets}")
    else:
        print("No targets CSV provided — will generate template displacement emails")

    all_results = []

    for i, competitor in enumerate(competitors, 1):
        print(f"\n[{i}/{len(competitors)}] Mining reviews for: {competitor}")

        # Scrape reviews
        if HAS_REQUESTS:
            reviews = scrape_competitor_reviews(competitor)
        else:
            print("  (requests/bs4 not installed — using Claude for review research)")
            reviews = scrape_reviews_with_anthropic(competitor, client)

        total_reviews = sum(len(v) for v in reviews.values())
        print(f"    Total review snippets collected: {total_reviews}")

        # Generate displacement emails
        print(f"    Analyzing pain points and generating displacement emails...")
        emails = analyze_reviews_and_generate_emails(
            client=client,
            competitor=competitor,
            reviews=reviews,
            targets=targets,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        all_results.extend(emails)

        for email in emails:
            print(f"    -> Subject: {email.get('subject', 'N/A')}")
            print(f"       Pain point: {email.get('pain_point', 'N/A')[:80]}")

        time.sleep(RATE_LIMIT_DELAY)

    # Write output
    write_output_csv(args.output, all_results)
    print("\nDone! Review the generated displacement emails before sending.")


if __name__ == "__main__":
    main()
