#!/usr/bin/env python3
"""
Hot Lead Scorer — Scores inbound replies on a 1-20 scale for prioritization.

Designed to be imported by reply_autopilot.py and hot_lead_notifier.py.
Evaluates leads based on reply category, engagement signals, company fit,
and response timing to produce an actionable priority score.

Usage (standalone):
    python hot_lead_scorer.py --email sarah@smithdental.com \\
        --name "Sarah Johnson" --company "Smith Dental" \\
        --category direct_intent --reply "I'd love to book a call"

Usage (as module):
    from hot_lead_scorer import score_hot_lead, format_score_message

    result = score_hot_lead(
        contact_email="sarah@smithdental.com",
        contact_name="Sarah Johnson",
        company_name="Smith Dental",
        category="direct_intent",
        reply_text="I'd love to book a call this week.",
        config=config,
    )
    print(format_score_message(result, "Sarah Johnson", "Smith Dental"))
"""

import json
import logging
import os
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PROCESSED_REPLIES_PATH = "output/processed_replies.json"

# Points awarded by reply category
CATEGORY_SCORES = {
    "direct_intent": 8,
    "meeting_booked": 10,
    "how_much": 6,
    "send_proof": 5,
    "how_does_it_work": 4,
    "positive_other": 3,
    "timing": 2,
}

# Bonus for first-time responder from a company domain
FIRST_REPLY_BONUS = 3

# Bonus for fast response (within 24h of contact)
FAST_RESPONSE_BONUS = 2

# Bonus for moderately fast response (within 3 days)
MODERATE_RESPONSE_BONUS = 1

# Reply length thresholds and bonuses
LONG_REPLY_THRESHOLD = 50   # words
SHORT_REPLY_THRESHOLD = 20  # words
LONG_REPLY_BONUS = 2
SHORT_REPLY_BONUS = 1

# ICP company size match bonus
ICP_SIZE_MIN = 10
ICP_SIZE_MAX = 100
ICP_SIZE_BONUS = 3

# Priority tiers
PRIORITY_THRESHOLDS = [
    (16, "critical"),
    (11, "high"),
    (6, "medium"),
    (1, "low"),
]

# Factor labels used in formatted output
FACTOR_LABELS = {
    "category": "category",
    "first_reply": "first_reply",
    "fast_response": "fast_response",
    "engaged_reply": "engaged_reply",
    "icp_size": "icp_size",
}

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_domain(email: str) -> str:
    """Return the domain portion of an email address."""
    if email and "@" in email:
        return email.split("@", 1)[1].strip().lower()
    return ""


def _load_processed_replies(config: dict) -> dict:
    """Load the processed replies tracker JSON.

    Resolves the path relative to the script directory so the scorer works
    regardless of the caller's working directory.
    """
    path = config.get("processed_replies_path", PROCESSED_REPLIES_PATH)

    # If relative, resolve from the directory where this script lives
    if not os.path.isabs(path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        path = os.path.join(script_dir, path)

    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Could not load processed replies from %s: %s", path, exc)
    return {}


def _is_first_reply_from_domain(domain: str, contact_email: str, processed: dict) -> bool:
    """Check whether any previous reply exists from the same email domain."""
    if not domain:
        return False

    contact_lower = contact_email.lower().strip()

    for _reply_id, data in processed.items():
        if not isinstance(data, dict):
            continue
        existing_email = data.get("contact_email", "")
        if not existing_email:
            continue
        # Skip the current contact's own earlier replies
        if existing_email.lower().strip() == contact_lower:
            continue
        if _extract_domain(existing_email) == domain:
            return False

    return True


def _count_words(text: str) -> int:
    """Count words in a string."""
    if not text:
        return 0
    return len(text.split())


def _get_priority(score: int) -> str:
    """Map a numeric score to a priority label."""
    for threshold, label in PRIORITY_THRESHOLDS:
        if score >= threshold:
            return label
    return "low"


# ---------------------------------------------------------------------------
# Core scoring
# ---------------------------------------------------------------------------


def score_hot_lead(
    contact_email: str,
    contact_name: str,
    company_name: str,
    category: str,
    reply_text: str,
    config: dict,
) -> dict:
    """Score a hot lead on a 1-20 scale based on multiple engagement factors.

    Args:
        contact_email: The prospect's email address.
        contact_name: The prospect's display name.
        company_name: The prospect's company name.
        category: Reply classification category (e.g. "direct_intent").
        reply_text: The full text of the prospect's reply.
        config: Pipeline config dict. May contain:
            - ``processed_replies_path``: override for processed replies JSON.
            - ``custom_variables``: dict with ``employee_count``.
            - ``contacted_at``: ISO timestamp of when the prospect was contacted.

    Returns:
        dict with keys:
            - ``score`` (int): 1-20 composite score.
            - ``factors`` (list[str]): Human-readable factor descriptions.
            - ``priority`` (str): "critical", "high", "medium", or "low".
    """
    score = 0
    factors: list[str] = []

    # --- 1. Reply category score ---
    cat_score = CATEGORY_SCORES.get(category, 0)
    if cat_score > 0:
        score += cat_score
        factors.append(f"{category}({cat_score})")

    # --- 2. First-time responder from company domain ---
    domain = _extract_domain(contact_email)
    processed = _load_processed_replies(config)

    if _is_first_reply_from_domain(domain, contact_email, processed):
        score += FIRST_REPLY_BONUS
        factors.append(f"first_reply({FIRST_REPLY_BONUS})")

    # --- 3. Reply speed ---
    contacted_at_str = config.get("contacted_at")
    if contacted_at_str:
        try:
            contacted_at = datetime.fromisoformat(contacted_at_str)
            if contacted_at.tzinfo is None:
                contacted_at = contacted_at.replace(tzinfo=timezone.utc)
            now = datetime.now(timezone.utc)
            hours_elapsed = (now - contacted_at).total_seconds() / 3600.0

            if hours_elapsed <= 24:
                score += FAST_RESPONSE_BONUS
                factors.append(f"fast_response({FAST_RESPONSE_BONUS})")
            elif hours_elapsed <= 72:
                score += MODERATE_RESPONSE_BONUS
                factors.append(f"fast_response({MODERATE_RESPONSE_BONUS})")
        except (ValueError, TypeError) as exc:
            logger.debug("Could not parse contacted_at '%s': %s", contacted_at_str, exc)

    # --- 4. Reply length (engagement signal) ---
    word_count = _count_words(reply_text)
    if word_count > LONG_REPLY_THRESHOLD:
        score += LONG_REPLY_BONUS
        factors.append(f"engaged_reply({LONG_REPLY_BONUS})")
    elif word_count >= SHORT_REPLY_THRESHOLD:
        score += SHORT_REPLY_BONUS
        factors.append(f"engaged_reply({SHORT_REPLY_BONUS})")

    # --- 5. Company size ICP match ---
    custom_vars = config.get("custom_variables", {})
    employee_count = custom_vars.get("employee_count")
    if employee_count is not None:
        try:
            emp = int(employee_count)
            if ICP_SIZE_MIN <= emp <= ICP_SIZE_MAX:
                score += ICP_SIZE_BONUS
                factors.append(f"icp_size({ICP_SIZE_BONUS})")
        except (ValueError, TypeError):
            logger.debug("Non-numeric employee_count: %s", employee_count)

    # Clamp score to 1-20
    score = max(1, min(20, score))

    priority = _get_priority(score)

    return {
        "score": score,
        "factors": factors,
        "priority": priority,
    }


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------


def format_score_message(
    score_result: dict,
    contact_name: str,
    company_name: str,
    action_summary: str = "",
) -> str:
    """Format a score result into a concise notification string.

    Example output:
        [SCORE 18/20 CRITICAL] Sarah at Smith Dental wants to book |
        Factors: direct_intent(8), first_reply(3), fast_response(2),
        engaged_reply(2), icp_size(3)

    Args:
        score_result: Dict returned by ``score_hot_lead()``.
        contact_name: Prospect name for the message.
        company_name: Company name for the message.
        action_summary: Optional short action phrase (e.g. "wants to book").
            Falls back to a generic phrase derived from priority.

    Returns:
        Formatted single-line string suitable for SMS or Slack.
    """
    score = score_result["score"]
    priority = score_result["priority"].upper()
    factors = score_result["factors"]

    name_part = contact_name or "Unknown"
    company_part = company_name or "Unknown Company"

    if not action_summary:
        summaries = {
            "CRITICAL": "wants to book",
            "HIGH": "showing strong interest",
            "MEDIUM": "engaged",
            "LOW": "replied",
        }
        action_summary = summaries.get(priority, "replied")

    factors_str = ", ".join(factors) if factors else "none"

    return (
        f"[SCORE {score}/20 {priority}] "
        f"{name_part} at {company_part} {action_summary} | "
        f"Factors: {factors_str}"
    )


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------


def main():
    """Run the scorer from the command line for testing."""
    import argparse

    parser = argparse.ArgumentParser(description="Score a hot lead (1-20 scale)")
    parser.add_argument("--email", required=True, help="Contact email")
    parser.add_argument("--name", default="", help="Contact name")
    parser.add_argument("--company", default="", help="Company name")
    parser.add_argument("--category", required=True, help="Reply category")
    parser.add_argument("--reply", default="", help="Reply text")
    parser.add_argument("--employee-count", type=int, default=None, help="Company employee count")
    parser.add_argument("--contacted-at", default=None, help="ISO timestamp of initial contact")
    parser.add_argument("--config", default=None, help="Path to config.json")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config: dict = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)

    if args.employee_count is not None:
        config.setdefault("custom_variables", {})["employee_count"] = args.employee_count

    if args.contacted_at:
        config["contacted_at"] = args.contacted_at

    result = score_hot_lead(
        contact_email=args.email,
        contact_name=args.name,
        company_name=args.company,
        category=args.category,
        reply_text=args.reply,
        config=config,
    )

    message = format_score_message(result, args.name, args.company)
    print(message)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
