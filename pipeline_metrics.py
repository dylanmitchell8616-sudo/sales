#!/usr/bin/env python3
"""
Pipeline Metrics Exporter — Track reply rates, booking rates, and conversion by campaign.

Pulls data from:
  - output/processed_replies.json (reply classifications and actions)
  - output/engaged_prospects.csv (interested prospects tracker)
  - Instantly API (campaign stats: sent, opened, replied)

Exports to CSV and JSON for use in Google Sheets or BI tools.

Usage:
    python pipeline_metrics.py                         # Export all metrics
    python pipeline_metrics.py --format json           # JSON only
    python pipeline_metrics.py --format csv            # CSV only
    python pipeline_metrics.py --output-dir reports/   # Custom output dir
    python pipeline_metrics.py --dry-run               # Preview without saving
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_CONFIG_PATH = "config.json"
PROCESSED_REPLIES_PATH = "output/processed_replies.json"
ENGAGED_TRACKER_PATH = "output/engaged_prospects.csv"
DEFAULT_OUTPUT_DIR = "output/metrics"
BASE_URL = "https://api.instantly.ai/api/v2"

# ---------------------------------------------------------------------------
# Instantly API helper
# ---------------------------------------------------------------------------


def api_request(method: str, endpoint: str, api_key: str, params: dict = None) -> dict:
    """Make an authenticated request to the Instantly V2 API."""
    if not HAS_REQUESTS:
        return {"error": "requests not installed"}

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(4):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                logging.warning("Rate limited, waiting %ds...", wait)
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json() if resp.text else {}
        except requests.exceptions.RequestException as e:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
            else:
                return {"error": str(e)}

    return {"error": "Max retries exceeded"}


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------


def load_processed_replies(script_dir: str) -> dict:
    """Load processed replies JSON."""
    path = os.path.join(script_dir, PROCESSED_REPLIES_PATH)
    if not os.path.exists(path):
        logging.warning("No processed replies file at %s", path)
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logging.error("Failed to load processed replies: %s", e)
        return {}


def load_engaged_prospects(script_dir: str) -> list[dict]:
    """Load engaged prospects CSV."""
    path = os.path.join(script_dir, ENGAGED_TRACKER_PATH)
    if not os.path.exists(path):
        logging.warning("No engaged prospects file at %s", path)
        return []
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception as e:
        logging.error("Failed to load engaged prospects: %s", e)
        return []


def fetch_campaign_stats(api_key: str) -> list[dict]:
    """Fetch campaign-level analytics from Instantly."""
    result = api_request("GET", "/campaigns", api_key, {"limit": 100})
    if "error" in result:
        logging.warning("Could not fetch campaigns: %s", result.get("error", "")[:200])
        return []

    campaigns = []
    if isinstance(result, list):
        campaigns = result
    elif isinstance(result, dict):
        campaigns = result.get("data", result.get("items", []))

    stats = []
    for c in campaigns:
        cid = c.get("id", "")
        name = c.get("name", "Unnamed")
        if not cid:
            continue

        # Fetch analytics for this campaign
        analytics = api_request("GET", f"/campaigns/{cid}/analytics", api_key)
        if "error" in analytics:
            # Try alternate endpoint
            analytics = api_request("GET", "/campaigns/analytics", api_key, {"campaign_id": cid})

        sent = 0
        opened = 0
        replied = 0
        bounced = 0

        if isinstance(analytics, dict) and "error" not in analytics:
            sent = analytics.get("total_sent", analytics.get("sent", 0)) or 0
            opened = analytics.get("total_opened", analytics.get("opened", 0)) or 0
            replied = analytics.get("total_replied", analytics.get("replied", 0)) or 0
            bounced = analytics.get("total_bounced", analytics.get("bounced", 0)) or 0

        stats.append({
            "campaign_id": cid,
            "campaign_name": name,
            "status": c.get("status", "unknown"),
            "emails_sent": sent,
            "emails_opened": opened,
            "emails_replied": replied,
            "emails_bounced": bounced,
            "open_rate": round(opened / sent * 100, 1) if sent > 0 else 0,
            "reply_rate": round(replied / sent * 100, 1) if sent > 0 else 0,
            "bounce_rate": round(bounced / sent * 100, 1) if sent > 0 else 0,
        })

    return stats


# ---------------------------------------------------------------------------
# Metrics computation
# ---------------------------------------------------------------------------


def compute_reply_metrics(processed_replies: dict) -> dict:
    """Compute reply classification and conversion metrics."""
    if not processed_replies:
        return {
            "total_replies": 0,
            "by_category": {},
            "by_action": {},
            "by_sentiment": {},
            "responses_sent": 0,
            "responses_failed": 0,
            "booking_rate": 0,
            "interest_rate": 0,
        }

    categories = Counter()
    actions = Counter()
    sentiments = Counter()
    responses_sent = 0
    responses_failed = 0

    for reply_id, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        categories[data.get("category", "unknown")] += 1
        actions[data.get("action", "unknown")] += 1
        sentiments[data.get("sentiment", "unknown")] += 1
        if data.get("response_sent"):
            responses_sent += 1
        if data.get("action") == "auto_reply_failed":
            responses_failed += 1

    total = len(processed_replies)
    booked = categories.get("meeting_booked", 0) + categories.get("direct_intent", 0)
    interested = sum(
        v for k, v in categories.items()
        if k not in ("not_interested", "negative_other", "unknown", "error")
    )

    return {
        "total_replies": total,
        "by_category": dict(categories.most_common()),
        "by_action": dict(actions.most_common()),
        "by_sentiment": dict(sentiments.most_common()),
        "responses_sent": responses_sent,
        "responses_failed": responses_failed,
        "booking_signals": booked,
        "booking_rate": round(booked / total * 100, 1) if total > 0 else 0,
        "interested_total": interested,
        "interest_rate": round(interested / total * 100, 1) if total > 0 else 0,
        "not_interested": categories.get("not_interested", 0) + categories.get("negative_other", 0),
    }


def compute_engaged_metrics(prospects: list[dict]) -> dict:
    """Compute engaged prospect metrics."""
    if not prospects:
        return {
            "total_engaged": 0,
            "by_status": {},
            "by_category": {},
            "timeline": [],
        }

    statuses = Counter()
    categories = Counter()
    daily = defaultdict(int)

    for p in prospects:
        statuses[p.get("status", "unknown")] += 1
        categories[p.get("reply_category", "unknown")] += 1
        added = p.get("added_at", "")
        if added:
            day = added[:10]
            daily[day] += 1

    timeline = [{"date": d, "prospects_added": c} for d, c in sorted(daily.items())]

    return {
        "total_engaged": len(prospects),
        "by_status": dict(statuses.most_common()),
        "by_category": dict(categories.most_common()),
        "timeline": timeline,
    }


def compute_time_to_book(processed_replies: dict) -> dict:
    """Estimate average time from first reply to booking signal."""
    # Group by email
    by_email = defaultdict(list)
    for reply_id, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        email = data.get("contact_email", "")
        if email:
            by_email[email].append(data)

    booking_times = []
    for email, replies in by_email.items():
        sorted_replies = sorted(replies, key=lambda r: r.get("processed_at", ""))
        first_ts = sorted_replies[0].get("processed_at", "")
        book_ts = None
        for r in sorted_replies:
            if r.get("category") in ("direct_intent", "meeting_booked"):
                book_ts = r.get("processed_at", "")
                break

        if first_ts and book_ts and first_ts != book_ts:
            try:
                t1 = datetime.fromisoformat(first_ts.replace("Z", "+00:00"))
                t2 = datetime.fromisoformat(book_ts.replace("Z", "+00:00"))
                hours = (t2 - t1).total_seconds() / 3600
                if hours > 0:
                    booking_times.append(hours)
            except Exception:
                pass

    return {
        "prospects_with_booking_signal": len(booking_times),
        "avg_hours_to_book": round(sum(booking_times) / len(booking_times), 1) if booking_times else 0,
        "min_hours_to_book": round(min(booking_times), 1) if booking_times else 0,
        "max_hours_to_book": round(max(booking_times), 1) if booking_times else 0,
    }


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------


def export_json(metrics: dict, output_dir: str) -> str:
    """Export all metrics to a JSON file."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"pipeline_metrics_{timestamp}.json")

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2, default=str)

    logging.info("Metrics exported to %s", filepath)
    return filepath


def export_csv(metrics: dict, output_dir: str) -> list[str]:
    """Export metrics to multiple CSV files for Google Sheets import."""
    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    files = []

    # 1. Campaign performance CSV
    campaigns = metrics.get("campaign_stats", [])
    if campaigns:
        path = os.path.join(output_dir, f"campaign_performance_{timestamp}.csv")
        fields = [
            "campaign_name", "status", "emails_sent", "emails_opened",
            "emails_replied", "emails_bounced", "open_rate", "reply_rate", "bounce_rate",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(campaigns)
        files.append(path)
        logging.info("Campaign CSV: %s", path)

    # 2. Reply breakdown CSV
    reply_metrics = metrics.get("reply_metrics", {})
    by_cat = reply_metrics.get("by_category", {})
    if by_cat:
        path = os.path.join(output_dir, f"reply_breakdown_{timestamp}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["category", "count", "percentage"])
            total = reply_metrics.get("total_replies", 1)
            for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
                w.writerow([cat, count, round(count / total * 100, 1)])
        files.append(path)
        logging.info("Reply breakdown CSV: %s", path)

    # 3. Summary metrics CSV (single row for easy dashboard import)
    path = os.path.join(output_dir, f"summary_{timestamp}.csv")
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_replies": reply_metrics.get("total_replies", 0),
        "responses_sent": reply_metrics.get("responses_sent", 0),
        "booking_signals": reply_metrics.get("booking_signals", 0),
        "booking_rate_pct": reply_metrics.get("booking_rate", 0),
        "interest_rate_pct": reply_metrics.get("interest_rate", 0),
        "not_interested": reply_metrics.get("not_interested", 0),
        "total_engaged": metrics.get("engaged_metrics", {}).get("total_engaged", 0),
        "engaged_booked": metrics.get("engaged_metrics", {}).get("by_status", {}).get("booked", 0),
        "engaged_interested": metrics.get("engaged_metrics", {}).get("by_status", {}).get("interested", 0),
        "avg_hours_to_book": metrics.get("time_to_book", {}).get("avg_hours_to_book", 0),
    }
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary.keys()))
        w.writeheader()
        w.writerow(summary)
    files.append(path)
    logging.info("Summary CSV: %s", path)

    # 4. Engaged prospect timeline CSV
    timeline = metrics.get("engaged_metrics", {}).get("timeline", [])
    if timeline:
        path = os.path.join(output_dir, f"engaged_timeline_{timestamp}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["date", "prospects_added"])
            w.writeheader()
            w.writerows(timeline)
        files.append(path)
        logging.info("Timeline CSV: %s", path)

    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_metrics(config: dict, output_dir: str = None, export_format: str = "both") -> dict:
    """Generate all pipeline metrics and export them.

    Returns the full metrics dict.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    if output_dir is None:
        output_dir = os.path.join(script_dir, DEFAULT_OUTPUT_DIR)

    logging.info("Generating pipeline metrics...")

    # Load local data
    processed_replies = load_processed_replies(script_dir)
    engaged_prospects = load_engaged_prospects(script_dir)

    # Fetch campaign stats from Instantly
    campaign_stats = []
    api_key = config.get("instantly_api_key", "")
    if api_key:
        logging.info("Fetching campaign stats from Instantly...")
        campaign_stats = fetch_campaign_stats(api_key)
        logging.info("Fetched stats for %d campaigns.", len(campaign_stats))
    else:
        logging.warning("No Instantly API key, skipping campaign stats.")

    # Compute metrics
    reply_metrics = compute_reply_metrics(processed_replies)
    engaged_metrics = compute_engaged_metrics(engaged_prospects)
    time_to_book = compute_time_to_book(processed_replies)

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reply_metrics": reply_metrics,
        "engaged_metrics": engaged_metrics,
        "time_to_book": time_to_book,
        "campaign_stats": campaign_stats,
    }

    # Export
    if export_format in ("json", "both"):
        export_json(metrics, output_dir)
    if export_format in ("csv", "both"):
        export_csv(metrics, output_dir)

    # Print summary to console
    _print_summary(metrics)

    return metrics


def _print_summary(metrics: dict):
    """Print a quick summary to the console."""
    rm = metrics.get("reply_metrics", {})
    em = metrics.get("engaged_metrics", {})
    ttb = metrics.get("time_to_book", {})
    cs = metrics.get("campaign_stats", [])

    print("\n" + "=" * 55)
    print("  PIPELINE METRICS SUMMARY")
    print("=" * 55)

    print(f"\n  Replies Processed:     {rm.get('total_replies', 0)}")
    print(f"  Responses Sent:        {rm.get('responses_sent', 0)}")
    print(f"  Booking Signals:       {rm.get('booking_signals', 0)}")
    print(f"  Booking Rate:          {rm.get('booking_rate', 0)}%")
    print(f"  Interest Rate:         {rm.get('interest_rate', 0)}%")
    print(f"  Not Interested:        {rm.get('not_interested', 0)}")

    print(f"\n  Engaged Prospects:     {em.get('total_engaged', 0)}")
    statuses = em.get("by_status", {})
    for status, count in statuses.items():
        print(f"    {status}: {count}")

    if ttb.get("avg_hours_to_book"):
        print(f"\n  Avg Time to Book:      {ttb['avg_hours_to_book']}h")
        print(f"  Min:                   {ttb['min_hours_to_book']}h")
        print(f"  Max:                   {ttb['max_hours_to_book']}h")

    if cs:
        total_sent = sum(c.get("emails_sent", 0) for c in cs)
        total_opened = sum(c.get("emails_opened", 0) for c in cs)
        total_replied = sum(c.get("emails_replied", 0) for c in cs)
        print(f"\n  Campaigns:             {len(cs)}")
        print(f"  Total Emails Sent:     {total_sent}")
        print(f"  Total Opens:           {total_opened}")
        print(f"  Total Replies:         {total_replied}")
        if total_sent > 0:
            print(f"  Overall Open Rate:     {round(total_opened / total_sent * 100, 1)}%")
            print(f"  Overall Reply Rate:    {round(total_replied / total_sent * 100, 1)}%")

    print("\n" + "=" * 55)


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline Metrics Exporter",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Config file path")
    parser.add_argument("--format", choices=["csv", "json", "both"], default="both",
                        help="Export format (default: both)")
    parser.add_argument("--output-dir", default=None, help="Output directory")
    parser.add_argument("--dry-run", action="store_true", help="Preview metrics without saving")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Load config
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(script_dir, config_path)

    try:
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception as e:
        logging.error("Could not load config: %s", e)
        sys.exit(1)

    output_dir = args.output_dir
    if output_dir and not os.path.isabs(output_dir):
        output_dir = os.path.join(script_dir, output_dir)

    if args.dry_run:
        logging.info("[DRY-RUN] Computing metrics (no files will be saved)...")
        # Still compute and print, just skip export
        processed = load_processed_replies(script_dir)
        engaged = load_engaged_prospects(script_dir)
        metrics = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "reply_metrics": compute_reply_metrics(processed),
            "engaged_metrics": compute_engaged_metrics(engaged),
            "time_to_book": compute_time_to_book(processed),
            "campaign_stats": [],
        }
        _print_summary(metrics)
    else:
        generate_metrics(config, output_dir=output_dir, export_format=args.format)


if __name__ == "__main__":
    main()
