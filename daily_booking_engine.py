#!/usr/bin/env python3
"""
Daily Meeting Booking Command Center
======================================
Generates a daily action plan to fill Dylan's calendar. Pulls from:
- Instantly reply data (hot leads to call back)
- Engaged prospects tracker (follow-up queue)
- New leads to reach on LinkedIn/phone
- Gmail outreach queue

Run daily at 6:30 AM after the pipeline refresh:
    python daily_booking_engine.py
    python daily_booking_engine.py --goal 3    # Set daily meeting goal
    python daily_booking_engine.py --channels   # Show channel breakdown

Outputs:
    output/daily_action_plan.json   — structured action list
    output/daily_action_plan.txt    — human-readable checklist
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from anthropic import Anthropic


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"

DAILY_MEETING_GOAL = 3  # meetings per day target
MAX_CALLS_PER_DAY = 30
MAX_LINKEDIN_PER_DAY = 25
MAX_EMAILS_PER_DAY = 30  # Instantly limit per account


def load_config():
    with open(BASE_DIR / "config.json") as f:
        return json.load(f)


def load_csv_safe(path):
    """Load CSV, return empty list if file doesn't exist."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return list(csv.DictReader(f))


def load_json_safe(path):
    """Load JSON, return empty list/dict if file doesn't exist."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        data = json.load(f)
        return data if isinstance(data, list) else []


def get_hot_leads():
    """Get leads from reply autopilot that showed interest."""
    processed = load_json_safe(OUTPUT_DIR / "processed_replies.json")
    hot = []
    for r in processed:
        category = r.get("category", r.get("reply_type", ""))
        if category in ("direct_intent", "how_does_it_work", "how_much",
                        "send_proof", "positive_other", "timing"):
            hot.append({
                "name": r.get("contact_name", r.get("from_name", "Unknown")),
                "email": r.get("contact_email", r.get("from_email", "")),
                "company": r.get("company_name", r.get("company", "")),
                "category": category,
                "reply_snippet": r.get("reply_text", r.get("body", ""))[:100],
                "priority": _priority_score(category),
                "action": _action_for_category(category),
                "channel": "call + email"
            })
    hot.sort(key=lambda x: x["priority"], reverse=True)
    return hot


def _priority_score(category):
    scores = {
        "direct_intent": 10,
        "how_much": 8,
        "how_does_it_work": 7,
        "send_proof": 6,
        "timing": 5,
        "positive_other": 4,
    }
    return scores.get(category, 1)


def _action_for_category(category):
    actions = {
        "direct_intent": "CALL NOW — they want to book. Send Calendly if no answer.",
        "how_much": "CALL — price objection, best handled live. Anchor $2K/mo to 40 appointments.",
        "how_does_it_work": "CALL — redirect to demo. 'Best explained on a quick call.'",
        "send_proof": "CALL — offer to walk through case studies live on a 10-min call.",
        "timing": "CALL — acknowledge timing, plant seed for next month. Book future slot.",
        "positive_other": "CALL — warm lead, explore their situation and pitch the demo.",
    }
    return actions.get(category, "Follow up via email")


def get_engaged_prospects():
    """Get prospects in engaged follow-up sequence."""
    engaged = load_csv_safe(OUTPUT_DIR / "engaged_prospects.csv")
    prospects = []
    for p in engaged:
        attempt = int(p.get("follow_up_attempt", p.get("attempt", 0)))
        if attempt < 8:  # Max 8 attempts per playbook
            prospects.append({
                "name": p.get("contact_name", p.get("name", "")),
                "email": p.get("contact_email", p.get("email", "")),
                "company": p.get("company_name", p.get("company", "")),
                "attempt": attempt,
                "last_contact": p.get("last_contact_date", ""),
                "channel": _next_channel(attempt),
                "action": f"Follow-up #{attempt + 1} — {_next_channel(attempt)}"
            })
    return prospects


def _next_channel(attempt):
    """Multi-channel escalation per the reply flow."""
    channels = [
        "email reply",
        "phone call (double-dial)",
        "WhatsApp voice note",
        "text message",
        "LinkedIn connect + message",
        "Facebook friend + DM",
        "Twitter/Instagram DM",
        "final email (break-up)"
    ]
    return channels[min(attempt, len(channels) - 1)]


def get_linkedin_targets():
    """Get fresh leads for LinkedIn outreach from recent campaigns."""
    targets = []

    # Pull from staffing leads (high-value, have LinkedIn URLs)
    staffing = load_json_safe(OUTPUT_DIR / "staffing_leads.json")
    for s in staffing:
        if s.get("linkedin"):
            targets.append({
                "name": s["name"],
                "company": s["company"],
                "title": s["title"],
                "linkedin": s["linkedin"],
                "channel": "LinkedIn",
                "action": "Connect + personalized message"
            })

    # Pull from recruiting leads (have LinkedIn if available)
    recruiting = load_csv_safe(OUTPUT_DIR / "recruiting_leads_750.csv")
    for r in recruiting[:20]:  # Top 20
        li = r.get("linkedin_url", r.get("LinkedIn URL", ""))
        if li:
            targets.append({
                "name": r.get("name", r.get("Full Name", r.get("first_name", ""))),
                "company": r.get("company", r.get("Company", "")),
                "title": r.get("title", r.get("Title", "")),
                "linkedin": li,
                "channel": "LinkedIn",
                "action": "Connect + personalized message"
            })

    return targets[:MAX_LINKEDIN_PER_DAY]


def get_call_list():
    """Build prioritized call list from all sources."""
    calls = []

    # 1. Hot leads from replies (highest priority)
    hot = get_hot_leads()
    for h in hot[:10]:
        calls.append({
            "name": h["name"],
            "company": h["company"],
            "phone": "",  # Would come from ZoomInfo
            "reason": f"REPLIED: {h['category']}",
            "priority": "HIGH",
            "script": h["action"]
        })

    # 2. Staffing agency main lines
    staffing_companies = [
        {"company": "Trustaff", "phone": "(513) 792-8100",
         "ask_for": "Sean Loring (President)", "priority": "HIGH"},
        {"company": "Fusion Medical Staffing", "phone": "(402) 513-1186",
         "ask_for": "Joe Kunes (Chief Sales Officer)", "priority": "HIGH"},
        {"company": "Supplemental Health Care", "phone": "(800) 543-8099",
         "ask_for": "Kelly Mahannah (President, Workforce Solutions)", "priority": "MEDIUM"},
        {"company": "Cross Country Healthcare", "phone": "(561) 998-2232",
         "ask_for": "Dan Walter (Group SVP Enterprise Sales)", "priority": "MEDIUM"},
    ]
    for s in staffing_companies:
        calls.append({
            "name": s["ask_for"],
            "company": s["company"],
            "phone": s["phone"],
            "reason": "Cold outreach — healthcare staffing AI play",
            "priority": s["priority"],
            "script": "Hi, this is Dylan from Realside AI. We build AI employees for staffing agencies that handle candidate intake calls 24/7. Could I speak with [name]?"
        })

    return calls[:MAX_CALLS_PER_DAY]


def get_gmail_queue():
    """Get pending Gmail outreach emails."""
    drafts = load_json_safe(OUTPUT_DIR / "staffing_email_drafts.json")
    unsent = [d for d in drafts if d.get("status") != "sent"]
    return unsent


def generate_daily_plan(goal=DAILY_MEETING_GOAL):
    """Generate the full daily action plan."""
    hot_leads = get_hot_leads()
    engaged = get_engaged_prospects()
    linkedin = get_linkedin_targets()
    calls = get_call_list()
    gmail_queue = get_gmail_queue()

    # Calculate conversion math
    # Industry averages: 2% cold email reply rate, 30% of replies become meetings
    # Phone: 5% connect rate, 20% of connects become meetings
    # LinkedIn: 15% accept rate, 10% of accepts become meetings

    plan = {
        "date": datetime.now().strftime("%Y-%m-%d"),
        "meeting_goal": goal,
        "summary": {
            "hot_leads_to_call": len(hot_leads),
            "engaged_followups": len(engaged),
            "linkedin_targets": len(linkedin),
            "cold_calls": len(calls),
            "gmail_emails_pending": len(gmail_queue),
            "instantly_campaigns_active": "CHECK — activate draft campaigns!"
        },
        "morning_block": {
            "time": "7:00 - 9:00 AM CT",
            "tasks": []
        },
        "midday_block": {
            "time": "11:00 AM - 1:00 PM CT",
            "tasks": []
        },
        "afternoon_block": {
            "time": "1:00 - 3:00 PM CT",
            "tasks": []
        },
        "evening_block": {
            "time": "5:00 - 6:00 PM CT",
            "tasks": []
        }
    }

    # MORNING: Hot leads + calls (highest conversion)
    morning = plan["morning_block"]["tasks"]
    morning.append("CHECK reply autopilot for overnight replies")
    for h in hot_leads[:5]:
        morning.append(f"CALL {h['name']} at {h['company']} — {h['action']}")
        morning.append(f"  Double-dial if no answer")
    for c in calls[:5]:
        morning.append(f"CALL {c['company']} {c['phone']} — ask for {c['name']}")

    # MIDDAY: LinkedIn outreach
    midday = plan["midday_block"]["tasks"]
    midday.append(f"Send {min(len(linkedin), 15)} LinkedIn connection requests with personalized notes")
    for l in linkedin[:5]:
        midday.append(f"  CONNECT: {l['name']} ({l['title']}) at {l['company']}")
    if len(linkedin) > 5:
        midday.append(f"  + {len(linkedin) - 5} more in output/daily_action_plan.json")
    midday.append("Check LinkedIn inbox for any pending message replies")
    midday.append("Send Loom videos to top 2 targets who haven't responded")

    # AFTERNOON: Follow-ups + engaged prospects
    afternoon = plan["afternoon_block"]["tasks"]
    afternoon.append("CHECK reply autopilot for midday replies")
    for e in engaged[:5]:
        afternoon.append(f"FOLLOW UP: {e['name']} at {e['company']} — {e['action']}")
    for c in calls[5:10]:
        afternoon.append(f"CALL {c['company']} {c['phone']} — ask for {c['name']}")

    # EVENING: Prep + queue
    evening = plan["evening_block"]["tasks"]
    evening.append("Review today's conversations, update engaged prospect tracker")
    evening.append("Prep meeting briefs for any calls booked tomorrow")
    evening.append("Queue tomorrow's LinkedIn messages")
    if gmail_queue:
        evening.append(f"Send {len(gmail_queue)} pending Gmail outreach emails")

    # Full lead lists for reference
    plan["all_hot_leads"] = hot_leads
    plan["all_engaged"] = engaged
    plan["all_linkedin"] = linkedin
    plan["all_calls"] = calls
    plan["all_gmail_queue"] = gmail_queue

    return plan


def format_plan_text(plan):
    """Format plan as human-readable text."""
    lines = []
    lines.append(f"{'='*60}")
    lines.append(f"  DAILY MEETING BOOKING PLAN — {plan['date']}")
    lines.append(f"  Goal: {plan['meeting_goal']} meetings today")
    lines.append(f"{'='*60}")
    lines.append("")

    s = plan["summary"]
    lines.append(f"  Hot leads to call back:  {s['hot_leads_to_call']}")
    lines.append(f"  Engaged follow-ups:      {s['engaged_followups']}")
    lines.append(f"  LinkedIn targets:        {s['linkedin_targets']}")
    lines.append(f"  Cold calls queued:       {s['cold_calls']}")
    lines.append(f"  Gmail emails pending:    {s['gmail_emails_pending']}")
    lines.append(f"  Instantly campaigns:     {s['instantly_campaigns_active']}")
    lines.append("")

    for block_name in ["morning_block", "midday_block", "afternoon_block", "evening_block"]:
        block = plan[block_name]
        lines.append(f"{'—'*60}")
        lines.append(f"  {block['time']}")
        lines.append(f"{'—'*60}")
        for task in block["tasks"]:
            if task.startswith("  "):
                lines.append(f"    {task.strip()}")
            else:
                lines.append(f"  [ ] {task}")
        lines.append("")

    lines.append(f"{'='*60}")
    lines.append("  CONVERSION MATH")
    lines.append(f"{'='*60}")
    lines.append("  To book 3 meetings/day, you need ~10 quality conversations.")
    lines.append("  That means:")
    lines.append("    - 30 cold calls (5% connect rate = 1-2 convos)")
    lines.append("    - 30 Instantly emails sending (2% reply = 1 hot lead)")
    lines.append("    - 15 LinkedIn requests (15% accept = 2 convos)")
    lines.append("    - 5 hot lead callbacks (50% book rate = 2-3 meetings)")
    lines.append("    - 5 engaged follow-ups (20% book rate = 1 meeting)")
    lines.append("")
    lines.append("  KEY: Hot lead callbacks are your #1 source. Never let a")
    lines.append("  reply sit more than 5 minutes without a call.")
    lines.append(f"{'='*60}")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Daily meeting booking command center")
    parser.add_argument("--goal", type=int, default=DAILY_MEETING_GOAL,
                        help="Daily meeting goal (default: 3)")
    parser.add_argument("--channels", action="store_true",
                        help="Show channel-by-channel breakdown")
    parser.add_argument("--json-only", action="store_true",
                        help="Output JSON only, no text")
    args = parser.parse_args()

    print(f"\nGenerating daily booking plan (goal: {args.goal} meetings)...\n")

    plan = generate_daily_plan(goal=args.goal)

    # Save JSON
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(OUTPUT_DIR / "daily_action_plan.json", "w") as f:
        json.dump(plan, f, indent=2, default=str)

    # Save and print text
    text = format_plan_text(plan)
    with open(OUTPUT_DIR / "daily_action_plan.txt", "w") as f:
        f.write(text)

    if not args.json_only:
        print(text)

    if args.channels:
        print(f"\n{'='*60}")
        print("  CHANNEL BREAKDOWN")
        print(f"{'='*60}")
        print(f"  Phone calls:     {len(plan['all_calls'])} queued")
        print(f"  LinkedIn:        {len(plan['all_linkedin'])} targets")
        print(f"  Gmail personal:  {len(plan['all_gmail_queue'])} pending")
        print(f"  Hot callbacks:   {len(plan['all_hot_leads'])} leads")
        print(f"  Engaged f/u:     {len(plan['all_engaged'])} prospects")

    print(f"\nSaved to: output/daily_action_plan.json")
    print(f"          output/daily_action_plan.txt")


if __name__ == "__main__":
    main()
