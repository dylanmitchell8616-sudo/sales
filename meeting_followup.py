#!/usr/bin/env python3
"""
Meeting Follow-Up Automation
=============================
Generates and sends post-call follow-up emails after meetings with prospects.
Tracks meeting outcomes and triggers appropriate next steps.

Usage:
    python meeting_followup.py --prospect "Jane Doe" --company "Acme Dental" \
        --email jane@acmedental.com --outcome booked_demo --notes "Interested in inbound AI"
    python meeting_followup.py --prospect "John Smith" --company "Smith HVAC" \
        --email john@smithhvac.com --outcome needs_followup --notes "Wants to talk to partner first"
    python meeting_followup.py --list   # Show recent meeting outcomes
"""

import argparse
import json
import logging
import os
import smtplib
import sys
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
MEETINGS_LOG = os.path.join(OUTPUT_DIR, "meetings_log.json")
FOLLOWUPS_DIR = os.path.join(OUTPUT_DIR, "meeting_followups")
DEFAULT_CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")

# Meeting outcomes and their follow-up strategies
OUTCOME_STRATEGIES = {
    "booked_demo": {
        "label": "Demo Booked",
        "urgency": "high",
        "followup_delay_hours": 1,
        "tone": "excited, confirming",
        "goal": "Confirm demo details, send calendar invite, set expectations",
    },
    "needs_followup": {
        "label": "Needs Follow-Up",
        "urgency": "medium",
        "followup_delay_hours": 24,
        "tone": "patient, value-adding",
        "goal": "Provide the info they requested, gently re-engage toward booking",
    },
    "send_proposal": {
        "label": "Send Proposal",
        "urgency": "high",
        "followup_delay_hours": 2,
        "tone": "professional, thorough",
        "goal": "Send customized proposal with pricing, ROI math, and next steps",
    },
    "warm_not_ready": {
        "label": "Warm but Not Ready",
        "urgency": "low",
        "followup_delay_hours": 72,
        "tone": "casual, no-pressure",
        "goal": "Stay top of mind, share relevant content, check back in a few weeks",
    },
    "objection_raised": {
        "label": "Objection Raised",
        "urgency": "medium",
        "followup_delay_hours": 4,
        "tone": "empathetic, reframing",
        "goal": "Address the specific objection with proof/case study, redirect to next call",
    },
    "no_show": {
        "label": "No Show",
        "urgency": "medium",
        "followup_delay_hours": 1,
        "tone": "understanding, brief",
        "goal": "Quick note saying no worries, offer to reschedule with one-click option",
    },
    "closed_lost": {
        "label": "Closed Lost",
        "urgency": "none",
        "followup_delay_hours": 0,
        "tone": "gracious",
        "goal": "Thank them, leave the door open, add to quarterly check-in list",
    },
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)


# ---------------------------------------------------------------------------
# Meeting log management
# ---------------------------------------------------------------------------

def load_meetings_log() -> list:
    if os.path.exists(MEETINGS_LOG):
        try:
            with open(MEETINGS_LOG) as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return []


def save_meetings_log(log: list):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(MEETINGS_LOG, "w") as f:
        json.dump(log, f, indent=2, default=str)


def log_meeting(prospect: str, company: str, email: str, outcome: str,
                notes: str, followup_sent: bool = False) -> dict:
    """Log a meeting outcome."""
    log = load_meetings_log()
    entry = {
        "id": len(log) + 1,
        "prospect": prospect,
        "company": company,
        "email": email,
        "outcome": outcome,
        "outcome_label": OUTCOME_STRATEGIES.get(outcome, {}).get("label", outcome),
        "notes": notes,
        "meeting_date": datetime.now(timezone.utc).isoformat(),
        "followup_sent": followup_sent,
        "followup_date": None,
    }
    log.append(entry)
    save_meetings_log(log)
    return entry


# ---------------------------------------------------------------------------
# Follow-up email generation with Claude
# ---------------------------------------------------------------------------

def generate_followup_email(
    config: dict,
    prospect: str,
    company: str,
    email: str,
    outcome: str,
    notes: str,
) -> dict:
    """Generate a post-meeting follow-up email using Claude."""
    api_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logging.error("No Anthropic API key configured")
        return {"subject": "", "body": ""}

    strategy = OUTCOME_STRATEGIES.get(outcome, OUTCOME_STRATEGIES["needs_followup"])

    # Load campaign memory if available
    memory_context = ""
    try:
        from campaign_memory_loader import get_memory_prompt
        memory_context = get_memory_prompt(campaign_type="followup")
    except ImportError:
        pass

    client = anthropic.Anthropic(api_key=api_key)

    prompt = f"""You are writing a post-meeting follow-up email for Dylan Mitchell at Realside AI.

MEETING DETAILS:
- Prospect: {prospect}
- Company: {company}
- Outcome: {strategy['label']}
- Dylan's notes: "{notes}"

FOLLOW-UP STRATEGY:
- Tone: {strategy['tone']}
- Goal: {strategy['goal']}

{memory_context}

SENDER: Dylan Mitchell, Realside AI
PRODUCTS: AI Inbound Receptionist (24/7 call answering, appointment booking) and AI Outbound Agent (speed-to-lead, CRM reactivation). Starts at $2K/month.

Write a follow-up email with:
1. Subject line (personalized, not generic)
2. Email body

Rules:
- Keep under 120 words
- Reference something specific from the meeting notes
- Never use dashes (--) in the email
- End with a clear, low-friction next step
- Sign off as "Dylan" (not "Best regards" or "Sincerely")
- If outcome is "booked_demo": confirm the demo, build anticipation
- If outcome is "needs_followup": provide value, don't be pushy
- If outcome is "send_proposal": reference what was discussed, tease the ROI
- If outcome is "no_show": keep it super short, empathetic, offer reschedule
- If outcome is "objection_raised": address the objection with a relevant proof point
- If outcome is "warm_not_ready": share a relevant insight, no hard sell
- If outcome is "closed_lost": thank them graciously, leave door open

Format response as:
SUBJECT: [subject line]
---
[email body]"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()

        # Parse subject and body
        if "SUBJECT:" in text and "---" in text:
            parts = text.split("---", 1)
            subject = parts[0].replace("SUBJECT:", "").strip()
            body = parts[1].strip()
        else:
            subject = f"Great connecting, {prospect.split()[0] if prospect else 'there'}"
            body = text

        return {"subject": subject, "body": body}
    except Exception as e:
        logging.error("Failed to generate follow-up: %s", e)
        return {"subject": f"Following up, {prospect}", "body": f"Hi {prospect},\n\nGreat connecting today. {notes}\n\nLet me know what days work for next steps.\n\nDylan"}


# ---------------------------------------------------------------------------
# Email sending
# ---------------------------------------------------------------------------

def send_followup_smtp(config: dict, to_email: str, subject: str, body: str) -> bool:
    """Send follow-up via SMTP."""
    sender = config.get("sender_email", "dylan.realside@gmail.com")
    password = config.get("smtp_app_password", "") or os.environ.get("SMTP_APP_PASSWORD", "")
    if not password:
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain", "utf-8"))
    html_body = body.replace("\n", "<br>")
    msg.attach(MIMEText(f"<html><body style='font-family: Arial, sans-serif;'>{html_body}</body></html>", "html", "utf-8"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(sender, password)
            server.send_message(msg)
        return True
    except Exception as e:
        logging.error("SMTP send failed: %s", e)
        return False


def send_followup_instantly(config: dict, to_email: str, subject: str, body: str) -> bool:
    """Send follow-up via Instantly API."""
    if not HAS_REQUESTS:
        return False
    api_key = config.get("instantly_api_key", "")
    if not api_key:
        return False

    sender = config.get("sender_email", "dylan.realside@gmail.com")
    url = "https://api.instantly.ai/api/v2/unibox/emails/send"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "from": sender,
        "to": to_email,
        "subject": subject,
        "body": {"html": body.replace("\n", "<br>"), "text": body},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=30)
        return resp.status_code < 400
    except Exception as e:
        logging.error("Instantly send failed: %s", e)
        return False


def save_followup_to_file(prospect: str, company: str, subject: str, body: str, outcome: str) -> str:
    """Save follow-up email to file."""
    os.makedirs(FOLLOWUPS_DIR, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = "".join(c if c.isalnum() else "_" for c in (company or prospect or "unknown").lower())
    filepath = os.path.join(FOLLOWUPS_DIR, f"{timestamp}_{safe_name}_{outcome}.txt")

    with open(filepath, "w") as f:
        f.write(f"TO: {prospect} at {company}\n")
        f.write(f"OUTCOME: {outcome}\n")
        f.write(f"SUBJECT: {subject}\n")
        f.write(f"{'='*50}\n\n")
        f.write(body)

    return filepath


# ---------------------------------------------------------------------------
# Main flow
# ---------------------------------------------------------------------------

def process_meeting_followup(
    config: dict,
    prospect: str,
    company: str,
    email: str,
    outcome: str,
    notes: str,
    dry_run: bool = False,
) -> dict:
    """Full flow: generate follow-up, send it, log the meeting."""
    result = {
        "followup_generated": False,
        "email_sent": False,
        "file_saved": False,
        "meeting_logged": False,
    }

    if outcome not in OUTCOME_STRATEGIES:
        logging.error("Unknown outcome: %s. Options: %s", outcome, ", ".join(OUTCOME_STRATEGIES.keys()))
        return result

    strategy = OUTCOME_STRATEGIES[outcome]

    # Skip sending for closed_lost
    if outcome == "closed_lost":
        logging.info("Closed lost. Logging but not sending follow-up.")
        log_meeting(prospect, company, email, outcome, notes, followup_sent=False)
        result["meeting_logged"] = True
        return result

    # Generate follow-up email
    logging.info("Generating %s follow-up for %s at %s...", strategy['label'], prospect, company)
    followup = generate_followup_email(config, prospect, company, email, outcome, notes)

    if not followup.get("body"):
        logging.error("Failed to generate follow-up email")
        return result

    result["followup_generated"] = True
    logging.info("Subject: %s", followup["subject"])

    # Save to file
    filepath = save_followup_to_file(prospect, company, followup["subject"], followup["body"], outcome)
    result["file_saved"] = True
    logging.info("Saved to %s", filepath)

    if dry_run:
        logging.info("[DRY RUN] Would send to %s", email)
        logging.info("Preview:\n%s", followup["body"])
        log_meeting(prospect, company, email, outcome, notes, followup_sent=False)
        result["meeting_logged"] = True
        return result

    # Send email
    sent = send_followup_smtp(config, email, followup["subject"], followup["body"])
    if not sent:
        sent = send_followup_instantly(config, email, followup["subject"], followup["body"])

    result["email_sent"] = sent
    if sent:
        logging.info("Follow-up sent to %s", email)
    else:
        logging.warning("Could not send follow-up (no email method configured). Saved to: %s", filepath)

    # Log meeting
    log_meeting(prospect, company, email, outcome, notes, followup_sent=sent)
    result["meeting_logged"] = True

    return result


def show_recent_meetings():
    """Display recent meeting outcomes."""
    log = load_meetings_log()
    if not log:
        print("No meetings logged yet.")
        return

    print(f"\n{'='*70}")
    print(f"  RECENT MEETINGS ({len(log)} total)")
    print(f"{'='*70}")
    print(f"  {'Date':12s} {'Prospect':20s} {'Company':20s} {'Outcome':15s}")
    print(f"  {'-'*12} {'-'*20} {'-'*20} {'-'*15}")

    for m in log[-15:]:
        date = m.get("meeting_date", "")[:10]
        prospect = (m.get("prospect", "")[:18] + "..") if len(m.get("prospect", "")) > 20 else m.get("prospect", "")
        company = (m.get("company", "")[:18] + "..") if len(m.get("company", "")) > 20 else m.get("company", "")
        outcome = m.get("outcome_label", m.get("outcome", ""))
        sent = "sent" if m.get("followup_sent") else "pending"
        print(f"  {date:12s} {prospect:20s} {company:20s} {outcome:15s} [{sent}]")

    # Summary stats
    outcomes = {}
    for m in log:
        o = m.get("outcome", "unknown")
        outcomes[o] = outcomes.get(o, 0) + 1

    print(f"\n  Outcome Distribution:")
    for outcome, count in sorted(outcomes.items(), key=lambda x: -x[1]):
        label = OUTCOME_STRATEGIES.get(outcome, {}).get("label", outcome)
        print(f"    {label:25s} {count}")
    print(f"{'='*70}")


def main():
    parser = argparse.ArgumentParser(description="Meeting Follow-Up Automation")
    parser.add_argument("--prospect", help="Prospect name")
    parser.add_argument("--company", help="Company name")
    parser.add_argument("--email", help="Prospect email")
    parser.add_argument("--outcome", choices=list(OUTCOME_STRATEGIES.keys()),
                        help="Meeting outcome")
    parser.add_argument("--notes", default="", help="Dylan's notes from the call")
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH, help="Config file path")
    parser.add_argument("--dry-run", action="store_true", help="Generate but don't send")
    parser.add_argument("--list", action="store_true", help="Show recent meeting outcomes")
    args = parser.parse_args()

    if args.list:
        show_recent_meetings()
        return

    if not args.prospect or not args.email or not args.outcome:
        parser.error("--prospect, --email, and --outcome are required (or use --list)")

    # Load config
    try:
        with open(args.config) as f:
            config = json.load(f)
    except Exception as e:
        logging.error("Could not load config: %s", e)
        sys.exit(1)

    result = process_meeting_followup(
        config=config,
        prospect=args.prospect,
        company=args.company or "",
        email=args.email,
        outcome=args.outcome,
        notes=args.notes,
        dry_run=args.dry_run,
    )

    print(f"\nResult: {json.dumps(result, indent=2)}")


if __name__ == "__main__":
    main()
