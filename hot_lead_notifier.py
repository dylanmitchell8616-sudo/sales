#!/usr/bin/env python3
"""
Hot Lead Notifier — Real-time alerts when high-intent prospects reply.

Fires immediately when reply_autopilot classifies a reply as:
  - direct_intent  (ready to book)
  - meeting_booked (already booked)

Notification channels (all optional, configure in config.json):
  1. Twilio SMS  — texts Dylan's phone instantly
  2. Slack       — posts to #hot-leads webhook
  3. Log         — always logs regardless

Usage:
    from hot_lead_notifier import notify_hot_lead
    notify_hot_lead(config, contact_name, contact_email, company, category, reply_text)
"""

import json
import logging
import os
import time

try:
    import requests
    _requests_available = True
except ImportError:
    _requests_available = False

# ---------------------------------------------------------------------------
# Notification categories that warrant an instant alert
# ---------------------------------------------------------------------------

HOT_CATEGORIES = {"direct_intent", "meeting_booked"}

CATEGORY_LABELS = {
    "direct_intent": "WANTS TO BOOK",
    "meeting_booked": "MEETING BOOKED",
}

EMOJI = {
    "direct_intent": "FIRE",
    "meeting_booked": "CALENDAR",
}


# ---------------------------------------------------------------------------
# Slack notifier
# ---------------------------------------------------------------------------

def _send_slack(webhook_url: str, text: str) -> bool:
    """POST a message to a Slack incoming webhook."""
    if not _requests_available:
        logging.warning("requests not installed — cannot send Slack notification.")
        return False
    try:
        resp = requests.post(
            webhook_url,
            json={"text": text},
            timeout=10,
        )
        if resp.status_code == 200:
            logging.info("Slack notification sent.")
            return True
        else:
            logging.warning("Slack webhook returned %d: %s", resp.status_code, resp.text[:200])
            return False
    except Exception as e:
        logging.warning("Slack notification failed: %s", e)
        return False


# ---------------------------------------------------------------------------
# Twilio SMS notifier
# ---------------------------------------------------------------------------

def _send_twilio_sms(account_sid: str, auth_token: str, from_number: str,
                     to_number: str, body: str) -> bool:
    """Send an SMS via Twilio REST API (no SDK required)."""
    if not _requests_available:
        logging.warning("requests not installed — cannot send Twilio SMS.")
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
    payload = {
        "From": from_number,
        "To": to_number,
        "Body": body,
    }
    try:
        resp = requests.post(
            url,
            data=payload,
            auth=(account_sid, auth_token),
            timeout=15,
        )
        if resp.status_code in (200, 201):
            sid = resp.json().get("sid", "")
            logging.info("Twilio SMS sent (sid=%s) to %s", sid, to_number)
            return True
        else:
            logging.warning("Twilio SMS failed (%d): %s", resp.status_code, resp.text[:300])
            return False
    except Exception as e:
        logging.warning("Twilio SMS error: %s", e)
        return False


# ---------------------------------------------------------------------------
# Core notification dispatcher
# ---------------------------------------------------------------------------

def notify_hot_lead(
    config: dict,
    contact_name: str,
    contact_email: str,
    company_name: str,
    category: str,
    reply_text: str,
    dry_run: bool = False,
) -> dict:
    """
    Fire instant alerts for a hot lead.

    Returns a dict summarizing what was sent:
      {"slack": bool, "sms": bool, "logged": bool}
    """
    if category not in HOT_CATEGORIES:
        return {"slack": False, "sms": False, "logged": False}

    label = CATEGORY_LABELS.get(category, category.upper())
    short_reply = (reply_text[:120] + "...") if len(reply_text) > 120 else reply_text
    calendar = config.get("calendar_link", "https://calendly.com/realsideai")

    # Build notification message
    msg_lines = [
        f"[{label}] {contact_name or contact_email} at {company_name or 'Unknown Co'}",
        f"Email: {contact_email}",
        f'Reply: "{short_reply}"',
        f"Book now: {calendar}",
    ]
    full_msg = "\n".join(msg_lines)

    # Short SMS version (160 chars)
    sms_msg = (
        f"[{label}] {contact_name or contact_email} @ {company_name or ''} replied: "
        f'"{short_reply[:80]}..." Book: {calendar}'
    )

    results = {"slack": False, "sms": False, "logged": True}

    # Always log
    logging.info("HOT LEAD ALERT [%s]: %s <%s> at %s",
                 label, contact_name, contact_email, company_name)
    logging.info("Reply preview: %s", short_reply)

    if dry_run:
        logging.info("[DRY-RUN] Would send notifications for hot lead %s", contact_email)
        return results

    # Slack notification
    slack_webhook = config.get("slack_webhook_url", "")
    if slack_webhook and _requests_available:
        results["slack"] = _send_slack(slack_webhook, full_msg)
    elif slack_webhook:
        logging.warning("Slack webhook configured but requests not available.")

    # Twilio SMS notification
    twilio_sid = config.get("twilio_account_sid", "")
    twilio_token = config.get("twilio_auth_token", "")
    twilio_from = config.get("twilio_from_number", "")
    dylan_phone = config.get("dylan_phone", "")

    if twilio_sid and twilio_token and twilio_from and dylan_phone:
        results["sms"] = _send_twilio_sms(
            account_sid=twilio_sid,
            auth_token=twilio_token,
            from_number=twilio_from,
            to_number=dylan_phone,
            body=sms_msg[:1600],
        )
    elif twilio_sid:
        logging.warning(
            "Twilio configured but missing twilio_auth_token/twilio_from_number/dylan_phone."
        )

    if not results["slack"] and not results["sms"]:
        logging.info(
            "No notification channels configured. Add slack_webhook_url or "
            "twilio_account_sid/twilio_auth_token/twilio_from_number/dylan_phone to config.json"
        )

    return results


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.json"
    try:
        with open(config_path) as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"Could not load config: {e}")
        sys.exit(1)

    # Send a test notification
    result = notify_hot_lead(
        config=cfg,
        contact_name="Pat Bauer",
        contact_email="pat.bauer@heartland.com",
        company_name="Heartland Dental",
        category="direct_intent",
        reply_text="Yes I'd love to see a demo. What times work this week?",
    )
    print(f"Notification result: {result}")
