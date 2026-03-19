#!/usr/bin/env python3
"""
Open Tracker Daemon — Fires breakthrough emails to prospects who opened but never replied.

Logic:
  - Every 4 hours, poll Instantly for leads who opened your email 2+ times
  - Skip leads who already replied or who already received an open-triggered email
  - Generate a short, curiosity-sparking breakthrough email with Claude
  - Send immediately via Instantly unibox
  - Track in output/open_tracker.json to avoid duplicate sends

Why it fills calendars:
  - Someone who opens 2-3 times is clearly interested but didn't reply
  - A personalized breakthrough at that moment converts 10-15% to a booked call
  - Fully automated — no manual review needed

Usage:
    python open_tracker_daemon.py                   # Daemon loop (every 4 hours)
    python open_tracker_daemon.py --once            # Single pass, then exit
    python open_tracker_daemon.py --dry-run         # Generate but don't send
    python open_tracker_daemon.py --interval 7200   # Custom interval (seconds)
"""

import argparse
import json
import logging
import os
import re
import signal
import sys
import time
from datetime import datetime, timezone

try:
    import requests
except ImportError:
    print("Error: requests required. pip install requests")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Error: anthropic required. pip install anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.instantly.ai/api/v2"
DEFAULT_CONFIG = "config.json"
DEFAULT_INTERVAL = 4 * 60 * 60  # 4 hours
OPEN_TRACKER_PATH = "output/open_tracker.json"
LOG_PATH = "output/open_tracker.log"
MIN_OPENS_TO_TRIGGER = 2  # fire after 2+ opens

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logging.info("Shutdown signal — stopping after current cycle.")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def setup_logging(log_path: str):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


def load_tracker(path: str) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_tracker(path: str, data: dict):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Instantly API
# ---------------------------------------------------------------------------


def _api(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(4):
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            else:
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            if resp.status_code == 429:
                time.sleep(2 ** (attempt + 1))
                continue
            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json() if resp.text else {}
        except requests.RequestException as e:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
            else:
                return {"error": str(e)}
    return {"error": "max retries"}


def _extract_items(result) -> list:
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for k in ("data", "items", "leads", "emails"):
            v = result.get(k)
            if isinstance(v, list):
                return v
    return []


def get_campaigns(api_key: str) -> list:
    result = _api("GET", "/campaigns", api_key, {"limit": 100})
    return _extract_items(result)


def get_leads_with_opens(api_key: str, campaign_id: str) -> list:
    """
    Fetch leads from a campaign who have opened emails.
    Tries multiple endpoint strategies.
    """
    # Strategy 1: analytics/leads/activity
    result = _api("POST", "/analytics/campaign/leads/activity", api_key, {
        "campaign_id": campaign_id,
        "limit": 200,
    })
    items = _extract_items(result)
    if items:
        return items

    # Strategy 2: leads endpoint with limit, filter client-side
    result = _api("GET", "/leads", api_key, {
        "campaign_id": campaign_id,
        "limit": 200,
    })
    items = _extract_items(result)
    if items:
        return items

    # Strategy 3: analytics/campaign/overview to get lead list
    result = _api("POST", "/analytics/campaign/overview", api_key, {
        "id": campaign_id,
        "limit": 200,
    })
    items = _extract_items(result)
    return items


def get_lead_stats(api_key: str, campaign_id: str, lead_email: str) -> dict:
    """Get open/reply stats for a specific lead."""
    result = _api("GET", "/leads", api_key, {
        "campaign_id": campaign_id,
        "email": lead_email,
    })
    items = _extract_items(result)
    if items:
        return items[0]
    return {}


def send_breakthrough_email(
    api_key: str,
    from_email: str,
    to_email: str,
    subject: str,
    body: str,
    campaign_id: str,
) -> bool:
    """Send a breakthrough follow-up through Instantly unibox."""
    payload = {
        "from": from_email,
        "to": to_email,
        "subject": subject,
        "body": {"html": body.replace("\n", "<br>"), "text": body},
        "campaign_id": campaign_id,
    }
    # Try unibox/emails/send
    result = _api("POST", "/unibox/emails/send", api_key, payload)
    if "error" not in result:
        return True
    # Try unibox reply as fallback
    result = _api("POST", "/unibox/emails/reply", api_key, payload)
    return "error" not in result


# ---------------------------------------------------------------------------
# Claude: generate breakthrough email
# ---------------------------------------------------------------------------


def _parse_json(text: str) -> dict:
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def generate_breakthrough_email(
    client: anthropic.Anthropic,
    contact_name: str,
    company_name: str,
    opens_count: int,
    original_subject: str,
    calendar_link: str,
    sender_name: str,
) -> dict:
    """Generate a short, high-converting breakthrough email for an opener."""
    first = sender_name.split()[0] if sender_name else "Dylan"
    prompt = f"""You are an expert SDR for Realside AI (AI Employees for service businesses — dental, med spas, wellness).

A prospect at {company_name} opened our email {opens_count} times but never replied.
Their name: {contact_name or "there"}
Original email subject: {original_subject or "(unknown)"}

Write a VERY short breakthrough email (under 80 words) that:
- Acknowledges nothing creepy (don't say "I saw you opened")
- Hits a fresh pain point specific to multi-location dental/service businesses
- Creates curiosity — don't explain the product
- Ends with a direct, low-friction CTA to our calendar: {calendar_link}
- Never use dashes of any kind (no -- or em dashes or en dashes)
- Sign off with first name only: {first}
- Tone: human, confident, not salesy

Return ONLY JSON with keys "subject" and "body" (plain text, \\n for newlines)."""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _parse_json(response.content[0].text)
        if "subject" not in result or "body" not in result:
            raise ValueError("missing keys")
        return result
    except Exception as e:
        logging.error("Breakthrough email generation failed: %s", e)
        first_name = contact_name.split()[0] if contact_name else "there"
        return {
            "subject": "Quick thought",
            "body": (
                f"Hi {first_name},\n\n"
                f"Had a quick idea for {company_name} that I think would be worth 10 minutes.\n\n"
                f"Here's my calendar: {calendar_link}\n\n"
                f"Best,\n{first}"
            ),
        }


# ---------------------------------------------------------------------------
# Core: find opener leads and fire breakthrough emails
# ---------------------------------------------------------------------------


def _get_opens(lead: dict) -> int:
    """Extract open count from a lead record (various field names)."""
    for key in ("opens", "open_count", "times_opened", "email_opens", "opened_count"):
        v = lead.get(key)
        if isinstance(v, int) and v > 0:
            return v
    # Some APIs nest stats
    stats = lead.get("stats") or lead.get("analytics") or {}
    if isinstance(stats, dict):
        for key in ("opens", "open_count", "times_opened"):
            v = stats.get(key)
            if isinstance(v, int) and v > 0:
                return v
    return 0


def _has_replied(lead: dict) -> bool:
    """Check if a lead has already replied."""
    status = str(lead.get("status", "")).lower()
    if "replied" in status or "reply" in status:
        return True
    for key in ("replied", "has_reply", "reply_count", "replies"):
        v = lead.get(key)
        if v and v not in (0, False, "", "0"):
            return True
    return False


def run_once(config: dict, tracker: dict, dry_run: bool = False) -> dict:
    """Single pass: find openers across all campaigns, send breakthroughs."""
    api_key = config["instantly_api_key"]
    anthropic_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    calendar = config.get("calendar_link", "https://calendly.com/realsideai")
    sender_email = config.get("sender_email", "dylan.realside@gmail.com")
    sender_name = config.get("sender_name", "Dylan Mitchell")

    client = anthropic.Anthropic(api_key=anthropic_key)

    stats = {
        "campaigns_checked": 0,
        "leads_scanned": 0,
        "openers_found": 0,
        "breakthroughs_sent": 0,
        "skipped": 0,
        "errors": 0,
    }

    campaigns = get_campaigns(api_key)
    if not campaigns:
        logging.info("No campaigns found.")
        return stats

    stats["campaigns_checked"] = len(campaigns)
    logging.info("Scanning %d campaigns for openers...", len(campaigns))

    for campaign in campaigns:
        if _shutdown:
            break

        campaign_id = campaign.get("id", "")
        campaign_name = campaign.get("name", "Unnamed")
        if not campaign_id:
            continue

        leads = get_leads_with_opens(api_key, campaign_id)
        stats["leads_scanned"] += len(leads)

        for lead in leads:
            if _shutdown:
                break

            email = (
                lead.get("email")
                or lead.get("lead_email")
                or lead.get("from_email")
                or ""
            ).strip().lower()

            if not email:
                continue

            # Already sent a breakthrough to this lead?
            tracker_key = f"{campaign_id}:{email}"
            if tracker_key in tracker:
                continue

            opens = _get_opens(lead)
            replied = _has_replied(lead)

            if opens < MIN_OPENS_TO_TRIGGER or replied:
                continue

            stats["openers_found"] += 1
            contact_name = (
                lead.get("first_name", "")
                + (" " + lead.get("last_name", "") if lead.get("last_name") else "")
            ).strip() or lead.get("name", "") or ""
            company_name = lead.get("company_name") or lead.get("company") or ""
            original_subject = lead.get("subject") or lead.get("email_subject") or ""

            logging.info(
                "Opener: %s <%s> at %s — %d opens, no reply. Campaign: %s",
                contact_name, email, company_name, opens, campaign_name,
            )

            try:
                email_data = generate_breakthrough_email(
                    client=client,
                    contact_name=contact_name,
                    company_name=company_name,
                    opens_count=opens,
                    original_subject=original_subject,
                    calendar_link=calendar,
                    sender_name=sender_name,
                )

                subject = email_data["subject"]
                body = email_data["body"]

                if dry_run:
                    logging.info("[DRY-RUN] Would send to %s: %s", email, subject)
                    logging.debug("[DRY-RUN] Body: %s", body[:200])
                    sent = True  # count as sent in dry-run for stats
                else:
                    sent = send_breakthrough_email(
                        api_key=api_key,
                        from_email=sender_email,
                        to_email=email,
                        subject=subject,
                        body=body,
                        campaign_id=campaign_id,
                    )
                    if sent:
                        logging.info("Breakthrough sent to %s (%s)", email, company_name)
                    else:
                        logging.warning("Failed to send breakthrough to %s", email)

                if sent:
                    stats["breakthroughs_sent"] += 1

                # Mark as processed regardless of send result (avoid spam)
                tracker[tracker_key] = {
                    "sent_at": datetime.now(timezone.utc).isoformat(),
                    "email": email,
                    "company": company_name,
                    "opens": opens,
                    "subject": subject,
                    "dry_run": dry_run,
                }

            except Exception as e:
                logging.error("Error processing opener %s: %s", email, e, exc_info=True)
                stats["errors"] += 1
                tracker[tracker_key] = {"error": str(e), "sent_at": datetime.now(timezone.utc).isoformat()}

    return stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(description="Open Tracker Daemon")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="Poll interval in seconds (default: 14400 = 4h)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config if os.path.isabs(args.config) else os.path.join(script_dir, args.config)
    log_path = os.path.join(script_dir, LOG_PATH)
    tracker_path = os.path.join(script_dir, OPEN_TRACKER_PATH)

    setup_logging(log_path)

    logging.info("=" * 60)
    logging.info("OPEN TRACKER DAEMON starting")
    logging.info("Interval: %ds | Dry-run: %s | Once: %s", args.interval, args.dry_run, args.once)
    logging.info("=" * 60)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logging.error("Could not load config: %s", e)
        sys.exit(1)

    tracker = load_tracker(tracker_path)

    if args.once:
        stats = run_once(config, tracker, dry_run=args.dry_run)
        save_tracker(tracker_path, tracker)
        logging.info(
            "Done. campaigns=%d leads_scanned=%d openers=%d breakthroughs=%d errors=%d",
            stats["campaigns_checked"], stats["leads_scanned"],
            stats["openers_found"], stats["breakthroughs_sent"], stats["errors"],
        )
        return

    cycle = 0
    while not _shutdown:
        cycle += 1
        logging.info("--- Open tracker cycle %d ---", cycle)
        try:
            stats = run_once(config, tracker, dry_run=args.dry_run)
            save_tracker(tracker_path, tracker)
            logging.info(
                "Cycle %d done. leads_scanned=%d openers=%d breakthroughs_sent=%d",
                cycle, stats["leads_scanned"], stats["openers_found"], stats["breakthroughs_sent"],
            )
        except Exception as e:
            logging.error("Cycle %d failed: %s", cycle, e, exc_info=True)

        if _shutdown:
            break

        slept = 0
        while slept < args.interval and not _shutdown:
            time.sleep(min(30, args.interval - slept))
            slept += 30

    logging.info("Open tracker daemon stopped.")


if __name__ == "__main__":
    main()
