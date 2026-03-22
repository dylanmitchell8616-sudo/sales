#!/usr/bin/env python3
"""
Case Study Matcher + Personalized Outreach Generator

Maintains a library of case studies (markdown files or CSV) and matches each
prospect to the most relevant case study based on industry, company size, and
pain points. Generates outreach emails that lead with the matched customer story.

Usage:
    python case_study_matcher.py --case-studies case_studies/ --targets targets.csv --output case_study_emails.csv
    python case_study_matcher.py --case-studies case_studies.csv --targets targets.csv --sender-email you@company.com --sender-name "Your Name"
"""

import argparse
import csv
import glob
import json
import os
import re
import sys
import time
from urllib.parse import urljoin

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
PAGES_TO_SCRAPE = ["/", "/about", "/about-us", "/products", "/pricing"]
MAX_CONTENT_LENGTH = 3000  # chars per page to send to Claude
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1  # seconds between requests to same domain


# ---------------------------------------------------------------------------
# Case study loading
# ---------------------------------------------------------------------------

def load_case_studies_from_csv(filepath: str) -> list[dict]:
    """Load case studies from a CSV file.

    Expected columns: customer_name, industry, pain_point, result, story
    """
    studies = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        required = {"customer_name", "industry", "pain_point", "result", "story"}
        if not required.issubset(set(reader.fieldnames or [])):
            print(f"Error: Case study CSV must have columns: {', '.join(sorted(required))}")
            sys.exit(1)
        for row in reader:
            studies.append({
                "customer_name": row["customer_name"].strip(),
                "industry": row["industry"].strip(),
                "pain_point": row["pain_point"].strip(),
                "result": row["result"].strip(),
                "story": row["story"].strip(),
            })
    return studies


def parse_markdown_case_study(filepath: str) -> dict:
    """Parse a single markdown case study file.

    Expected frontmatter-style headers or free-form content. The parser looks
    for lines like ``Customer: Acme Corp`` at the top, falling back to using
    the filename as the customer name and the entire body as the story.
    """
    with open(filepath, encoding="utf-8") as f:
        content = f.read()

    meta: dict[str, str] = {}
    field_map = {
        "customer": "customer_name",
        "customer_name": "customer_name",
        "industry": "industry",
        "pain_point": "pain_point",
        "pain point": "pain_point",
        "result": "result",
        "story": "story",
    }

    lines = content.splitlines()
    body_start = 0
    for idx, line in enumerate(lines):
        match = re.match(r"^#+\s*(.+)", line)  # markdown heading
        kv_match = re.match(r"^(\w[\w\s]*?):\s*(.+)", line)
        if kv_match:
            key = kv_match.group(1).strip().lower()
            value = kv_match.group(2).strip()
            if key in field_map:
                meta[field_map[key]] = value
                body_start = idx + 1
        elif match and not meta.get("customer_name"):
            meta["customer_name"] = match.group(1).strip()
            body_start = idx + 1
        elif line.strip() == "":
            body_start = idx + 1
        else:
            break

    remaining_body = "\n".join(lines[body_start:]).strip()

    # Fallback: use filename as customer name
    if "customer_name" not in meta:
        basename = os.path.splitext(os.path.basename(filepath))[0]
        meta["customer_name"] = basename.replace("_", " ").replace("-", " ").title()

    return {
        "customer_name": meta.get("customer_name", "Unknown"),
        "industry": meta.get("industry", ""),
        "pain_point": meta.get("pain_point", ""),
        "result": meta.get("result", ""),
        "story": meta.get("story", remaining_body or content),
    }


def load_case_studies_from_dir(dirpath: str) -> list[dict]:
    """Load all markdown case studies from a directory."""
    studies = []
    patterns = [os.path.join(dirpath, "*.md"), os.path.join(dirpath, "*.markdown")]
    files = []
    for pattern in patterns:
        files.extend(glob.glob(pattern))
    files.sort()

    if not files:
        print(f"Error: No markdown files found in {dirpath}")
        sys.exit(1)

    for fp in files:
        studies.append(parse_markdown_case_study(fp))
    return studies


def load_case_studies(path: str) -> list[dict]:
    """Load case studies from either a CSV file or a directory of markdown files."""
    if os.path.isdir(path):
        return load_case_studies_from_dir(path)
    elif os.path.isfile(path) and path.lower().endswith(".csv"):
        return load_case_studies_from_csv(path)
    elif os.path.isfile(path):
        # Single markdown file — treat as a one-study library
        return [parse_markdown_case_study(path)]
    else:
        print(f"Error: --case-studies path not found: {path}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Web scraping (mirrors prospect_researcher.py)
# ---------------------------------------------------------------------------

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


def scrape_company(domain: str) -> dict[str, str]:
    """Scrape key pages from a company domain. Returns {page_path: content}."""
    if not HAS_REQUESTS:
        return {}

    results = {}
    base_url = f"https://{domain}"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; CaseStudyMatcher/1.0)"
    })

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        content = scrape_page(url, session)
        if content:
            results[path] = content
        time.sleep(RATE_LIMIT_DELAY)

    return results


def scrape_company_with_anthropic(domain: str, client: anthropic.Anthropic) -> dict[str, str]:
    """Fallback: use Claude to summarize company pages when requests/bs4 unavailable."""
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
                    "content": (
                        f"Fetch and summarize the key content from this URL in 2-3 paragraphs. "
                        f"Focus on what the company does, their products/services, industry, "
                        f"company size signals, and any notable pain points or challenges: {url}"
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


# ---------------------------------------------------------------------------
# Claude-powered matching and email generation
# ---------------------------------------------------------------------------

def format_case_studies_for_prompt(case_studies: list[dict]) -> str:
    """Format the case study library into a numbered list for the Claude prompt."""
    parts = []
    for i, cs in enumerate(case_studies, 1):
        parts.append(
            f"[{i}] Customer: {cs['customer_name']}\n"
            f"    Industry: {cs['industry']}\n"
            f"    Pain Point: {cs['pain_point']}\n"
            f"    Result: {cs['result']}\n"
            f"    Story: {cs['story'][:500]}"
        )
    return "\n\n".join(parts)


def match_and_generate(
    client: anthropic.Anthropic,
    company_name: str,
    domain: str,
    scraped_content: dict[str, str],
    contact_name: str | None,
    contact_title: str | None,
    case_studies: list[dict],
    sender_name: str,
    sender_email: str,
    product_description: str,
) -> dict:
    """Use Claude to match the prospect to the best case study and generate outreach."""

    content_summary = ""
    for page, text in scraped_content.items():
        content_summary += f"\n--- Content from {domain}{page} ---\n{text}\n"

    if not content_summary.strip():
        content_summary = (
            f"(No web content was available for {domain}. "
            f"Generate based on the domain name and any knowledge you have.)"
        )

    recipient = contact_name or "the team"
    title_line = f"Their title: {contact_title}" if contact_title else ""
    studies_text = format_case_studies_for_prompt(case_studies)

    prompt = f"""You are a world-class B2B sales strategist. Your task has two parts:

1. MATCH: Pick the single most relevant case study for this prospect based on industry alignment, company size similarity, and overlapping pain points.
2. GENERATE: Write a short, personalized cold email that LEADS with the matched customer story.

PROSPECT INFO:
- Company: {company_name}
- Domain: {domain}
- Recipient: {recipient}
{title_line}

SCRAPED WEBSITE CONTENT:
{content_summary}

CASE STUDY LIBRARY:
{studies_text}

SENDER INFO:
- Name: {sender_name}
- Email: {sender_email}
- Product: {product_description}

EMAIL RULES:
1. Open by referencing the matched case study — e.g. "We helped [Customer] solve [pain point] and achieve [result]"
2. Immediately connect it to something SPECIFIC about the prospect from their website
3. Keep the email under 150 words
4. Include exactly ONE clear call-to-action: ask what days work for a call (never include a calendly or scheduling link)
5. Tone: professional but conversational, not salesy
6. Do NOT use buzzwords like "synergy", "leverage", "revolutionize"
7. Sign off with the sender's name

Return your response as JSON with these exact keys:
- "matched_case_study": the customer_name of the best-fit case study
- "match_reason": 1-2 sentences explaining why this case study is the best match for this prospect
- "subject": the email subject line
- "body": the full email body (plain text, use \\n for newlines)
- "personalization_hook": one sentence explaining what specific prospect detail you referenced and why
"""

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1500,
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
            "matched_case_study": "Unknown",
            "match_reason": "Could not parse structured response",
            "subject": f"Quick question about {company_name}",
            "body": text,
            "personalization_hook": "Could not parse structured response",
        }

    return result


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def read_targets_csv(filepath: str) -> list[dict]:
    """Read target companies from CSV. Expected columns: domain, company_name (optional: contact_name, contact_title)."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "domain" not in (reader.fieldnames or []):
            print("Error: Targets CSV must have a 'domain' column")
            sys.exit(1)
        for row in reader:
            rows.append(row)
    return rows


def write_output_csv(filepath: str, results: list[dict]):
    """Write matched case study emails to CSV."""
    if not results:
        print("No results to write.")
        return

    fieldnames = [
        "company_name", "domain", "contact_name", "contact_title",
        "matched_case_study", "match_reason",
        "subject", "body", "personalization_hook",
        "sender_email", "sender_name",
    ]
    with open(filepath, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)
    print(f"\nWrote {len(results)} emails to {filepath}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Case Study Matcher + Personalized Outreach Generator"
    )
    parser.add_argument(
        "--case-studies", required=True,
        help="Path to a directory of markdown case study files OR a CSV with columns: customer_name, industry, pain_point, result, story",
    )
    parser.add_argument(
        "--targets", required=True,
        help="Input CSV with target companies (must have 'domain' column; optional: company_name, contact_name, contact_title)",
    )
    parser.add_argument(
        "--output", default="case_study_emails.csv",
        help="Output CSV path (default: case_study_emails.csv)",
    )
    parser.add_argument(
        "--sender-email", default=DEFAULT_SENDER_EMAIL,
        help=f"Your email address (default: {DEFAULT_SENDER_EMAIL})",
    )
    parser.add_argument(
        "--sender-name", default=DEFAULT_SENDER_NAME,
        help=f"Your name (default: {DEFAULT_SENDER_NAME})",
    )
    parser.add_argument(
        "--product", default="our product",
        help="Short description of your product/service for context",
    )
    args = parser.parse_args()

    # Validate API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Error: ANTHROPIC_API_KEY environment variable is required")
        print("Set it with: export ANTHROPIC_API_KEY=your-key-here")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    # Load case studies
    case_studies = load_case_studies(args.case_studies)
    print(f"Loaded {len(case_studies)} case studies from {args.case_studies}")
    for cs in case_studies:
        print(f"  - {cs['customer_name']} ({cs['industry']})")

    # Read targets
    targets = read_targets_csv(args.targets)
    print(f"Loaded {len(targets)} target companies from {args.targets}")

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

        # Match case study and generate email
        print(f"  Matching case study and generating email...")
        email = match_and_generate(
            client=client,
            company_name=company_name,
            domain=domain,
            scraped_content=scraped,
            contact_name=contact_name,
            contact_title=contact_title,
            case_studies=case_studies,
            sender_name=args.sender_name,
            sender_email=args.sender_email,
            product_description=args.product,
        )

        results.append({
            "company_name": company_name,
            "domain": domain,
            "contact_name": contact_name or "",
            "contact_title": contact_title or "",
            "matched_case_study": email.get("matched_case_study", ""),
            "match_reason": email.get("match_reason", ""),
            "subject": email.get("subject", ""),
            "body": email.get("body", ""),
            "personalization_hook": email.get("personalization_hook", ""),
            "sender_email": args.sender_email,
            "sender_name": args.sender_name,
        })

        print(f"  Done — Matched: {email.get('matched_case_study', 'N/A')}")
        print(f"  Reason: {email.get('match_reason', 'N/A')}")
        print(f"  Subject: {email.get('subject', 'N/A')}")

    # Write output
    write_output_csv(args.output, results)
    print("\nDone! Review the generated emails before sending.")


if __name__ == "__main__":
    main()
