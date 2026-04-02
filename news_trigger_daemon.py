#!/usr/bin/env python3
"""
News Trigger Daemon — Continuous Monitoring for Buying Signals
==============================================================
Monitors Google News RSS for target accounts every 4 hours.
When a trigger event is detected (funding, expansion, leadership change, M&A),
auto-generates and queues a timely outreach email.

Usage:
    python news_trigger_daemon.py                    # Run continuous daemon
    python news_trigger_daemon.py --once             # Single pass, then exit
    python news_trigger_daemon.py --interval 14400   # Custom interval (seconds)
    python news_trigger_daemon.py --dry-run          # Generate but don't queue
"""

import argparse
import csv
import json
import logging
import os
import signal
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

try:
    import requests
except ImportError:
    print("Install requests: pip install requests")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Install anthropic: pip install anthropic")
    sys.exit(1)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = str(BASE_DIR / "config.json")
DEFAULT_INTERVAL = 4 * 60 * 60  # 4 hours
SEEN_ARTICLES_PATH = str(BASE_DIR / "output/news_daemon_seen.json")
QUEUED_OUTPUT_PATH = str(BASE_DIR / "output/news_triggered_daemon.csv")
LOG_PATH = str(BASE_DIR / "output/news_daemon.log")

TRIGGER_KEYWORDS = [
    "expands", "expansion", "opens new", "new locations",
    "funding", "raises", "investment", "acquires", "merger",
    "appoints", "hires", "named CEO", "named President",
    "partnership", "launches", "record revenue", "growth",
]

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logging.info("Shutdown signal received.")
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(fh)
    root.addHandler(ch)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def load_seen(path: str) -> set:
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return set(json.load(f))
        except Exception:
            pass
    return set()


def save_seen(path: str, seen: set):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def fetch_news(company_name: str) -> list:
    """Fetch Google News RSS for a company and return relevant articles."""
    query = quote_plus(f'"{company_name}" dental')
    url = f"https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en"
    try:
        resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        articles = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            articles.append({
                "title": title,
                "link": link,
                "pub_date": pub_date,
                "description": description,
            })
        return articles
    except Exception as e:
        logging.debug("News fetch failed for %s: %s", company_name, e)
        return []


def is_trigger_article(title: str, description: str) -> bool:
    text = (title + " " + description).lower()
    return any(kw.lower() in text for kw in TRIGGER_KEYWORDS)


def generate_trigger_email(
    client: anthropic.Anthropic,
    company_name: str,
    article_title: str,
    article_url: str,
    cfg: dict,
) -> dict:
    calendar = cfg.get("calendar_link", "https://calendly.com/realsideai")
    sender = cfg.get("sender_name", "Dylan Mitchell").split()[0]
    prompt = f"""Write a short cold outreach email (under 100 words) referencing this news about {company_name}.

News: "{article_title}"
Source: {article_url}

You're Dylan from Realside AI. Realside AI builds AI Employees for dental/service businesses:
- AI Inbound Receptionist: answers calls 24/7, books appointments, handles FAQs
- AI Outbound Agent: calls new leads in <2 min, reactivates dormant patients

Rules:
- Lead with the news as a hook ("Saw that {company_name} is expanding...")
- Tie it to a relevant pain point (more locations = more calls to manage)
- End with calendar CTA: {calendar}
- Friendly, confident, no em-dashes
- Sign: {sender}

Return ONLY JSON with "subject" and "body" keys."""

    try:
        resp = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=512,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text.strip()
        import re
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except Exception as e:
        logging.error("Email generation failed: %s", e)
    return {
        "subject": f"Quick thought on {company_name}'s expansion",
        "body": f"Hi,\n\nSaw the news about {company_name} — congrats on the momentum.\n\nAs you scale, managing inbound calls across every new location gets expensive fast. Realside AI's AI Receptionist handles that 24/7 automatically.\n\nWorth 15 min? {calendar}\n\n{sender}",
    }


def append_to_output(row: dict):
    """Append a triggered email to the output CSV."""
    os.makedirs(os.path.dirname(QUEUED_OUTPUT_PATH), exist_ok=True)
    fieldnames = ["company_name", "domain", "contact_email", "subject", "body",
                  "trigger_article", "trigger_url", "generated_at"]
    file_exists = os.path.exists(QUEUED_OUTPUT_PATH)
    with open(QUEUED_OUTPUT_PATH, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)


def run_once(cfg: dict, seen: set, dry_run: bool = False) -> tuple[int, set]:
    """Single monitoring pass. Returns (new_triggers_found, updated_seen)."""
    anthropic_key = cfg.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    client = anthropic.Anthropic(api_key=anthropic_key)

    # Get companies to monitor from targets.csv + icp_prospects.csv
    companies = {}
    for csv_path in [
        str(BASE_DIR / cfg.get("targets_csv", "targets.csv")),
        str(BASE_DIR / cfg.get("output_dir", "output") / "icp_prospects.csv"),
    ]:
        if not os.path.exists(csv_path):
            continue
        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    name = row.get("company_name", "")
                    domain = row.get("domain", "")
                    if name and domain:
                        companies[domain] = {"company_name": name, "domain": domain}
        except Exception:
            pass

    if not companies:
        logging.info("No companies to monitor. Run pipeline first to build targets.csv.")
        return 0, seen

    logging.info("Monitoring %d companies for news triggers...", len(companies))
    triggers_found = 0

    for domain, info in companies.items():
        if _shutdown:
            break
        company_name = info["company_name"]
        articles = fetch_news(company_name)
        for article in articles:
            article_id = article.get("link", article.get("title", ""))
            if article_id in seen:
                continue
            seen.add(article_id)

            title = article.get("title", "")
            desc = article.get("description", "")
            if not is_trigger_article(title, desc):
                continue

            logging.info("TRIGGER: %s — %s", company_name, title[:80])
            triggers_found += 1

            if dry_run:
                logging.info("[DRY-RUN] Would generate email for: %s", title[:80])
                continue

            email = generate_trigger_email(client, company_name, title,
                                           article.get("link", ""), cfg)
            row = {
                "company_name": company_name,
                "domain": domain,
                "contact_email": f"contact@{domain}",
                "subject": email.get("subject", ""),
                "body": email.get("body", ""),
                "trigger_article": title,
                "trigger_url": article.get("link", ""),
                "generated_at": datetime.now(timezone.utc).isoformat(),
            }
            append_to_output(row)
            logging.info("Queued trigger email for %s: %s", company_name, email.get("subject", "")[:60])

        time.sleep(1)  # polite rate limiting

    return triggers_found, seen


def main():
    parser = argparse.ArgumentParser(description="News Trigger Daemon")
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="Check interval in seconds (default: 14400 = 4 hours)")
    parser.add_argument("--once", action="store_true", help="Run once and exit")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    setup_logging()
    cfg = load_config(args.config)
    seen = load_seen(SEEN_ARTICLES_PATH)

    logging.info("News Trigger Daemon starting (interval=%ds)", args.interval)

    if args.once:
        triggers, seen = run_once(cfg, seen, dry_run=args.dry_run)
        save_seen(SEEN_ARTICLES_PATH, seen)
        logging.info("Single pass complete. %d new triggers found.", triggers)
        return

    cycle = 0
    while not _shutdown:
        cycle += 1
        logging.info("--- Cycle %d ---", cycle)
        try:
            triggers, seen = run_once(cfg, seen, dry_run=args.dry_run)
            save_seen(SEEN_ARTICLES_PATH, seen)
            logging.info("Cycle %d complete. %d triggers found.", cycle, triggers)
        except Exception as e:
            logging.error("Cycle %d error: %s", cycle, e)

        # Sleep in increments for responsive shutdown
        slept = 0
        while slept < args.interval and not _shutdown:
            time.sleep(min(30, args.interval - slept))
            slept += 30

    logging.info("News Trigger Daemon stopped.")


if __name__ == "__main__":
    main()
