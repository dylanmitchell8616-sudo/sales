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

PAGES_TO_SCRAPE = ["/", "/about", "/about-us", "/services", "/pricing", "/blog",
                   "/team", "/our-team", "/staff", "/contact", "/reviews", "/testimonials"]
MAX_CONTENT_LENGTH = 3000
REQUEST_TIMEOUT = 15
RATE_LIMIT_DELAY = 1
BRIEFS_DIR = "output/meeting_briefs"
BRIEFS_HISTORY_PATH = "output/meeting_briefs/history.json"
DEFAULT_CONFIG_PATH = "config.json"

PREP_CATEGORIES = {"direct_intent", "meeting_booked"}

# Known tech platforms to detect from website HTML/text
TECH_SIGNATURES = {
    "Mindbody": ["mindbodyonline.com", "mindbody", "MINDBODY"],
    "Jane App": ["jane.app", "janeapp.com"],
    "Square Appointments": ["squareup.com/appointments", "square appointments"],
    "Acuity Scheduling": ["acuityscheduling.com", "acuity"],
    "Calendly": ["calendly.com"],
    "Vagaro": ["vagaro.com"],
    "Zenoti": ["zenoti.com"],
    "Boulevard": ["joinblvd.com", "boulevard"],
    "Fresha": ["fresha.com"],
    "Phorest": ["phorest.com"],
    "ServiceTitan": ["servicetitan.com"],
    "Housecall Pro": ["housecallpro.com"],
    "Jobber": ["getjobber.com", "jobber"],
    "Dentrix": ["dentrix.com"],
    "Open Dental": ["opendental.com"],
    "Eaglesoft": ["eaglesoft"],
    "HubSpot": ["hubspot.com", "hs-scripts.com", "hbspt."],
    "Salesforce": ["salesforce.com", "force.com"],
    "Mailchimp": ["mailchimp.com", "mc.us"],
    "Constant Contact": ["constantcontact.com"],
    "Google Ads": ["googleads.g.doubleclick", "google_conversion", "gtag("],
    "Facebook Pixel": ["fbq(", "facebook.com/tr", "connect.facebook.net"],
    "Yelp": ["yelp.com/biz"],
    "Podium": ["podium.com"],
    "Birdeye": ["birdeye.com"],
    "Weave": ["getweave.com"],
    "CallRail": ["callrail.com", "calltrk.com"],
}

# Decision-maker title patterns
DECISION_MAKER_TITLES = re.compile(
    r'\b(owner|founder|co-founder|ceo|president|managing director|'
    r'general manager|practice manager|office manager|chief operating|'
    r'chief marketing|chief revenue|vp of|vice president|director of|'
    r'head of|partner|principal|administrator|medical director|'
    r'dental director|clinic director|spa director|operations manager)\b',
    re.IGNORECASE
)

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


def scrape_company(domain: str) -> tuple[dict[str, str], dict[str, str]]:
    """Scrape key pages from a company domain. Returns (text_content, raw_html)."""
    if not HAS_REQUESTS:
        logging.warning("requests/bs4 not installed, skipping website scrape.")
        return {}, {}

    results = {}
    raw_html = {}
    base_url = f"https://{domain}"
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; ProspectResearcher/1.0)"
    })

    for path in PAGES_TO_SCRAPE:
        url = urljoin(base_url, path)
        try:
            resp = session.get(url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
            if resp.status_code == 200:
                # Store raw HTML for tech detection
                raw_html[path] = resp.text[:5000]
                # Parse clean text
                content = scrape_page(url, session)
                if content:
                    results[path] = content
        except Exception:
            pass
        time.sleep(RATE_LIMIT_DELAY)

    return results, raw_html


def detect_tech_stack(website_content: dict[str, str], raw_html: dict[str, str]) -> list[str]:
    """Detect technology platforms from website content and HTML source."""
    detected = set()
    # Check both rendered text and raw HTML
    all_text = "\n".join(website_content.values())
    all_html = "\n".join(raw_html.values())
    combined = all_text + "\n" + all_html

    for tech, signatures in TECH_SIGNATURES.items():
        for sig in signatures:
            if sig.lower() in combined.lower():
                detected.add(tech)
                break
    return sorted(detected)


def extract_team_members(website_content: dict[str, str]) -> list[dict]:
    """Extract potential decision-makers from team/about pages."""
    members = []
    # Focus on pages most likely to have team info
    team_pages = ["/team", "/our-team", "/staff", "/about", "/about-us"]
    seen_names = set()

    for path in team_pages:
        content = website_content.get(path, "")
        if not content:
            continue

        lines = content.split("\n")
        for i, line in enumerate(lines):
            line = line.strip()
            if not line or len(line) > 100:
                continue
            # Look for title matches in nearby lines
            title_match = DECISION_MAKER_TITLES.search(line)
            if title_match:
                # The name is often the line before or the same line
                title = line
                name = ""
                if i > 0:
                    prev = lines[i - 1].strip()
                    # Names are typically short (2-4 words), start with capitals
                    if prev and len(prev) < 60 and re.match(r'^[A-Z][a-z]', prev):
                        name = prev
                if name and name not in seen_names:
                    seen_names.add(name)
                    members.append({"name": name, "title": title})

    return members[:5]  # Top 5 decision-makers


def detect_competitors_used(website_content: dict[str, str], config: dict) -> list[str]:
    """Detect if the prospect mentions any competitor products."""
    competitors = config.get("competitors", "").split(",")
    all_text = "\n".join(website_content.values()).lower()
    found = []
    for comp in competitors:
        comp = comp.strip()
        if comp and comp.lower() in all_text:
            found.append(comp)
    return found


def analyze_reviews_signals(website_content: dict[str, str]) -> dict:
    """Extract review/testimonial signals that indicate pain points or satisfaction."""
    review_pages = ["/reviews", "/testimonials", "/"]
    signals = {"has_reviews": False, "themes": []}

    for path in review_pages:
        content = website_content.get(path, "").lower()
        if not content:
            continue

        # Check for common pain point mentions
        pain_patterns = {
            "missed_calls": ["missed call", "couldn't get through", "no one answered", "voicemail"],
            "wait_times": ["long wait", "waited", "hold time", "on hold"],
            "scheduling": ["hard to schedule", "booking", "couldn't book", "appointment"],
            "response_time": ["slow response", "never called back", "didn't respond"],
            "front_desk": ["front desk", "receptionist", "rude staff"],
        }
        for theme, patterns in pain_patterns.items():
            if any(p in content for p in patterns):
                signals["has_reviews"] = True
                signals["themes"].append(theme)

    return signals


def load_brief_history() -> dict:
    """Load history of past meeting briefs for the same companies."""
    if os.path.exists(BRIEFS_HISTORY_PATH):
        try:
            with open(BRIEFS_HISTORY_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_brief_history(history: dict):
    """Save meeting brief history."""
    os.makedirs(os.path.dirname(BRIEFS_HISTORY_PATH), exist_ok=True)
    with open(BRIEFS_HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


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
    tech_stack: list[str] = None,
    team_members: list[dict] = None,
    competitors_used: list[str] = None,
    review_signals: dict = None,
    past_briefs: list[str] = None,
) -> str:
    """Use Claude to generate a meeting prep brief for Dylan."""

    site_text = ""
    for path, content in website_content.items():
        site_text += f"\n--- {path} ---\n{content}\n"

    if not site_text:
        site_text = "(Website content not available)"

    # Build intelligence section
    intel_lines = []
    if tech_stack:
        intel_lines.append(f"TECH STACK DETECTED: {', '.join(tech_stack)}")
    if team_members:
        members_str = "; ".join(f"{m['name']} ({m['title']})" for m in team_members)
        intel_lines.append(f"KEY PEOPLE FOUND: {members_str}")
    if competitors_used:
        intel_lines.append(f"COMPETITOR MENTIONS ON SITE: {', '.join(competitors_used)}")
    if review_signals and review_signals.get("themes"):
        intel_lines.append(f"REVIEW PAIN POINTS: {', '.join(review_signals['themes'])}")
    if past_briefs:
        intel_lines.append(f"NOTE: We've briefed on this company {len(past_briefs)} time(s) before. Last: {past_briefs[-1]}")

    intel_section = "\n".join(intel_lines) if intel_lines else "(No additional intelligence)"

    prompt = f"""You are a sales prep assistant for Realside AI. Generate a concise, actionable meeting prep brief for Dylan Mitchell before his call with a prospect.

PROSPECT INFO:
- Name: {contact_name or 'Unknown'}
- Email: {contact_email}
- Company: {company_name or 'Unknown'}
- Domain: {domain or 'Unknown'}
- Reply category: {category}
- Their reply: "{reply_text}"

INTELLIGENCE GATHERED:
{intel_section}

WEBSITE CONTENT SCRAPED:
{site_text}

CASE STUDIES (for reference):
{case_studies[:2000] if case_studies else '(none loaded)'}

REALSIDE AI PRODUCTS:
- AI Inbound Receptionist: Answers all calls 24/7, books appointments, handles FAQs, live transfers. Recovers 20-40% missed calls, adds 10-25% more bookings.
- AI Outbound Agent: Calls/texts new ad leads within 2 min, re-engages dormant CRM leads. 2-3x speed-to-lead, 5-15% database reactivation.
- Pricing: Starts at $2K/month, custom based on volume.

Generate a meeting prep brief with these sections:

1. COMPANY SNAPSHOT (2-3 sentences: what they do, estimated size, location, target market)
2. TECH & TOOLS (what booking/CRM/marketing tools they use based on detection, and what this means for integration)
3. KEY DECISION MAKERS (who Dylan should ask to speak with, based on team members found or typical org structure)
4. LIKELY PAIN POINTS (bullet list of 3-4 pain points. Use review signals if available. Be specific to their business type.)
5. COMPETITIVE LANDSCAPE (if they use competitor tools, how Realside differentiates. If no competitor detected, note the whitespace opportunity.)
6. RECOMMENDED PITCH ANGLE (which product fits best, personalized to their specific situation, 2-3 sentences)
7. RELEVANT CASE STUDY (which case study to reference, the key stat to drop, and how to frame it for this prospect)
8. CONVERSATION STARTERS (3 personalized openers. Reference specific things from their website, recent changes, or team members.)
9. OBJECTION PREP (3 likely objections with suggested responses. Tailor to their business type and reply category.)
10. PRICING STRATEGY (how to anchor price for this prospect specifically. What ROI math to use based on their business.)
11. GOAL FOR THE CALL (clear next step to push for, with a backup goal if the first doesn't land)

Keep it scannable. Use bullet points. Be specific, not generic. Total length: 400-600 words."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
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
    raw_html = {}
    if domain:
        website_content, raw_html = scrape_company(domain)
        logging.info("Scraped %d pages from %s", len(website_content), domain)
    else:
        logging.warning("No domain provided, generating brief without website data.")

    # Step 1b: Extract intelligence from scraped data
    tech_stack = detect_tech_stack(website_content, raw_html) if website_content else []
    team_members = extract_team_members(website_content) if website_content else []
    competitors_used = detect_competitors_used(website_content, config)
    review_signals = analyze_reviews_signals(website_content) if website_content else {}

    if tech_stack:
        logging.info("Tech stack detected: %s", ", ".join(tech_stack))
    if team_members:
        logging.info("Decision makers found: %s", ", ".join(m["name"] for m in team_members))
    if competitors_used:
        logging.info("Competitor mentions: %s", ", ".join(competitors_used))

    # Step 1c: Check brief history for this company
    brief_history = load_brief_history()
    domain_key = (domain or "").lower().replace("www.", "")
    past_briefs = brief_history.get(domain_key, [])

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
        tech_stack=tech_stack,
        team_members=team_members,
        competitors_used=competitors_used,
        review_signals=review_signals,
        past_briefs=past_briefs,
    )
    result["brief_generated"] = True
    result["tech_stack"] = tech_stack
    result["team_members"] = team_members
    result["competitors_detected"] = competitors_used

    # Update brief history
    if domain_key:
        if domain_key not in brief_history:
            brief_history[domain_key] = []
        brief_history[domain_key].append(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        save_brief_history(brief_history)

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
