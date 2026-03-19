#!/usr/bin/env python3
"""
Meeting Prep Brief Generator — Auto-research prospects and email a prep brief.

When a prospect is classified as direct_intent or meeting_booked, this module:
  1. Scrapes the prospect's company website
  2. Uses Claude to generate a concise meeting prep brief
  3. Emails the brief to Dylan (dylan.realside@gmail.com) via SMTP

Can be used standalone or imported by reply_autopilot.py.

Usage:
    python meeting_prep.py --email prospect@company.com --name "Pat Bauer" --company "Heartland Dental" --domain heartland.com --category direct_intent
    python meeting_prep.py --email prospect@company.com --domain example.com --dry-run
"""

import argparse
import json
import logging
import os
import re
import smtplib
import sys
import time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PAGES_TO_SCRAPE = ["/", "/about", "/about-us", "/services", "/pricing", "/blog"]
MAX_CONTENT_LENGTH = 3000
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1
BRIEFS_DIR = "output/meeting_briefs"
DEFAULT_CONFIG_PATH = "config.json"

PREP_CATEGORIES = {"direct_intent", "meeting_booked"}

# ---------------------------------------------------------------------------
# Website scraping (reuses pattern from prospect_researcher.py)
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
        logging.warning("requests/bs4 not installed, skipping website scrape.")
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


# ---------------------------------------------------------------------------
# Brief generation via Claude
# ---------------------------------------------------------------------------


def generate_prep_brief(
    client: anthropic.Anthropic,
    contact_name: str,
    contact_email: str,
    company_name: str,
    domain: str,
    category: str,
    reply_text: str,
    website_content: dict[str, str],
    case_studies: str,
) -> str:
    """Use Claude to generate a meeting prep brief for Dylan."""

    site_text = ""
    for path, content in website_content.items():
        site_text += f"\n--- {path} ---\n{content}\n"

    if not site_text:
        site_text = "(Website content not available)"

    prompt = f"""You are a sales prep assistant for Realside AI. Generate a concise meeting prep brief for Dylan Mitchell before his call with a prospect.

PROSPECT INFO:
- Name: {contact_name or 'Unknown'}
- Email: {contact_email}
- Company: {company_name or 'Unknown'}
- Domain: {domain or 'Unknown'}
- Reply category: {category}
- Their reply: "{reply_text}"

WEBSITE CONTENT SCRAPED:
{site_text}

CASE STUDIES (for reference):
{case_studies[:2000] if case_studies else '(none loaded)'}

Generate a meeting prep brief with these sections:

1. COMPANY SNAPSHOT (2-3 sentences: what they do, size, location, target market)
2. LIKELY PAIN POINTS (bullet list of 3-4 pain points based on their business type and website)
3. RECOMMENDED PITCH ANGLE (which Realside AI product fits best and why, 2-3 sentences)
4. RELEVANT CASE STUDY (which case study to reference and the key stat to drop)
5. CONVERSATION STARTERS (2-3 personalized openers based on their website/business)
6. OBJECTION PREP (2-3 likely objections and suggested responses)
7. GOAL FOR THE CALL (one clear next step to push for)

Keep it scannable. Use bullet points. Total length: 300-500 words."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        return response.content[0].text.strip()
    except Exception as e:
        logging.error("Failed to generate prep brief: %s", e)
        return f"[AUTO-GENERATED BRIEF FAILED]\n\nProspect: {contact_name} <{contact_email}>\nCompany: {company_name} ({domain})\nCategory: {category}\nReply: {reply_text}\n\nManual research needed."


# ---------------------------------------------------------------------------
# Email delivery via SMTP (Gmail App Password)
# ---------------------------------------------------------------------------


def send_prep_email_smtp(
    to_email: str,
    subject: str,
    body: str,
    sender_email: str,
    smtp_password: str,
    smtp_host: str = "smtp.gmail.com",
    smtp_port: int = 587,
) -> bool:
    """Send the prep brief via SMTP (Gmail with app password)."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender_email
    msg["To"] = to_email

    # Plain text version
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # Simple HTML version
    html_body = body.replace("\n", "<br>")
    html = f"<html><body style='font-family: Arial, sans-serif; font-size: 14px; line-height: 1.6;'>{html_body}</body></html>"
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(sender_email, smtp_password)
            server.send_message(msg)
        logging.info("Prep brief emailed to %s via SMTP", to_email)
        return True
    except Exception as e:
        logging.error("SMTP send failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Email delivery via Instantly API (fallback)
# ---------------------------------------------------------------------------


def send_prep_email_instantly(
    api_key: str,
    to_email: str,
    from_email: str,
    subject: str,
    body: str,
) -> bool:
    """Send the prep brief via Instantly's unibox send endpoint."""
    if not HAS_REQUESTS:
        logging.warning("requests not installed, cannot send via Instantly.")
        return False

    url = "https://api.instantly.ai/api/v2/unibox/emails/send"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "from": from_email,
        "to": to_email,
        "subject": subject,
        "body": {"html": body.replace("\n", "<br>"), "text": body},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code < 400:
            logging.info("Prep brief emailed to %s via Instantly", to_email)
            return True
        else:
            logging.warning("Instantly send failed (%d): %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logging.error("Instantly send error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Save brief to file (always, as backup)
# ---------------------------------------------------------------------------


def save_brief_to_file(
    brief: str,
    contact_name: str,
    contact_email: str,
    company_name: str,
    domain: str,
    category: str,
    script_dir: str,
) -> str:
    """Save the prep brief as a text file in output/meeting_briefs/."""
    briefs_dir = os.path.join(script_dir, BRIEFS_DIR)
    os.makedirs(briefs_dir, exist_ok=True)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^a-zA-Z0-9]", "_", (company_name or domain or "unknown").lower())
    filename = f"{timestamp}_{safe_name}.txt"
    filepath = os.path.join(briefs_dir, filename)

    header = (
        f"MEETING PREP BRIEF\n"
        f"{'=' * 50}\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\n"
        f"Prospect: {contact_name or 'Unknown'} <{contact_email}>\n"
        f"Company: {company_name or 'Unknown'} ({domain or 'N/A'})\n"
        f"Category: {category}\n"
        f"{'=' * 50}\n\n"
    )

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(header + brief)

    logging.info("Brief saved to %s", filepath)
    return filepath


# ---------------------------------------------------------------------------
# Main entry point (called by reply_autopilot or standalone)
# ---------------------------------------------------------------------------


def generate_and_send_prep(
    config: dict,
    contact_name: str,
    contact_email: str,
    company_name: str,
    domain: str,
    category: str,
    reply_text: str,
    dry_run: bool = False,
) -> dict:
    """Full flow: scrape website, generate brief, email to Dylan, save to file.

    Returns dict with keys: brief_generated, email_sent, file_saved, filepath
    """
    result = {
        "brief_generated": False,
        "email_sent": False,
        "file_saved": False,
        "filepath": "",
    }

    if category not in PREP_CATEGORIES:
        logging.debug("Category '%s' does not trigger meeting prep.", category)
        return result

    script_dir = os.path.dirname(os.path.abspath(__file__))

    # Initialize Claude client
    anthropic_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        logging.error("No Anthropic API key for meeting prep.")
        return result

    client = anthropic.Anthropic(api_key=anthropic_key)

    # Load case studies
    case_studies = ""
    cs_path = config.get("case_studies_path", "case_studies")
    if not os.path.isabs(cs_path):
        cs_path = os.path.join(script_dir, cs_path)
    if os.path.isdir(cs_path):
        for fn in sorted(os.listdir(cs_path)):
            if fn.endswith(".md"):
                try:
                    with open(os.path.join(cs_path, fn), encoding="utf-8") as f:
                        case_studies += f"\n--- {fn} ---\n{f.read().strip()}\n"
                except Exception:
                    pass

    # Step 1: Scrape prospect website
    logging.info("Scraping %s for meeting prep...", domain or "(no domain)")
    website_content = {}
    if domain:
        website_content = scrape_company(domain)
        logging.info("Scraped %d pages from %s", len(website_content), domain)
    else:
        logging.warning("No domain provided, generating brief without website data.")

    # Step 2: Generate brief with Claude
    logging.info("Generating meeting prep brief for %s at %s...", contact_name, company_name)
    brief = generate_prep_brief(
        client=client,
        contact_name=contact_name,
        contact_email=contact_email,
        company_name=company_name,
        domain=domain or "",
        category=category,
        reply_text=reply_text,
        website_content=website_content,
        case_studies=case_studies,
    )
    result["brief_generated"] = True

    # Step 3: Always save to file
    filepath = save_brief_to_file(
        brief=brief,
        contact_name=contact_name,
        contact_email=contact_email,
        company_name=company_name,
        domain=domain or "",
        category=category,
        script_dir=script_dir,
    )
    result["file_saved"] = True
    result["filepath"] = filepath

    if dry_run:
        logging.info("[DRY-RUN] Would email prep brief to %s", config.get("sender_email"))
        logging.info("Brief preview:\n%s", brief[:500])
        return result

    # Step 4: Email the brief to Dylan
    sender_email = config.get("sender_email", "dylan.realside@gmail.com")
    sender_name = config.get("sender_name", "Dylan Mitchell")
    subject = f"Meeting Prep: {contact_name or contact_email} at {company_name or domain or 'Unknown'}"

    email_body = (
        f"Meeting Prep Brief for your upcoming call\n"
        f"{'-' * 50}\n\n"
        f"Prospect: {contact_name or 'Unknown'} <{contact_email}>\n"
        f"Company: {company_name or 'Unknown'} ({domain or 'N/A'})\n"
        f"Intent: {category.replace('_', ' ').title()}\n"
        f"Their reply: \"{reply_text[:200]}\"\n\n"
        f"{'-' * 50}\n\n"
        f"{brief}\n\n"
        f"{'-' * 50}\n"
        f"Calendar: {config.get('calendar_link', 'https://calendly.com/realsideai')}\n"
        f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )

    # Try SMTP first (if configured), then Instantly API
    smtp_password = config.get("smtp_app_password", "") or os.environ.get("SMTP_APP_PASSWORD", "")
    if smtp_password:
        result["email_sent"] = send_prep_email_smtp(
            to_email=sender_email,
            subject=subject,
            body=email_body,
            sender_email=sender_email,
            smtp_password=smtp_password,
        )
    else:
        # Fallback: send via Instantly API
        instantly_key = config.get("instantly_api_key", "")
        if instantly_key:
            result["email_sent"] = send_prep_email_instantly(
                api_key=instantly_key,
                to_email=sender_email,
                from_email=sender_email,
                subject=subject,
                body=email_body,
            )
        else:
            logging.warning(
                "No email delivery method configured. Add smtp_app_password to config.json "
                "or set SMTP_APP_PASSWORD env var. Brief saved to: %s", filepath
            )

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Meeting Prep Brief Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--email", required=True, help="Prospect email address")
    parser.add_argument("--name", default="", help="Prospect name")
    parser.add_argument("--company", default="", help="Company name")
    parser.add_argument("--domain", default="", help="Company domain (e.g. heartland.com)")
    parser.add_argument("--category", default="direct_intent",
                        choices=["direct_intent", "meeting_booked"],
                        help="Reply category")
    parser.add_argument("--reply-text", default="I'd love to learn more. What times work?",
                        help="The prospect's reply text")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't email")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load config
    config_path = args.config
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isabs(config_path):
        config_path = os.path.join(script_dir, config_path)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logging.error("Could not load config: %s", e)
        sys.exit(1)

    # Derive domain from email if not provided
    domain = args.domain
    if not domain and args.email and "@" in args.email:
        domain = args.email.split("@")[1]

    result = generate_and_send_prep(
        config=config,
        contact_name=args.name,
        contact_email=args.email,
        company_name=args.company,
        domain=domain,
        category=args.category,
        reply_text=args.reply_text,
        dry_run=args.dry_run,
    )

    print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
