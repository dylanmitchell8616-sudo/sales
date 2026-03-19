#!/usr/bin/env python3
"""
Realside AI - Campaign Tracker & Cost-Per-Meeting Calculator
Tracks all outreach channels, calculates CPM, and generates weekly reports.
Uses CSV files for simplicity — no database needed.
"""

import csv
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

BASE_DIR = Path(__file__).resolve().parent.parent
TRACKING_DIR = BASE_DIR / "tracking"
OUTPUT_DIR = BASE_DIR / "output" / "reports"


def ensure_tracking_files():
    """Create tracking CSV files if they don't exist."""
    os.makedirs(TRACKING_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    files = {
        "daily_activity.csv": [
            "date", "channel", "leads_contacted", "emails_sent", "connections_sent",
            "videos_recorded", "replies_received", "positive_replies",
            "meetings_booked", "meetings_held", "deals_closed", "revenue", "spend", "notes"
        ],
        "meetings_log.csv": [
            "date", "contact_name", "company", "industry", "channel_source",
            "sequence_used", "meeting_status", "deal_value", "next_steps", "notes"
        ],
        "monthly_costs.csv": [
            "month", "instantly_cost", "apollo_cost", "domains_cost", "google_workspace_cost",
            "loom_cost", "linkedin_ads_cost", "other_costs", "total_cost"
        ],
    }

    for filename, headers in files.items():
        filepath = TRACKING_DIR / filename
        if not filepath.exists():
            with open(filepath, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
            print(f"  ✓ Created {filename}")

    return True


def log_daily_activity(date, channel, metrics):
    """Log daily activity for a channel."""
    filepath = TRACKING_DIR / "daily_activity.csv"
    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            date,
            channel,
            metrics.get("leads_contacted", 0),
            metrics.get("emails_sent", 0),
            metrics.get("connections_sent", 0),
            metrics.get("videos_recorded", 0),
            metrics.get("replies_received", 0),
            metrics.get("positive_replies", 0),
            metrics.get("meetings_booked", 0),
            metrics.get("meetings_held", 0),
            metrics.get("deals_closed", 0),
            metrics.get("revenue", 0),
            metrics.get("spend", 0),
            metrics.get("notes", ""),
        ])
    print(f"  ✓ Logged {channel} activity for {date}")


def log_meeting(meeting_data):
    """Log a meeting to the meetings tracker."""
    filepath = TRACKING_DIR / "meetings_log.csv"
    with open(filepath, "a", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([
            meeting_data.get("date", datetime.now().strftime("%Y-%m-%d")),
            meeting_data["contact_name"],
            meeting_data["company"],
            meeting_data.get("industry", ""),
            meeting_data["channel_source"],
            meeting_data.get("sequence_used", ""),
            meeting_data.get("meeting_status", "scheduled"),
            meeting_data.get("deal_value", 0),
            meeting_data.get("next_steps", ""),
            meeting_data.get("notes", ""),
        ])
    print(f"  ✓ Logged meeting with {meeting_data['contact_name']} at {meeting_data['company']}")


def generate_weekly_report():
    """Generate a weekly performance report from tracking data."""
    activity_file = TRACKING_DIR / "daily_activity.csv"
    meetings_file = TRACKING_DIR / "meetings_log.csv"

    if not activity_file.exists():
        print("No activity data found. Run 'init' first and start logging activity.")
        return

    # Load activity data
    activities = []
    with open(activity_file, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            activities.append(row)

    # Load meetings data
    meetings = []
    if meetings_file.exists():
        with open(meetings_file, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                meetings.append(row)

    if not activities:
        print("No activity data logged yet. Start logging daily activity first.")
        return

    # Calculate metrics by channel
    channel_metrics = defaultdict(lambda: {
        "emails_sent": 0, "leads_contacted": 0, "replies": 0,
        "positive_replies": 0, "meetings_booked": 0, "meetings_held": 0,
        "deals_closed": 0, "revenue": 0, "spend": 0
    })

    for a in activities:
        ch = a["channel"]
        channel_metrics[ch]["emails_sent"] += int(a.get("emails_sent", 0) or 0)
        channel_metrics[ch]["leads_contacted"] += int(a.get("leads_contacted", 0) or 0)
        channel_metrics[ch]["replies"] += int(a.get("replies_received", 0) or 0)
        channel_metrics[ch]["positive_replies"] += int(a.get("positive_replies", 0) or 0)
        channel_metrics[ch]["meetings_booked"] += int(a.get("meetings_booked", 0) or 0)
        channel_metrics[ch]["meetings_held"] += int(a.get("meetings_held", 0) or 0)
        channel_metrics[ch]["deals_closed"] += int(a.get("deals_closed", 0) or 0)
        channel_metrics[ch]["revenue"] += float(a.get("revenue", 0) or 0)
        channel_metrics[ch]["spend"] += float(a.get("spend", 0) or 0)

    # Generate report
    report = []
    report.append("=" * 70)
    report.append("REALSIDE AI - MARKETING PERFORMANCE REPORT")
    report.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    report.append(f"Data range: {activities[0]['date']} to {activities[-1]['date']}")
    report.append("=" * 70)

    total_meetings = 0
    total_spend = 0
    total_revenue = 0

    for channel, m in sorted(channel_metrics.items()):
        report.append(f"\n{'─' * 50}")
        report.append(f"CHANNEL: {channel.upper()}")
        report.append(f"{'─' * 50}")

        reply_rate = (m["replies"] / m["emails_sent"] * 100) if m["emails_sent"] > 0 else 0
        meeting_rate = (m["meetings_booked"] / m["positive_replies"] * 100) if m["positive_replies"] > 0 else 0
        cpm = (m["spend"] / m["meetings_booked"]) if m["meetings_booked"] > 0 else 0
        close_rate = (m["deals_closed"] / m["meetings_held"] * 100) if m["meetings_held"] > 0 else 0

        report.append(f"  Leads Contacted:   {m['leads_contacted']}")
        report.append(f"  Emails Sent:       {m['emails_sent']}")
        report.append(f"  Replies:           {m['replies']} ({reply_rate:.1f}% reply rate)")
        report.append(f"  Positive Replies:  {m['positive_replies']}")
        report.append(f"  Meetings Booked:   {m['meetings_booked']} ({meeting_rate:.1f}% booking rate)")
        report.append(f"  Meetings Held:     {m['meetings_held']}")
        report.append(f"  Deals Closed:      {m['deals_closed']} ({close_rate:.1f}% close rate)")
        report.append(f"  Revenue:           ${m['revenue']:,.2f}")
        report.append(f"  Spend:             ${m['spend']:,.2f}")
        report.append(f"  Cost Per Meeting:  ${cpm:,.2f}")

        if m["revenue"] > 0 and m["spend"] > 0:
            roi = ((m["revenue"] - m["spend"]) / m["spend"]) * 100
            report.append(f"  ROI:               {roi:,.0f}%")

        total_meetings += m["meetings_booked"]
        total_spend += m["spend"]
        total_revenue += m["revenue"]

    # Totals
    report.append(f"\n{'=' * 70}")
    report.append("TOTALS")
    report.append(f"{'=' * 70}")
    report.append(f"  Total Meetings Booked:  {total_meetings}")
    report.append(f"  Total Spend:            ${total_spend:,.2f}")
    report.append(f"  Total Revenue:          ${total_revenue:,.2f}")
    overall_cpm = (total_spend / total_meetings) if total_meetings > 0 else 0
    report.append(f"  Overall Cost/Meeting:   ${overall_cpm:,.2f}")
    if total_revenue > 0 and total_spend > 0:
        overall_roi = ((total_revenue - total_spend) / total_spend) * 100
        report.append(f"  Overall ROI:            {overall_roi:,.0f}%")

    # Meeting source breakdown
    if meetings:
        report.append(f"\n{'=' * 70}")
        report.append("MEETING SOURCE BREAKDOWN")
        report.append(f"{'=' * 70}")
        source_counts = defaultdict(int)
        for mtg in meetings:
            source_counts[mtg.get("channel_source", "unknown")] += 1
        for source, count in sorted(source_counts.items(), key=lambda x: -x[1]):
            pct = (count / len(meetings)) * 100
            report.append(f"  {source}: {count} meetings ({pct:.0f}%)")

    report_text = "\n".join(report)

    # Save report
    report_filename = f"report_{datetime.now().strftime('%Y%m%d')}.txt"
    report_path = OUTPUT_DIR / report_filename
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(report_path, "w") as f:
        f.write(report_text)

    print(report_text)
    print(f"\n✓ Report saved to: {report_path}")
    return report_text


def print_usage():
    print("""
Realside AI - Campaign Tracker

Usage:
  python campaign_tracker.py init                    Initialize tracking files
  python campaign_tracker.py report                  Generate performance report
  python campaign_tracker.py log-activity            Log daily channel activity (interactive)
  python campaign_tracker.py log-meeting             Log a meeting (interactive)
  python campaign_tracker.py targets                 Show monthly targets and current progress

Examples:
  python scripts/campaign_tracker.py init
  python scripts/campaign_tracker.py report
""")


def interactive_log_activity():
    """Interactive daily activity logger."""
    print("\n📊 Log Daily Activity")
    print("─" * 40)

    date = input("Date (YYYY-MM-DD, or Enter for today): ").strip()
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    channels = ["cold_email", "linkedin_organic", "linkedin_ads", "loom_video", "referral", "webinar", "facebook_groups"]
    print("\nChannels:")
    for i, ch in enumerate(channels, 1):
        print(f"  {i}. {ch}")
    ch_idx = int(input("Select channel (number): ")) - 1
    channel = channels[ch_idx]

    metrics = {}
    metric_prompts = [
        ("leads_contacted", "Leads contacted"),
        ("emails_sent", "Emails sent"),
        ("connections_sent", "Connection requests sent"),
        ("videos_recorded", "Videos recorded"),
        ("replies_received", "Replies received"),
        ("positive_replies", "Positive replies"),
        ("meetings_booked", "Meetings booked"),
        ("meetings_held", "Meetings held"),
        ("deals_closed", "Deals closed"),
        ("revenue", "Revenue ($)"),
        ("spend", "Spend ($)"),
    ]

    for key, prompt in metric_prompts:
        val = input(f"  {prompt} (0): ").strip()
        metrics[key] = float(val) if val else 0

    notes = input("  Notes: ").strip()
    metrics["notes"] = notes

    log_daily_activity(date, channel, metrics)


def interactive_log_meeting():
    """Interactive meeting logger."""
    print("\n📅 Log Meeting")
    print("─" * 40)

    meeting_data = {
        "date": input("Date (YYYY-MM-DD, or Enter for today): ").strip() or datetime.now().strftime("%Y-%m-%d"),
        "contact_name": input("Contact name: ").strip(),
        "company": input("Company: ").strip(),
        "industry": input("Industry: ").strip(),
        "channel_source": input("Source channel (cold_email/linkedin/loom/referral/webinar): ").strip(),
        "sequence_used": input("Sequence used (crm_reactivation/voice_agent/combo): ").strip(),
        "meeting_status": input("Status (scheduled/held/no-show/cancelled): ").strip() or "scheduled",
        "deal_value": input("Estimated deal value ($): ").strip() or "0",
        "next_steps": input("Next steps: ").strip(),
        "notes": input("Notes: ").strip(),
    }

    log_meeting(meeting_data)


def show_targets():
    """Show monthly targets vs actual progress."""
    print("\n" + "=" * 60)
    print("MONTHLY TARGETS vs ACTUALS")
    print("=" * 60)

    targets = {
        "cold_email": {"meetings_target": 50, "budget": 242, "target_cpm": 4.84},
        "linkedin_organic": {"meetings_target": 15, "budget": 0, "target_cpm": 0},
        "loom_video": {"meetings_target": 15, "budget": 15, "target_cpm": 1.00},
        "webinar": {"meetings_target": 10, "budget": 0, "target_cpm": 0},
        "facebook_groups": {"meetings_target": 5, "budget": 0, "target_cpm": 0},
        "linkedin_ads": {"meetings_target": 5, "budget": 500, "target_cpm": 100},
    }

    total_target = 0
    total_budget = 0

    for channel, t in targets.items():
        total_target += t["meetings_target"]
        total_budget += t["budget"]
        print(f"\n  {channel}:")
        print(f"    Target: {t['meetings_target']} meetings/mo")
        print(f"    Budget: ${t['budget']}/mo")
        print(f"    Target CPM: ${t['target_cpm']:.2f}")

    print(f"\n{'─' * 60}")
    print(f"  TOTAL TARGET: {total_target} meetings/month")
    print(f"  TOTAL BUDGET: ${total_budget}/month")
    overall_cpm = total_budget / total_target if total_target > 0 else 0
    print(f"  BLENDED CPM:  ${overall_cpm:.2f}/meeting")
    print(f"{'─' * 60}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    command = sys.argv[1]

    if command == "init":
        print("\nInitializing tracking files...")
        ensure_tracking_files()
        print("\n✓ Tracking system ready! Start logging activity with: python campaign_tracker.py log-activity")
    elif command == "report":
        generate_weekly_report()
    elif command == "log-activity":
        ensure_tracking_files()
        interactive_log_activity()
    elif command == "log-meeting":
        ensure_tracking_files()
        interactive_log_meeting()
    elif command == "targets":
        show_targets()
    else:
        print_usage()
