#!/usr/bin/env python3
"""
Pipeline Metrics Exporter — Track reply rates, booking rates, and conversion by campaign.

Pulls data from:
  - output/processed_replies.json (reply classifications and actions)
  - output/engaged_prospects.csv (interested prospects tracker)
  - Instantly API (campaign stats: sent, opened, replied)

Exports to CSV and JSON for use in Google Sheets or BI tools.

Features:
  - Conversion funnel visualization (sent -> opened -> replied -> booked)
  - Best-performing subject line tracking
  - Best time-of-day / day-of-week analysis
  - Campaign comparison (which campaign type converts best)
  - Daily summary that's easy to scan

Usage:
    python pipeline_metrics.py                         # Export all metrics
    python pipeline_metrics.py --format json           # JSON only
    python pipeline_metrics.py --format csv            # CSV only
    python pipeline_metrics.py --output-dir reports/   # Custom output dir
    python pipeline_metrics.py --dry-run               # Preview without saving
    python pipeline_metrics.py --daily-summary         # Print daily summary only
"""

import argparse
import csv
import json
import logging
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta

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
    campaigns = Counter()
    variants_sent = Counter()
    variants_replied = Counter()  # track secondary replies per variant
    responses_sent = 0
    responses_failed = 0

    # Track emails that sent a response, grouped by variant
    responded_emails = {}  # {email: variant}

    for reply_id, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        categories[data.get("category", "unknown")] += 1
        actions[data.get("action", "unknown")] += 1
        sentiments[data.get("sentiment", "unknown")] += 1

        # Campaign attribution
        src = data.get("source_campaign_name") or data.get("source_campaign_id", "unknown")
        if src:
            campaigns[src] += 1

        # A/B variant tracking
        variant = data.get("response_variant", "")
        email = data.get("contact_email", "").lower()
        if data.get("response_sent") and variant:
            variants_sent[variant] += 1
            responded_emails[email] = variant
        elif email in responded_emails:
            # This is a secondary reply (they replied AFTER we sent a variant response)
            prev_variant = responded_emails[email]
            variants_replied[prev_variant] += 1

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

    # Compute variant performance (secondary reply rate per variant)
    variant_performance = {}
    for v, sent_count in variants_sent.items():
        reply_count = variants_replied.get(v, 0)
        variant_performance[v] = {
            "responses_sent": sent_count,
            "secondary_replies": reply_count,
            "secondary_reply_rate": round(reply_count / sent_count * 100, 1) if sent_count > 0 else 0,
        }

    return {
        "total_replies": total,
        "by_category": dict(categories.most_common()),
        "by_action": dict(actions.most_common()),
        "by_sentiment": dict(sentiments.most_common()),
        "by_campaign": dict(campaigns.most_common()),
        "responses_sent": responses_sent,
        "responses_failed": responses_failed,
        "booking_signals": booked,
        "booking_rate": round(booked / total * 100, 1) if total > 0 else 0,
        "interested_total": interested,
        "interest_rate": round(interested / total * 100, 1) if total > 0 else 0,
        "not_interested": categories.get("not_interested", 0) + categories.get("negative_other", 0),
        "variant_performance": variant_performance,
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


def compute_conversion_funnel(campaign_stats: list[dict], processed_replies: dict) -> dict:
    """Compute the full conversion funnel: sent -> opened -> replied -> booked.

    Returns a dict with absolute numbers and stage-to-stage conversion rates.
    """
    total_sent = sum(c.get("emails_sent", 0) for c in campaign_stats)
    total_opened = sum(c.get("emails_opened", 0) for c in campaign_stats)
    total_replied = sum(c.get("emails_replied", 0) for c in campaign_stats)

    # Count bookings from processed replies
    total_booked = 0
    for _rid, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        if data.get("category") in ("direct_intent", "meeting_booked"):
            total_booked += 1

    funnel = {
        "sent": total_sent,
        "opened": total_opened,
        "replied": total_replied,
        "booked": total_booked,
        "sent_to_opened_rate": round(total_opened / total_sent * 100, 1) if total_sent > 0 else 0,
        "opened_to_replied_rate": round(total_replied / total_opened * 100, 1) if total_opened > 0 else 0,
        "replied_to_booked_rate": round(total_booked / total_replied * 100, 1) if total_replied > 0 else 0,
        "sent_to_booked_rate": round(total_booked / total_sent * 100, 1) if total_sent > 0 else 0,
    }
    return funnel


def compute_subject_line_performance(processed_replies: dict) -> list[dict]:
    """Track which subject lines generate the most replies and bookings.

    Returns a list of dicts sorted by reply count descending.
    """
    subject_stats = defaultdict(lambda: {"replies": 0, "bookings": 0, "interested": 0, "not_interested": 0})

    for _rid, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        subject = data.get("original_subject", "") or data.get("subject", "")
        if not subject:
            continue

        subject_stats[subject]["replies"] += 1
        cat = data.get("category", "")
        if cat in ("direct_intent", "meeting_booked"):
            subject_stats[subject]["bookings"] += 1
        if cat not in ("not_interested", "negative_other", "unknown", "error"):
            subject_stats[subject]["interested"] += 1
        if cat in ("not_interested", "negative_other"):
            subject_stats[subject]["not_interested"] += 1

    results = []
    for subject, stats in subject_stats.items():
        total = stats["replies"]
        results.append({
            "subject_line": subject,
            "total_replies": total,
            "bookings": stats["bookings"],
            "interested": stats["interested"],
            "not_interested": stats["not_interested"],
            "booking_rate": round(stats["bookings"] / total * 100, 1) if total > 0 else 0,
            "interest_rate": round(stats["interested"] / total * 100, 1) if total > 0 else 0,
        })

    results.sort(key=lambda x: (-x["bookings"], -x["interested"], -x["total_replies"]))
    return results


def compute_time_analysis(processed_replies: dict) -> dict:
    """Analyze best time-of-day and day-of-week for replies.

    Returns dict with hourly and daily distributions.
    """
    hour_counts = Counter()
    day_counts = Counter()
    hour_bookings = Counter()
    day_bookings = Counter()

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

    for _rid, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        ts = data.get("processed_at", "") or data.get("replied_at", "")
        if not ts:
            continue
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            hour = dt.hour
            day = dt.weekday()  # 0=Monday
            hour_counts[hour] += 1
            day_counts[day] += 1
            if data.get("category") in ("direct_intent", "meeting_booked"):
                hour_bookings[hour] += 1
                day_bookings[day] += 1
        except (ValueError, TypeError):
            pass

    # Best hours (sorted by count)
    hourly = []
    for h in range(24):
        total = hour_counts.get(h, 0)
        bookings = hour_bookings.get(h, 0)
        hourly.append({
            "hour": f"{h:02d}:00",
            "replies": total,
            "bookings": bookings,
            "booking_rate": round(bookings / total * 100, 1) if total > 0 else 0,
        })

    # Best days
    daily = []
    for d in range(7):
        total = day_counts.get(d, 0)
        bookings = day_bookings.get(d, 0)
        daily.append({
            "day": day_names[d],
            "replies": total,
            "bookings": bookings,
            "booking_rate": round(bookings / total * 100, 1) if total > 0 else 0,
        })

    # Find peaks
    best_hour = max(hourly, key=lambda x: x["replies"]) if hourly else None
    best_day = max(daily, key=lambda x: x["replies"]) if daily else None
    best_booking_hour = max(hourly, key=lambda x: x["bookings"]) if hourly else None
    best_booking_day = max(daily, key=lambda x: x["bookings"]) if daily else None

    return {
        "hourly_distribution": hourly,
        "daily_distribution": daily,
        "best_reply_hour": best_hour["hour"] if best_hour and best_hour["replies"] > 0 else "N/A",
        "best_reply_day": best_day["day"] if best_day and best_day["replies"] > 0 else "N/A",
        "best_booking_hour": best_booking_hour["hour"] if best_booking_hour and best_booking_hour["bookings"] > 0 else "N/A",
        "best_booking_day": best_booking_day["day"] if best_booking_day and best_booking_day["bookings"] > 0 else "N/A",
    }


def compute_campaign_comparison(campaign_stats: list[dict], processed_replies: dict) -> list[dict]:
    """Compare campaigns side-by-side ranked by effectiveness.

    Returns a list of campaign dicts sorted by booking rate descending.
    """
    # Count bookings per campaign from processed replies
    campaign_bookings = Counter()
    campaign_interested = Counter()
    for _rid, data in processed_replies.items():
        if not isinstance(data, dict):
            continue
        src = data.get("source_campaign_name") or data.get("source_campaign_id", "")
        cat = data.get("category", "")
        if cat in ("direct_intent", "meeting_booked"):
            campaign_bookings[src] += 1
        if cat not in ("not_interested", "negative_other", "unknown", "error"):
            campaign_interested[src] += 1

    comparison = []
    for c in campaign_stats:
        name = c.get("campaign_name", "Unknown")
        sent = c.get("emails_sent", 0)
        opened = c.get("emails_opened", 0)
        replied = c.get("emails_replied", 0)
        bookings = campaign_bookings.get(name, 0)
        interested = campaign_interested.get(name, 0)

        comparison.append({
            "campaign_name": name,
            "sent": sent,
            "opened": opened,
            "replied": replied,
            "bookings": bookings,
            "interested": interested,
            "open_rate": round(opened / sent * 100, 1) if sent > 0 else 0,
            "reply_rate": round(replied / sent * 100, 1) if sent > 0 else 0,
            "booking_rate": round(bookings / sent * 100, 1) if sent > 0 else 0,
            "efficiency_score": round(
                (bookings * 3 + interested * 1) / sent * 100, 1
            ) if sent > 0 else 0,
        })

    comparison.sort(key=lambda x: (-x["efficiency_score"], -x["booking_rate"]))
    return comparison


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
    funnel = metrics.get("conversion_funnel", {})
    time_analysis = metrics.get("time_analysis", {})
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
        "funnel_sent": funnel.get("sent", 0),
        "funnel_opened": funnel.get("opened", 0),
        "funnel_replied": funnel.get("replied", 0),
        "funnel_booked": funnel.get("booked", 0),
        "funnel_sent_to_booked_pct": funnel.get("sent_to_booked_rate", 0),
        "best_reply_hour": time_analysis.get("best_reply_hour", "N/A"),
        "best_reply_day": time_analysis.get("best_reply_day", "N/A"),
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

    # 5. Subject line performance CSV
    subject_perf = metrics.get("subject_line_performance", [])
    if subject_perf:
        path = os.path.join(output_dir, f"subject_lines_{timestamp}.csv")
        fields = ["subject_line", "total_replies", "bookings", "interested",
                   "not_interested", "booking_rate", "interest_rate"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(subject_perf[:50])  # Top 50
        files.append(path)
        logging.info("Subject line CSV: %s", path)

    # 6. Campaign comparison CSV
    campaign_comp = metrics.get("campaign_comparison", [])
    if campaign_comp:
        path = os.path.join(output_dir, f"campaign_comparison_{timestamp}.csv")
        fields = ["campaign_name", "sent", "opened", "replied", "bookings",
                   "interested", "open_rate", "reply_rate", "booking_rate", "efficiency_score"]
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(campaign_comp)
        files.append(path)
        logging.info("Campaign comparison CSV: %s", path)

    # 7. Time analysis CSV
    hourly = time_analysis.get("hourly_distribution", [])
    if hourly:
        path = os.path.join(output_dir, f"time_analysis_{timestamp}.csv")
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["type", "period", "replies", "bookings", "booking_rate"])
            for h in hourly:
                w.writerow(["hour", h["hour"], h["replies"], h["bookings"], h["booking_rate"]])
            for d in time_analysis.get("daily_distribution", []):
                w.writerow(["day", d["day"], d["replies"], d["bookings"], d["booking_rate"]])
        files.append(path)
        logging.info("Time analysis CSV: %s", path)

    return files


# ---------------------------------------------------------------------------
# Daily summary
# ---------------------------------------------------------------------------


def generate_daily_summary(metrics: dict) -> str:
    """Generate a scannable daily summary string for Dylan.

    Designed to be read in 30 seconds or less.
    """
    rm = metrics.get("reply_metrics", {})
    em = metrics.get("engaged_metrics", {})
    ttb = metrics.get("time_to_book", {})
    funnel = metrics.get("conversion_funnel", {})
    time_analysis = metrics.get("time_analysis", {})
    subject_perf = metrics.get("subject_line_performance", [])
    campaign_comp = metrics.get("campaign_comparison", [])

    lines = []
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    lines.append(f"PIPELINE DAILY SUMMARY - {today}")
    lines.append("=" * 55)

    # Conversion Funnel
    lines.append("")
    lines.append("CONVERSION FUNNEL:")
    sent = funnel.get("sent", 0)
    opened = funnel.get("opened", 0)
    replied = funnel.get("replied", 0)
    booked = funnel.get("booked", 0)

    if sent > 0:
        # ASCII bar chart
        max_val = max(sent, 1)
        bar_width = 30
        sent_bar = "#" * bar_width
        opened_bar = "#" * max(1, round(opened / max_val * bar_width))
        replied_bar = "#" * max(1, round(replied / max_val * bar_width)) if replied > 0 else ""
        booked_bar = "#" * max(1, round(booked / max_val * bar_width)) if booked > 0 else ""

        lines.append(f"  Sent:    {sent_bar} {sent}")
        lines.append(f"  Opened:  {opened_bar} {opened} ({funnel.get('sent_to_opened_rate', 0)}%)")
        lines.append(f"  Replied: {replied_bar} {replied} ({funnel.get('opened_to_replied_rate', 0)}%)")
        lines.append(f"  Booked:  {booked_bar} {booked} ({funnel.get('replied_to_booked_rate', 0)}%)")
        lines.append(f"  Overall: {funnel.get('sent_to_booked_rate', 0)}% sent-to-book")
    else:
        lines.append("  (No campaign data available)")

    # Key Numbers
    lines.append("")
    lines.append("KEY NUMBERS:")
    lines.append(f"  Replies processed: {rm.get('total_replies', 0)}")
    lines.append(f"  Responses sent:    {rm.get('responses_sent', 0)}")
    lines.append(f"  Booking signals:   {rm.get('booking_signals', 0)} ({rm.get('booking_rate', 0)}%)")
    lines.append(f"  Interest rate:     {rm.get('interest_rate', 0)}%")
    lines.append(f"  Not interested:    {rm.get('not_interested', 0)}")
    lines.append(f"  Engaged total:     {em.get('total_engaged', 0)}")

    if ttb.get("avg_hours_to_book"):
        lines.append(f"  Avg time to book:  {ttb['avg_hours_to_book']}h")

    # Best Subject Lines
    if subject_perf:
        lines.append("")
        lines.append("TOP SUBJECT LINES:")
        for i, s in enumerate(subject_perf[:5]):
            booking_str = f" [{s['bookings']} bookings]" if s["bookings"] > 0 else ""
            lines.append(f"  {i+1}. \"{s['subject_line'][:60]}\" - {s['total_replies']} replies{booking_str}")

    # Best Timing
    if time_analysis.get("best_reply_hour") != "N/A":
        lines.append("")
        lines.append("BEST TIMING:")
        lines.append(f"  Best hour for replies:  {time_analysis.get('best_reply_hour', 'N/A')}")
        lines.append(f"  Best day for replies:   {time_analysis.get('best_reply_day', 'N/A')}")
        lines.append(f"  Best hour for bookings: {time_analysis.get('best_booking_hour', 'N/A')}")
        lines.append(f"  Best day for bookings:  {time_analysis.get('best_booking_day', 'N/A')}")

    # Campaign Ranking
    if campaign_comp:
        lines.append("")
        lines.append("CAMPAIGN RANKING (by efficiency):")
        for i, c in enumerate(campaign_comp[:5]):
            name = c["campaign_name"]
            # Trim the "Realside AI - " prefix for readability
            name = name.replace("Realside AI ", "").strip(" -\u2014")
            lines.append(
                f"  {i+1}. {name[:35]:35s} "
                f"sent:{c['sent']:4d}  opened:{c['open_rate']:5.1f}%  "
                f"replied:{c['reply_rate']:5.1f}%  booked:{c['booking_rate']:5.1f}%"
            )

    # Variant A/B Performance
    variant_perf = rm.get("variant_performance", {})
    if variant_perf:
        lines.append("")
        lines.append("A/B VARIANT PERFORMANCE:")
        for v, vdata in sorted(variant_perf.items(),
                                key=lambda x: -x[1].get("secondary_reply_rate", 0)):
            lines.append(
                f"  {v}: {vdata['responses_sent']} sent, "
                f"{vdata['secondary_replies']} re-replies "
                f"({vdata['secondary_reply_rate']}%)"
            )

    lines.append("")
    lines.append("=" * 55)

    return "\n".join(lines)


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
    conversion_funnel = compute_conversion_funnel(campaign_stats, processed_replies)
    subject_line_performance = compute_subject_line_performance(processed_replies)
    time_analysis = compute_time_analysis(processed_replies)
    campaign_comparison = compute_campaign_comparison(campaign_stats, processed_replies)

    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reply_metrics": reply_metrics,
        "engaged_metrics": engaged_metrics,
        "time_to_book": time_to_book,
        "campaign_stats": campaign_stats,
        "conversion_funnel": conversion_funnel,
        "subject_line_performance": subject_line_performance,
        "time_analysis": time_analysis,
        "campaign_comparison": campaign_comparison,
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
    """Print the daily summary to the console."""
    summary = generate_daily_summary(metrics)
    print("\n" + summary)


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
    parser.add_argument("--daily-summary", action="store_true",
                        help="Print daily summary to console only (no export)")

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

    if args.dry_run or args.daily_summary:
        logging.info("Computing metrics...")
        processed = load_processed_replies(script_dir)
        engaged = load_engaged_prospects(script_dir)

        # Fetch campaign stats even for summary/dry-run
        campaign_stats = []
        api_key = config.get("instantly_api_key", "")
        if api_key and not args.dry_run:
            campaign_stats = fetch_campaign_stats(api_key)

        reply_metrics = compute_reply_metrics(processed)
        metrics = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "reply_metrics": reply_metrics,
            "engaged_metrics": compute_engaged_metrics(engaged),
            "time_to_book": compute_time_to_book(processed),
            "campaign_stats": campaign_stats,
            "conversion_funnel": compute_conversion_funnel(campaign_stats, processed),
            "subject_line_performance": compute_subject_line_performance(processed),
            "time_analysis": compute_time_analysis(processed),
            "campaign_comparison": compute_campaign_comparison(campaign_stats, processed),
        }
        _print_summary(metrics)
    else:
        generate_metrics(config, output_dir=output_dir, export_format=args.format)


if __name__ == "__main__":
    main()
