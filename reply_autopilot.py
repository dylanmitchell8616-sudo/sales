#!/usr/bin/env python3
"""
Reply Autopilot — Fully Automated Instantly Reply Manager

Monitors Instantly campaigns for new replies, classifies them with Claude AI,
generates and sends responses, and tags leads — all automatically.

Usage:
    python reply_autopilot.py                        # Run with config.json defaults
    python reply_autopilot.py --interval 120         # Poll every 2 minutes
    python reply_autopilot.py --dry-run              # Classify and generate but don't send
    python reply_autopilot.py --once                 # Run once then exit (no loop)
    python reply_autopilot.py --config config.json   # Custom config path
"""

import argparse
import csv
import json
import logging
import os
import random
import re
import signal
import sys
import time
from datetime import datetime, timezone

try:
    from hot_lead_notifier import notify_hot_lead, HOT_CATEGORIES
except ImportError:
    HOT_CATEGORIES = {"direct_intent", "meeting_booked"}
    def notify_hot_lead(*args, **kwargs):
        return {"slack": False, "sms": False, "logged": False}

try:
    from hot_lead_scorer import score_hot_lead, format_score_message
except ImportError:
    def score_hot_lead(*args, **kwargs):
        return {"score": 0, "factors": [], "priority": "unknown"}
    def format_score_message(*args, **kwargs):
        return ""

try:
    from meeting_prep import generate_and_send_prep, PREP_CATEGORIES
except ImportError:
    PREP_CATEGORIES = {"direct_intent", "meeting_booked"}
    def generate_and_send_prep(*args, **kwargs):
        return {"brief_generated": False, "email_sent": False, "file_saved": False, "filepath": ""}

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Error: anthropic package required. Install with: pip install anthropic")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_URL = "https://api.instantly.ai/api/v2"
DEFAULT_CONFIG_PATH = "config.json"
DEFAULT_POLL_INTERVAL = 60  # seconds
PROCESSED_REPLIES_PATH = "output/processed_replies.json"
LOG_PATH = "output/reply_autopilot.log"

REPLY_CATEGORIES = [
    "direct_intent",
    "how_does_it_work",
    "how_much",
    "send_proof",
    "not_interested",
    "tried_before",
    "already_have",
    "timing",
    "positive_other",
    "negative_other",
    "meeting_booked",
]

# Categories that should receive an auto-reply
AUTO_REPLY_CATEGORIES = {
    "direct_intent",
    "how_does_it_work",
    "how_much",
    "send_proof",
    "tried_before",
    "already_have",
    "timing",
    "positive_other",
    "meeting_booked",
}

# Categories that indicate a prospect is interested (auto-add to engaged tracker)
INTERESTED_CATEGORIES = {
    "direct_intent",
    "how_does_it_work",
    "how_much",
    "send_proof",
    "tried_before",
    "already_have",
    "timing",
    "positive_other",
    "meeting_booked",
}

# Tag mapping
TAG_MAP = {
    "direct_intent": "Interested",
    "how_does_it_work": "Interested",
    "how_much": "Interested",
    "send_proof": "Interested",
    "tried_before": "Interested",
    "already_have": "Interested",
    "timing": "Interested",
    "positive_other": "Interested",
    "not_interested": "Not Interested",
    "negative_other": "Not Interested",
    "meeting_booked": "Meeting Booked",
}

ENGAGED_TRACKER_PATH = "output/engaged_prospects.csv"

# ---------------------------------------------------------------------------
# Graceful shutdown
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logging.info("Received signal %s — shutting down after current cycle.", signum)
    _shutdown = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------


def setup_logging(log_path: str):
    """Configure logging to both console and file."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.DEBUG)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


# ---------------------------------------------------------------------------
# Instantly API helpers (mirrors instantly_uploader.py patterns)
# ---------------------------------------------------------------------------


def api_request(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    """Make an authenticated request to the Instantly V2 API with retry logic."""
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    for attempt in range(4):
        try:
            if method.upper() == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            elif method.upper() == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "PATCH":
                resp = requests.patch(url, headers=headers, json=data, timeout=30)
            elif method.upper() == "DELETE":
                resp = requests.delete(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                logging.warning("Rate limited, waiting %ds...", wait)
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                logging.debug("API error %d: %s", resp.status_code, resp.text[:500])
                return {"error": resp.text, "status_code": resp.status_code}

            return resp.json() if resp.text else {}

        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                logging.warning("Network error, retrying in %ds: %s", wait, e)
                time.sleep(wait)
            else:
                logging.error("Failed after 4 attempts: %s", e)
                return {"error": str(e)}

    return {"error": "Max retries exceeded"}


# ---------------------------------------------------------------------------
# Config & state helpers
# ---------------------------------------------------------------------------


def load_config(path: str) -> dict:
    """Load configuration from JSON file."""
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        logging.error("Config file not found: %s", path)
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error("Invalid JSON in config file: %s", e)
        sys.exit(1)


def load_case_studies(case_studies_path: str) -> str:
    """Load all case study .md files from a directory into a single string."""
    if not os.path.isdir(case_studies_path):
        logging.warning("Case studies directory not found: %s", case_studies_path)
        return ""

    studies = []
    for filename in sorted(os.listdir(case_studies_path)):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(case_studies_path, filename)
        if os.path.isfile(filepath):
            try:
                with open(filepath, encoding="utf-8") as f:
                    content = f.read().strip()
                if content:
                    studies.append(f"--- {filename} ---\n{content}")
            except Exception as e:
                logging.warning("Could not read %s: %s", filepath, e)

    result = "\n\n".join(studies)
    if result:
        logging.info("Loaded %d case studies from %s", len(studies), case_studies_path)
    else:
        logging.warning("No case studies loaded. Responses will lack social proof.")
    return result


def load_processed_replies(path: str) -> dict:
    """Load the processed replies tracker JSON, creating it if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            logging.warning("Corrupted processed replies file, starting fresh.")
            return {}
    return {}


def save_processed_reply(path: str, reply_id: str, data: dict):
    """Mark a reply as processed and persist to disk."""
    processed = load_processed_replies(path)
    processed[reply_id] = data
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(processed, f, indent=2, default=str)


def append_engaged_prospect(
    script_dir: str,
    contact_email: str,
    contact_name: str,
    company_name: str,
    category: str,
    campaign_id: str = "",
    campaign_name: str = "",
    dry_run: bool = False,
):
    """Auto-append an interested prospect to the engaged_prospects.csv tracker."""
    if not contact_email:
        return

    tracker_path = os.path.join(script_dir, ENGAGED_TRACKER_PATH)
    os.makedirs(os.path.dirname(tracker_path), exist_ok=True)

    # Read existing entries to avoid duplicates
    existing_emails = set()
    fieldnames = [
        "contact_email", "contact_name", "company_name", "status",
        "added_at", "reply_category", "source_campaign_id", "source_campaign_name",
    ]
    if os.path.exists(tracker_path):
        try:
            with open(tracker_path, newline="", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    existing_emails.add(row.get("contact_email", "").lower())
        except Exception:
            pass

    if contact_email.lower() in existing_emails:
        logging.debug("Prospect %s already in engaged tracker.", contact_email)
        return

    status = "booked" if category == "meeting_booked" else "interested"
    row = {
        "contact_email": contact_email,
        "contact_name": contact_name or "",
        "company_name": company_name or "",
        "status": status,
        "added_at": datetime.now(timezone.utc).isoformat(),
        "reply_category": category,
        "source_campaign_id": campaign_id,
        "source_campaign_name": campaign_name,
    }

    if dry_run:
        logging.info("[DRY-RUN] Would add %s (%s) to engaged tracker as '%s' (campaign: %s)",
                     contact_email, company_name, status, campaign_name or campaign_id)
        return

    file_exists = os.path.exists(tracker_path)
    try:
        with open(tracker_path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            if not file_exists:
                writer.writeheader()
            writer.writerow(row)
        logging.info("Added %s to engaged tracker (status=%s, category=%s, campaign=%s)",
                     contact_email, status, category, campaign_name or campaign_id)
    except Exception as e:
        logging.warning("Failed to update engaged tracker: %s", e)


# ---------------------------------------------------------------------------
# Instantly API operations
# ---------------------------------------------------------------------------


def fetch_campaigns(api_key: str) -> list:
    """Get all campaigns from Instantly."""
    campaigns = []
    # Paginate through results
    params = {"limit": 100}
    result = api_request("GET", "/campaigns", api_key, params)
    if "error" in result:
        logging.error("Failed to fetch campaigns: %s", result.get("error", "")[:200])
        return []

    # Handle different response shapes
    if isinstance(result, list):
        campaigns = result
    elif isinstance(result, dict):
        campaigns = result.get("data", result.get("items", []))
        if isinstance(campaigns, dict):
            campaigns = campaigns.get("items", [])

    logging.info("Fetched %d campaigns.", len(campaigns))
    return campaigns


def fetch_replies(api_key: str, campaign_id: str) -> list:
    """Fetch reply emails from Instantly unibox for a given campaign.

    Tries multiple API endpoint patterns since the Instantly V2 API
    may vary. Falls back gracefully.
    """
    replies = []

    # Strategy 1: unibox/emails endpoint
    params = {
        "campaign_id": campaign_id,
        "limit": 50,
        "email_type": "reply",
    }
    result = api_request("GET", "/unibox/emails", api_key, params)
    if "error" not in result:
        items = _extract_items(result)
        if items:
            logging.debug("Fetched %d replies via /unibox/emails for campaign %s",
                          len(items), campaign_id)
            return items

    # Strategy 2: campaign replies endpoint
    result = api_request("GET", f"/campaigns/{campaign_id}/replies", api_key, {"limit": 50})
    if "error" not in result:
        items = _extract_items(result)
        if items:
            logging.debug("Fetched %d replies via /campaigns/.../replies for campaign %s",
                          len(items), campaign_id)
            return items

    # Strategy 3: leads with replied status
    result = api_request("GET", "/leads", api_key, {
        "campaign_id": campaign_id,
        "limit": 50,
        "status": "replied",
    })
    if "error" not in result:
        items = _extract_items(result)
        if items:
            logging.debug("Fetched %d replied leads via /leads for campaign %s",
                          len(items), campaign_id)
            return items

    # Strategy 4: unibox/emails without campaign filter
    result = api_request("GET", "/unibox/emails", api_key, {
        "limit": 50,
        "email_type": "reply",
    })
    if "error" not in result:
        items = _extract_items(result)
        if items:
            # Filter to our campaign if possible
            filtered = [i for i in items if i.get("campaign_id") == campaign_id]
            if filtered:
                logging.debug("Fetched %d replies via unfiltered /unibox/emails for campaign %s",
                              len(filtered), campaign_id)
                return filtered
            # Return all if can't filter — caller will deduplicate via processed set
            return items

    logging.debug("No replies found for campaign %s", campaign_id)
    return replies


def _extract_items(result) -> list:
    """Extract list items from various API response shapes."""
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        for key in ("data", "items", "emails", "replies", "leads"):
            val = result.get(key)
            if isinstance(val, list):
                return val
        # If dict has typical email fields, wrap it
        if result.get("id") or result.get("email"):
            return [result]
    return []


def send_reply(api_key: str, reply_to_uuid: str, from_email: str,
               to_email: str, subject: str, body: str, campaign_id: str = None) -> dict:
    """Send a reply back through Instantly.

    Tries multiple endpoint patterns.
    """

    # Strategy 1: unibox reply
    payload = {
        "reply_to_uuid": reply_to_uuid,
        "from": from_email,
        "to": to_email,
        "subject": subject,
        "body": {"html": body.replace("\n", "<br>"), "text": body},
    }
    if campaign_id:
        payload["campaign_id"] = campaign_id

    result = api_request("POST", "/unibox/emails/reply", api_key, payload)
    if "error" not in result:
        logging.info("Sent reply via /unibox/emails/reply to %s", to_email)
        return result

    # Strategy 2: unibox send
    result = api_request("POST", "/unibox/emails/send", api_key, payload)
    if "error" not in result:
        logging.info("Sent reply via /unibox/emails/send to %s", to_email)
        return result

    # Strategy 3: emails reply endpoint
    payload2 = {
        "email_id": reply_to_uuid,
        "from_email": from_email,
        "to_email": to_email,
        "subject": subject,
        "body": body,
        "campaign_id": campaign_id or "",
    }
    result = api_request("POST", "/emails/reply", api_key, payload2)
    if "error" not in result:
        logging.info("Sent reply via /emails/reply to %s", to_email)
        return result

    logging.error("Failed to send reply to %s (tried all endpoints): %s",
                  to_email, result.get("error", "")[:200])
    return result


def tag_lead(api_key: str, lead_email: str, campaign_id: str, tag: str) -> dict:
    """Tag a lead in Instantly. Tries multiple endpoint patterns."""

    # Strategy 1: lead tag endpoint
    payload = {
        "email": lead_email,
        "campaign_id": campaign_id,
        "tag": tag,
    }
    result = api_request("POST", "/leads/tag", api_key, payload)
    if "error" not in result:
        logging.info("Tagged %s as '%s' via /leads/tag", lead_email, tag)
        return result

    # Strategy 2: leads update with tags
    payload2 = {
        "email": lead_email,
        "campaign_id": campaign_id,
        "tags": [tag],
    }
    result = api_request("PATCH", "/leads", api_key, payload2)
    if "error" not in result:
        logging.info("Tagged %s as '%s' via PATCH /leads", lead_email, tag)
        return result

    # Strategy 3: lead labels
    result = api_request("POST", "/leads/labels", api_key, payload)
    if "error" not in result:
        logging.info("Tagged %s as '%s' via /leads/labels", lead_email, tag)
        return result

    logging.warning("Could not tag %s as '%s' (tried all endpoints): %s",
                    lead_email, tag, result.get("error", "")[:200])
    return result


# ---------------------------------------------------------------------------
# Claude AI classification & response generation
# ---------------------------------------------------------------------------


def _parse_json_response(text: str) -> dict:
    """Extract JSON object from Claude's response, handling markdown blocks."""
    text = text.strip()
    # Try markdown code block first
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            text = m.group(0)
    return json.loads(text)


def classify_reply(client: anthropic.Anthropic, reply_text: str) -> dict:
    """Use Claude to classify a prospect reply into a category.

    Returns dict with keys: category, sentiment, should_reply
    """
    categories_str = "\n".join(f"- {c}" for c in REPLY_CATEGORIES)

    prompt = f"""Classify this prospect reply into one of these categories:
{categories_str}

Category definitions:
- direct_intent: wants to book a call or learn more, clearly interested
- how_does_it_work: asking about the process or product mechanics
- how_much: asking about pricing or cost
- send_proof: wants case studies, results, proof it works
- not_interested: polite decline, unsubscribe, not a fit
- tried_before: tried AI or similar solution before and it didn't work
- already_have: already has a solution in place
- timing: not the right time, ask to reach out later
- positive_other: positive/curious reply that doesn't fit above categories
- negative_other: hostile, rude, or strongly negative reply

Reply: "{reply_text}"

Return ONLY a JSON object with these keys:
- "category": one of the categories above
- "sentiment": "positive", "neutral", or "negative"
- "should_reply": true or false (false for hostile/rude replies or explicit unsubscribes)"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=256,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _parse_json_response(response.content[0].text)

        # Validate category
        if result.get("category") not in REPLY_CATEGORIES:
            result["category"] = "positive_other" if result.get("sentiment") == "positive" else "negative_other"
        if "should_reply" not in result:
            result["should_reply"] = result["category"] in AUTO_REPLY_CATEGORIES
        if "sentiment" not in result:
            result["sentiment"] = "neutral"

        return result

    except Exception as e:
        logging.error("Classification failed: %s", e)
        return {"category": "positive_other", "sentiment": "neutral", "should_reply": False}


# ---------------------------------------------------------------------------
# A/B Testing Variants for response generation
# ---------------------------------------------------------------------------

RESPONSE_VARIANTS = {
    "A": {
        "name": "imperium_empathy",
        "description": "Empathize first, reframe with logic/social proof, low-friction CTA",
        "style_instructions": """Style: Empathize first, reframe with logic or social proof, end with low-friction CTA.
- Friendly, confident, value-driven tone
- Short, punchy sentences
- Spark curiosity, don't fully answer questions over email""",
    },
    "B": {
        "name": "direct_value",
        "description": "Lead with a specific result/number, social proof first, curiosity-driven CTA",
        "style_instructions": """Style: Lead with a specific, impressive result or number right away. Social proof first.
- Open with a stat or case study result (e.g. "We just helped a 3-location med spa recover $14K/mo in missed calls")
- Confident, direct tone. No fluff
- End with a curiosity-driven question, not a calendar link push (e.g. "Curious what that would look like for {company}?")""",
    },
    "C": {
        "name": "question_led",
        "description": "Open with a provocative question, challenge assumptions, soft close",
        "style_instructions": """Style: Open with a thought-provoking question that challenges their assumptions.
- Start with "What if..." or "Have you ever wondered..." or a surprising question
- Keep it conversational and curious, like a peer not a salesperson
- End with a soft offer, not a hard CTA (e.g. "Happy to share how if you're curious")""",
    },
}

# Variant weights: can be adjusted as winners emerge
# Format: {"A": weight, "B": weight, "C": weight} — higher = more likely
VARIANT_WEIGHTS_PATH = "output/variant_weights.json"


def _load_variant_weights() -> dict:
    """Load A/B test variant weights. Defaults to equal weights."""
    try:
        if os.path.exists(VARIANT_WEIGHTS_PATH):
            with open(VARIANT_WEIGHTS_PATH, encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"A": 40, "B": 40, "C": 20}


def _pick_variant() -> str:
    """Pick a response variant based on weights."""
    weights = _load_variant_weights()
    variants = list(weights.keys())
    weight_values = [weights.get(v, 1) for v in variants]
    return random.choices(variants, weights=weight_values, k=1)[0]


def generate_response(
    client: anthropic.Anthropic,
    category: str,
    original_email: str,
    reply_text: str,
    contact_name: str,
    company_name: str,
    case_studies: str,
    calendar_link: str,
    sender_name: str,
) -> dict:
    """Use Claude to generate a response email based on the Imperium framework.

    Picks a random A/B/C variant for testing different response styles.
    Returns dict with keys: subject, body, variant
    """
    first_name = sender_name.split()[0] if sender_name else "Dylan"
    variant = _pick_variant()
    variant_config = RESPONSE_VARIANTS.get(variant, RESPONSE_VARIANTS["A"])

    logging.info("Using response variant %s (%s) for %s",
                 variant, variant_config["name"], contact_name or company_name)

    prompt = f"""Act as an expert SDR for Realside AI. Realside AI builds AI Employees for service businesses (med spas, dental, wellness). Products: AI Inbound Receptionist (answers calls 24/7, books appointments) and AI Outbound Agent (calls/texts leads within 2 mins, reactivates dormant CRM leads).

The prospect replied to our cold email with this objection type: {category}

Original email we sent: {original_email}
Their reply: {reply_text}
Their name: {contact_name}
Their company: {company_name}

CASE STUDIES FOR SOCIAL PROOF:
{case_studies}

{variant_config["style_instructions"]}

Rules:
- Under 120 words
- Never use '--' or em dashes or en dashes of any kind
- Always include calendar link: {calendar_link}
- For pricing: deflect to call first, if they push anchor at $2K/mo tied to 40 pre-qualified appointments
- For "how does it work": redirect to demo call
- For "send proof": offer to walk through case studies on a call
- Sign off with sender first name only: {first_name}

Return ONLY a JSON object with these keys:
- "subject": email subject line (short, relevant, contextual — no "Re:" prefix)
- "body": full email body (plain text, use \\n for newlines)"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user", "content": prompt}],
        )
        result = _parse_json_response(response.content[0].text)

        if "subject" not in result or "body" not in result:
            raise ValueError("Missing subject or body in response")

        result["variant"] = variant
        return result

    except Exception as e:
        logging.error("Response generation failed: %s", e)
        # Fallback response
        return {
            "subject": f"Quick follow-up, {contact_name}",
            "body": (
                f"Hi {contact_name},\n\n"
                f"Thanks for getting back to me. I'd love to show you how we're helping "
                f"businesses like {company_name} capture more revenue with AI.\n\n"
                f"Here's my calendar if you have 15 minutes: {calendar_link}\n\n"
                f"Best,\n{first_name}"
            ),
            "variant": variant,
        }


# ---------------------------------------------------------------------------
# Core processing
# ---------------------------------------------------------------------------


def _get_reply_id(reply: dict) -> str:
    """Extract a stable unique ID from a reply object."""
    return (
        reply.get("id")
        or reply.get("uuid")
        or reply.get("email_id")
        or reply.get("message_id")
        # Fallback: hash of sender + timestamp
        or f"{reply.get('from_email', reply.get('email', 'unknown'))}_"
           f"{reply.get('timestamp', reply.get('created_at', reply.get('date', '')))}"
    )


def _get_reply_text(reply: dict) -> str:
    """Extract the reply body text from a reply object."""
    # Try various field names
    for key in ("body_text", "text_body", "body", "text", "content", "message", "snippet"):
        val = reply.get(key)
        if val and isinstance(val, str) and len(val.strip()) > 0:
            return val.strip()
    # If body is a dict (html/text)
    body = reply.get("body")
    if isinstance(body, dict):
        return (body.get("text") or body.get("html") or "").strip()
    return ""


def _get_contact_info(reply: dict) -> tuple:
    """Extract contact name, email, and company from a reply object."""
    email = (
        reply.get("from_email")
        or reply.get("from")
        or reply.get("email")
        or reply.get("lead_email")
        or ""
    )
    name = (
        reply.get("from_name")
        or reply.get("lead_name")
        or reply.get("first_name", "")
        or ""
    )
    if not name and reply.get("first_name"):
        name = reply["first_name"]
        if reply.get("last_name"):
            name += " " + reply["last_name"]

    company = reply.get("company_name") or reply.get("company") or ""

    return name.strip(), email.strip(), company.strip()


def _get_original_email(reply: dict) -> str:
    """Extract the original email that was sent, if available."""
    for key in ("original_body", "original_message", "in_reply_to_body",
                "parent_body", "thread_body"):
        val = reply.get(key)
        if val and isinstance(val, str):
            return val.strip()
    return "(original email not available)"


def process_reply(
    reply: dict,
    campaign_id: str,
    config: dict,
    claude_client: anthropic.Anthropic,
    case_studies: str,
    dry_run: bool = False,
    campaign_name: str = "",
) -> dict:
    """Process a single reply: classify, generate response, send, tag.

    Returns a state dict to store in processed_replies.json.
    """
    reply_id = _get_reply_id(reply)
    reply_text = _get_reply_text(reply)
    contact_name, contact_email, company_name = _get_contact_info(reply)
    original_email = _get_original_email(reply)
    now = datetime.now(timezone.utc).isoformat()

    logging.info(
        "Processing reply %s from %s <%s> at %s",
        reply_id, contact_name or "(unknown)", contact_email, company_name or "(unknown)",
    )

    if not reply_text:
        logging.warning("Empty reply body for %s, skipping.", reply_id)
        return {
            "processed_at": now,
            "category": "unknown",
            "action": "skipped_empty",
            "response_sent": False,
            "contact_email": contact_email,
        }

    # Step 1: Classify the reply
    classification = classify_reply(claude_client, reply_text)
    category = classification["category"]
    sentiment = classification["sentiment"]
    should_reply = classification["should_reply"]

    logging.info(
        "Classified reply from %s: category=%s, sentiment=%s, should_reply=%s",
        contact_email, category, sentiment, should_reply,
    )

    # Step 2: Determine tag
    tag = TAG_MAP.get(category, "Interested")

    # Step 3: Tag the lead in Instantly
    if not dry_run:
        tag_lead(config["instantly_api_key"], contact_email, campaign_id, tag)
    else:
        logging.info("[DRY-RUN] Would tag %s as '%s'", contact_email, tag)

    # Step 3b: Score hot lead and fire notification (SMS + Slack) for high-intent replies
    lead_score = {}
    if category in HOT_CATEGORIES or category in ("how_much", "send_proof"):
        lead_score = score_hot_lead(
            contact_email=contact_email,
            contact_name=contact_name,
            company_name=company_name,
            category=category,
            reply_text=reply_text,
            config=config,
        )
        score_msg = format_score_message(lead_score, contact_name, company_name)
        if score_msg:
            logging.info("Lead score: %s", score_msg)

    if category in HOT_CATEGORIES:
        notify_hot_lead(
            config=config,
            contact_name=contact_name,
            contact_email=contact_email,
            company_name=company_name,
            category=category,
            reply_text=reply_text,
            dry_run=dry_run,
        )

    # Step 3b2: Generate and send meeting prep brief for hot leads
    if category in PREP_CATEGORIES:
        domain = ""
        if contact_email and "@" in contact_email:
            domain = contact_email.split("@")[1]
        try:
            prep_result = generate_and_send_prep(
                config=config,
                contact_name=contact_name,
                contact_email=contact_email,
                company_name=company_name,
                domain=domain,
                category=category,
                reply_text=reply_text,
                dry_run=dry_run,
            )
            if prep_result.get("brief_generated"):
                logging.info("Meeting prep brief generated for %s (email_sent=%s, file=%s)",
                             contact_email, prep_result.get("email_sent"), prep_result.get("filepath"))
        except Exception as e:
            logging.warning("Meeting prep generation failed for %s: %s", contact_email, e)

    # Step 3c: Auto-add interested leads to engaged_prospects.csv tracker
    if category in INTERESTED_CATEGORIES:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        append_engaged_prospect(
            script_dir=script_dir,
            contact_email=contact_email,
            contact_name=contact_name,
            company_name=company_name,
            category=category,
            campaign_id=campaign_id,
            campaign_name=campaign_name,
            dry_run=dry_run,
        )

    # Step 4: Decide on action
    action = "no_action"
    response_sent = False
    response_data = {}

    if category == "negative_other" and sentiment == "negative":
        # Hostile / rude — do nothing
        action = "skipped_hostile"
        logging.info("Hostile reply from %s — skipping entirely.", contact_email)

    elif category == "not_interested":
        # Polite decline — skip auto-reply (handle manually with Loom)
        action = "skipped_not_interested_manual_loom"
        logging.info("Not interested reply from %s — skipping (manual Loom).", contact_email)

    elif should_reply and category in AUTO_REPLY_CATEGORIES:
        # Generate and send auto-reply
        action = "auto_reply"
        response_data = generate_response(
            client=claude_client,
            category=category,
            original_email=original_email,
            reply_text=reply_text,
            contact_name=contact_name or "there",
            company_name=company_name or "your business",
            case_studies=case_studies,
            calendar_link=config.get("calendar_link", "https://calendly.com/realsideai"),
            sender_name=config.get("sender_name", "Dylan Mitchell"),
        )

        subject = response_data.get("subject", "")
        body = response_data.get("body", "")

        logging.info(
            "Generated response for %s: subject='%s' (%d chars)",
            contact_email, subject[:60], len(body),
        )

        if not dry_run:
            send_result = send_reply(
                api_key=config["instantly_api_key"],
                reply_to_uuid=reply_id,
                from_email=config.get("sender_email", "dylan.realside@gmail.com"),
                to_email=contact_email,
                subject=subject,
                body=body,
                campaign_id=campaign_id,
            )
            response_sent = "error" not in send_result
            if response_sent:
                logging.info("Reply sent to %s successfully.", contact_email)
            else:
                logging.error("Failed to send reply to %s.", contact_email)
                action = "auto_reply_failed"
        else:
            logging.info("[DRY-RUN] Would send reply to %s: %s", contact_email, subject)
            response_sent = False

    else:
        action = f"skipped_{category}"
        logging.info("No auto-reply for category '%s' from %s.", category, contact_email)

    return {
        "processed_at": now,
        "category": category,
        "sentiment": sentiment,
        "action": action,
        "response_sent": response_sent,
        "contact_email": contact_email,
        "contact_name": contact_name,
        "company_name": company_name,
        "tag_applied": tag,
        "reply_preview": reply_text[:200],
        "response_subject": response_data.get("subject", ""),
        "response_variant": response_data.get("variant", "A"),
        "source_campaign_id": campaign_id,
        "source_campaign_name": campaign_name,
        "lead_score": lead_score.get("score", 0),
        "lead_priority": lead_score.get("priority", ""),
        "dry_run": dry_run,
    }


def run_once(config: dict, dry_run: bool = False) -> dict:
    """Single pass: fetch all campaign replies, classify, respond, tag.

    Returns summary stats.
    """
    api_key = config["instantly_api_key"]
    anthropic_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        logging.error("No Anthropic API key found in config or ANTHROPIC_API_KEY env var.")
        return {"error": "missing_anthropic_key"}

    claude_client = anthropic.Anthropic(api_key=anthropic_key)

    # Resolve case studies path relative to config location
    script_dir = os.path.dirname(os.path.abspath(__file__))
    case_studies_path = config.get("case_studies_path", "case_studies")
    if not os.path.isabs(case_studies_path):
        case_studies_path = os.path.join(script_dir, case_studies_path)
    case_studies = load_case_studies(case_studies_path)

    # Resolve processed replies path
    processed_path = os.path.join(script_dir, PROCESSED_REPLIES_PATH)
    processed = load_processed_replies(processed_path)

    # Stats
    stats = {
        "campaigns_checked": 0,
        "replies_found": 0,
        "replies_new": 0,
        "replies_classified": 0,
        "replies_sent": 0,
        "replies_skipped": 0,
        "errors": 0,
    }

    # Fetch all campaigns
    campaigns = fetch_campaigns(api_key)
    if not campaigns:
        logging.info("No campaigns found.")
        return stats

    stats["campaigns_checked"] = len(campaigns)

    for campaign in campaigns:
        campaign_id = campaign.get("id", "")
        campaign_name = campaign.get("name", "Unnamed")

        if not campaign_id:
            continue

        logging.debug("Checking campaign: %s (%s)", campaign_name, campaign_id)

        # Fetch replies for this campaign
        replies = fetch_replies(api_key, campaign_id)
        stats["replies_found"] += len(replies)

        for reply in replies:
            if _shutdown:
                logging.info("Shutdown requested, stopping processing.")
                return stats

            reply_id = _get_reply_id(reply)

            # Skip already-processed replies
            if reply_id in processed:
                continue

            stats["replies_new"] += 1

            try:
                result = process_reply(
                    reply=reply,
                    campaign_id=campaign_id,
                    config=config,
                    claude_client=claude_client,
                    case_studies=case_studies,
                    dry_run=dry_run,
                    campaign_name=campaign_name,
                )

                stats["replies_classified"] += 1
                if result.get("response_sent"):
                    stats["replies_sent"] += 1
                elif result.get("action", "").startswith("skipped"):
                    stats["replies_skipped"] += 1

                # Persist processed state
                save_processed_reply(processed_path, reply_id, result)
                processed[reply_id] = result  # update local cache too

            except Exception as e:
                logging.error("Error processing reply %s: %s", reply_id, e, exc_info=True)
                stats["errors"] += 1
                # Mark as processed with error to avoid infinite retries
                save_processed_reply(processed_path, reply_id, {
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "category": "error",
                    "action": "error",
                    "response_sent": False,
                    "error": str(e),
                })
                processed[reply_id] = True

    return stats


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Reply Autopilot — Automated Instantly Reply Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG_PATH,
                        help=f"Path to config JSON (default: {DEFAULT_CONFIG_PATH})")
    parser.add_argument("--interval", type=int, default=DEFAULT_POLL_INTERVAL,
                        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Classify and generate responses but don't send or tag")
    parser.add_argument("--once", action="store_true",
                        help="Run one pass then exit (no loop)")

    args = parser.parse_args()

    # Resolve paths relative to script directory
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = args.config
    if not os.path.isabs(config_path):
        config_path = os.path.join(script_dir, config_path)
    log_path = os.path.join(script_dir, LOG_PATH)

    # Setup logging
    setup_logging(log_path)

    logging.info("=" * 60)
    logging.info("Reply Autopilot starting")
    logging.info("=" * 60)
    logging.info("Config:   %s", config_path)
    logging.info("Interval: %ds", args.interval)
    logging.info("Dry-run:  %s", args.dry_run)
    logging.info("Mode:     %s", "single pass" if args.once else "daemon loop")

    # Load config
    config = load_config(config_path)

    if not config.get("instantly_api_key"):
        logging.error("No instantly_api_key found in config.")
        sys.exit(1)

    anthropic_key = config.get("anthropic_api_key") or os.environ.get("ANTHROPIC_API_KEY")
    if not anthropic_key:
        logging.error("No Anthropic API key found in config or ANTHROPIC_API_KEY env var.")
        sys.exit(1)

    if args.once:
        stats = run_once(config, dry_run=args.dry_run)
        _log_stats(stats)
        logging.info("Single pass complete. Exiting.")
    else:
        logging.info("Entering daemon loop (poll every %ds). Press Ctrl+C to stop.", args.interval)
        cycle = 0
        while not _shutdown:
            cycle += 1
            logging.info("--- Cycle %d ---", cycle)
            try:
                stats = run_once(config, dry_run=args.dry_run)
                _log_stats(stats)
            except Exception as e:
                logging.error("Unhandled error in cycle %d: %s", cycle, e, exc_info=True)

            if _shutdown:
                break

            # Sleep in small increments so we can respond to shutdown signals quickly
            slept = 0
            while slept < args.interval and not _shutdown:
                time.sleep(min(5, args.interval - slept))
                slept += 5

        logging.info("Daemon stopped gracefully.")


def _log_stats(stats: dict):
    """Log cycle summary statistics."""
    logging.info(
        "Cycle stats: campaigns=%d, replies_found=%d, new=%d, classified=%d, "
        "sent=%d, skipped=%d, errors=%d",
        stats.get("campaigns_checked", 0),
        stats.get("replies_found", 0),
        stats.get("replies_new", 0),
        stats.get("replies_classified", 0),
        stats.get("replies_sent", 0),
        stats.get("replies_skipped", 0),
        stats.get("errors", 0),
    )


if __name__ == "__main__":
    main()
