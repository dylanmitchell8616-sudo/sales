#!/usr/bin/env python3
"""Flask webhook receiver for Instantly real-time notifications.

Receives POST payloads from Instantly webhooks, classifies replies using
AutoResponder, generates and sends auto-responses via the Instantly API,
and logs all events.

Usage:
    python webhooks/receiver.py              # Runs on port 8000
    python webhooks/receiver.py --port 9000  # Custom port

Production deployment note:
    This receiver must be accessible at a public URL for Instantly to deliver
    webhook payloads. Deployment options:

      - ngrok (testing only):
            ngrok http 8000
        Then use the generated https://xxxx.ngrok.io/webhook URL when
        creating webhooks with setup_webhooks.py.

      - VPS ($5/mo on Hetzner, DigitalOcean, Vultr):
        Run behind nginx/caddy with a real domain and TLS.

      - PaaS (Railway, Render, Fly.io):
        Deploy this file as a simple web service. Set the INSTANTLY_API_KEY
        environment variable in the platform's dashboard.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request

# Allow imports from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))
from instantly.client import InstantlyClient
from replies.responder import AutoResponder

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

LOG_FILE = LOG_DIR / "webhook_events.log"

# Set up logging: file + console.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("webhook_receiver")

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

app = Flask(__name__)

# Load env and initialise singletons at import time so they're ready when the
# first request arrives.
load_dotenv(Path(__file__).parent.parent / ".env")

_api_key = os.getenv("INSTANTLY_API_KEY", "")
if not _api_key:
    logger.warning("INSTANTLY_API_KEY not set. Auto-responses will fail.")

client = InstantlyClient(_api_key) if _api_key else None
responder = AutoResponder()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def extract_reply_data(payload: dict) -> dict:
    """Normalise an Instantly webhook payload into a consistent structure.

    Instantly's webhook schema may nest data under various keys. This
    function pulls out the fields we care about regardless of nesting.
    """
    # The payload might wrap the real data under "data", "event_data", etc.
    data = payload.get("data", payload.get("event_data", payload))

    return {
        "event_type": payload.get("event_type", payload.get("event", "unknown")),
        "email": data.get("email", data.get("lead_email", data.get("from_email", ""))),
        "reply_text": data.get("reply_text", data.get("body", data.get("text", ""))),
        "subject": data.get("subject", ""),
        "campaign_id": data.get("campaign_id", ""),
        "lead_email": data.get("lead_email", data.get("email", data.get("from_email", ""))),
        "from_email": data.get("from_email", data.get("reply_from", "")),
        "to_email": data.get("to_email", data.get("account_email", "")),
        "first_name": data.get("first_name", data.get("firstName", "")),
        "last_name": data.get("last_name", data.get("lastName", "")),
        "company_name": data.get("company_name", data.get("companyName", "")),
        "timestamp": data.get("timestamp", datetime.now(timezone.utc).isoformat()),
        "raw": payload,
    }


def send_auto_reply(reply_data: dict) -> bool:
    """Classify the reply, generate a response, and send it via Instantly.

    Returns True if a reply was sent, False otherwise.
    """
    if client is None:
        logger.error("Cannot send reply: InstantlyClient not initialised.")
        return False

    reply_text = reply_data.get("reply_text", "")
    if not reply_text:
        logger.info("No reply text in payload; skipping auto-response.")
        return False

    # Check whether we should respond at all.
    if not responder.should_respond(reply_text):
        category = responder.classify_reply(reply_text)
        logger.info(
            "Skipping auto-response for %s (category=%s, needs human review or OOO).",
            reply_data["lead_email"],
            category,
        )
        return False

    # Build lead_data dict expected by AutoResponder.
    lead_data = {
        "firstName": reply_data.get("first_name") or reply_data.get("lead_email", "").split("@")[0],
        "companyName": reply_data.get("company_name", "your company"),
        "email": reply_data.get("lead_email", ""),
    }

    category = responder.classify_reply(reply_text)
    response_text = responder.generate_response(reply_text, lead_data)

    if response_text is None:
        logger.info("No response template for category '%s'; skipping.", category)
        return False

    response_html = AutoResponder.format_reply_html(response_text)

    logger.info(
        "Sending auto-reply to %s (category=%s)",
        reply_data["lead_email"],
        category,
    )

    # Send via Instantly's reply/send endpoint.
    try:
        send_payload = {
            "reply_to_uuid": reply_data.get("raw", {}).get("data", {}).get("uuid", ""),
            "from": reply_data.get("to_email", ""),
            "to": reply_data["lead_email"],
            "subject": f"Re: {reply_data.get('subject', '')}",
            "body": response_html,
        }

        # Try the v2 emails/reply endpoint first; fall back to unibox/reply.
        try:
            result = client.post("emails/reply", json=send_payload)
        except Exception:
            result = client.post("unibox/emails/reply", json=send_payload)

        logger.info("Reply sent successfully: %s", json.dumps(result)[:200])
        return True

    except Exception as e:
        logger.error("Failed to send auto-reply to %s: %s", reply_data["lead_email"], e)
        return False


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint for monitoring and load balancers."""
    return jsonify({
        "status": "ok",
        "service": "instantly-webhook-receiver",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/webhook", methods=["POST"])
def handle_webhook():
    """Receive and process Instantly webhook events.

    Instantly sends a POST with a JSON body. We log it, classify the reply,
    and auto-respond if appropriate.
    """
    # Accept both JSON and form-encoded payloads.
    if request.is_json:
        payload = request.get_json(silent=True) or {}
    else:
        payload = request.form.to_dict()

    event_type = payload.get("event_type", payload.get("event", "unknown"))
    logger.info("Received webhook event: %s", event_type)
    logger.debug("Full payload: %s", json.dumps(payload, indent=2))

    # Log raw payload to file for debugging.
    _log_raw_event(event_type, payload)

    # Route by event type.
    if event_type in ("reply_received", "reply"):
        reply_data = extract_reply_data(payload)
        logger.info(
            "Reply from %s (campaign %s): %s",
            reply_data["lead_email"],
            reply_data["campaign_id"],
            reply_data["reply_text"][:120],
        )
        send_auto_reply(reply_data)

    elif event_type in ("email_opened", "open"):
        data = payload.get("data", payload)
        logger.info(
            "Email opened by %s (campaign %s)",
            data.get("email", data.get("lead_email", "unknown")),
            data.get("campaign_id", "unknown"),
        )

    else:
        logger.info("Unhandled event type '%s'; logged for review.", event_type)

    # Always return 200 so Instantly doesn't retry.
    return Response(status=200)


def _log_raw_event(event_type: str, payload: dict) -> None:
    """Append the raw event to a JSONL log file for auditing."""
    log_entry = {
        "received_at": datetime.now(timezone.utc).isoformat(),
        "event_type": event_type,
        "payload": payload,
    }
    log_path = LOG_DIR / "webhook_events.jsonl"
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError as e:
        logger.warning("Could not write to event log: %s", e)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Instantly webhook receiver.")
    parser.add_argument(
        "--port", type=int, default=8000,
        help="Port to listen on (default: 8000).",
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="Host to bind to (default: 0.0.0.0).",
    )
    parser.add_argument(
        "--debug", action="store_true",
        help="Enable Flask debug mode (development only).",
    )
    args = parser.parse_args()

    logger.info("Starting webhook receiver on %s:%d", args.host, args.port)
    logger.info("Webhook endpoint: POST /webhook")
    logger.info("Health check:     GET  /health")
    logger.info("Logging events to %s", LOG_FILE)

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
