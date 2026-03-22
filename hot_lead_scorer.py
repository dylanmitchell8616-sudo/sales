#!/usr/bin/env python3
"""
Hot Lead Scorer — Scores inbound replies on a 1-20 scale for prioritization.

Designed to be imported by reply_autopilot.py and hot_lead_notifier.py.
Evaluates leads based on reply category, engagement signals, company fit,
response timing, engagement velocity, multi-touch activity, and recency
to produce an actionable priority score with human-readable explanations.

Usage (standalone):
    python hot_lead_scorer.py --email sarah@smithdental.com \
        --name "Sarah Johnson" --company "Smith Dental" \
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
from datetime import datetime, timezone, timedelta

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

# ICP industry match bonus
ICP_INDUSTRIES = {
    "med spa", "dental", "aesthetic", "wellness", "iv clinic",
    "plastic surgery", "dermatology", "chiropractic", "orthodontic",
    "cosmetic", "spa", "medspa", "medical spa", "dentistry",
}
ICP_INDUSTRY_BONUS = 2

# Engagement velocity bonus (reply within N minutes of email open)
VELOCITY_FAST_MINUTES = 30
VELOCITY_MODERATE_MINUTES = 120
VELOCITY_FAST_BONUS = 3
VELOCITY_MODERATE_BONUS = 1

# Multi-touch bonus (replied to multiple campaigns/emails)
MULTI_TOUCH_2_BONUS = 2
MULTI_TOUCH_3_BONUS = 3

# Recency decay: activity older than N days gets reduced weight
RECENCY_FRESH_DAYS = 3
RECENCY_STALE_DAYS = 14
RECENCY_STALE_PENALTY = -2

# Priority tiers
PRIORITY_THRESHOLDS = [
    (16, "critical"),
    (11, "high"),
    (6, "medium"),
    (1, "low"),
]

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


def _count_previous_replies(contact_email: str, processed: dict) -> int:
    """Count how many previous replies exist from this contact email."""
    if not contact_email or not processed:
        return 0
    email_lower = contact_email.lower().strip()
    count = 0
    for _reply_id, data in processed.items():
        if not isinstance(data, dict):
            continue
        existing_email = data.get("contact_email", "")
        if existing_email and existing_email.lower().strip() == email_lower:
            count += 1
    return count


def _get_latest_reply_age_days(contact_email: str, processed: dict) -> float | None:
    """Return the age in days of the most recent previous reply from this contact.

    Returns None if no previous replies exist.
    """
    if not contact_email or not processed:
        return None
    email_lower = contact_email.lower().strip()
    now = datetime.now(timezone.utc)
    latest_dt = None
    for _reply_id, data in processed.items():
        if not isinstance(data, dict):
            continue
        existing_email = data.get("contact_email", "")
        if not existing_email or existing_email.lower().strip() != email_lower:
            continue
        ts = data.get("processed_at", "")
        if ts:
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if latest_dt is None or dt > latest_dt:
                    latest_dt = dt
            except (ValueError, TypeError):
                pass
    if latest_dt is None:
        return None
    return (now - latest_dt).total_seconds() / 86400.0


def _check_industry_match(company_name: str, config: dict) -> bool:
    """Check if the company name or industry field matches ICP industries."""
    # Check explicit industry field first
    custom_vars = config.get("custom_variables", {})
    industry = (custom_vars.get("industry", "") or "").lower()
    company_lower = (company_name or "").lower()

    check_strings = [industry, company_lower]
    for s in check_strings:
        if not s:
            continue
        for icp_ind in ICP_INDUSTRIES:
            if icp_ind in s:
                return True
    return False


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
            - ``custom_variables``: dict with ``employee_count``, ``industry``.
            - ``contacted_at``: ISO timestamp of when the prospect was contacted.
            - ``opened_at``: ISO timestamp of when the prospect opened the email.
            - ``replied_at``: ISO timestamp of when the prospect replied.

    Returns:
        dict with keys:
            - ``score`` (int): 1-20 composite score.
            - ``factors`` (list[str]): Human-readable factor descriptions.
            - ``priority`` (str): "critical", "high", "medium", or "low".
            - ``explanation`` (str): Plain-English summary of why the lead scored this way.
    """
    score = 0
    factors: list[str] = []
    explanations: list[str] = []

    # --- 1. Reply category score ---
    cat_score = CATEGORY_SCORES.get(category, 0)
    if cat_score > 0:
        score += cat_score
        factors.append(f"category:{category}(+{cat_score})")
        cat_labels = {
            "direct_intent": "They want to book a call",
            "meeting_booked": "Meeting already booked",
            "how_much": "Asking about pricing (strong buying signal)",
            "send_proof": "Wants proof/case studies (evaluating seriously)",
            "how_does_it_work": "Curious about the product",
            "positive_other": "Positive response",
            "timing": "Interested but timing issue",
        }
        explanations.append(cat_labels.get(category, f"Category: {category}"))

    # --- 2. First-time responder from company domain ---
    domain = _extract_domain(contact_email)
    processed = _load_processed_replies(config)

    if _is_first_reply_from_domain(domain, contact_email, processed):
        score += FIRST_REPLY_BONUS
        factors.append(f"first_from_domain(+{FIRST_REPLY_BONUS})")
        explanations.append(f"First person from {domain} to reply")

    # --- 3. Reply speed (time from contact to reply) ---
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
                factors.append(f"fast_response(+{FAST_RESPONSE_BONUS})")
                explanations.append(f"Replied within {hours_elapsed:.0f}h of contact")
            elif hours_elapsed <= 72:
                score += MODERATE_RESPONSE_BONUS
                factors.append(f"moderate_response(+{MODERATE_RESPONSE_BONUS})")
                explanations.append(f"Replied within {hours_elapsed:.0f}h of contact")
        except (ValueError, TypeError) as exc:
            logger.debug("Could not parse contacted_at '%s': %s", contacted_at_str, exc)

    # --- 4. Engagement velocity (time from email open to reply) ---
    opened_at_str = config.get("opened_at")
    replied_at_str = config.get("replied_at")
    if opened_at_str and replied_at_str:
        try:
            opened_at = datetime.fromisoformat(opened_at_str)
            replied_at = datetime.fromisoformat(replied_at_str)
            if opened_at.tzinfo is None:
                opened_at = opened_at.replace(tzinfo=timezone.utc)
            if replied_at.tzinfo is None:
                replied_at = replied_at.replace(tzinfo=timezone.utc)
            minutes_to_reply = (replied_at - opened_at).total_seconds() / 60.0

            if 0 < minutes_to_reply <= VELOCITY_FAST_MINUTES:
                score += VELOCITY_FAST_BONUS
                factors.append(f"velocity_fast(+{VELOCITY_FAST_BONUS})")
                explanations.append(f"Replied {minutes_to_reply:.0f}min after opening email (very engaged)")
            elif 0 < minutes_to_reply <= VELOCITY_MODERATE_MINUTES:
                score += VELOCITY_MODERATE_BONUS
                factors.append(f"velocity_moderate(+{VELOCITY_MODERATE_BONUS})")
                explanations.append(f"Replied {minutes_to_reply:.0f}min after opening email")
        except (ValueError, TypeError) as exc:
            logger.debug("Could not parse open/reply timestamps: %s", exc)

    # --- 5. Reply length (engagement signal) ---
    word_count = _count_words(reply_text)
    if word_count > LONG_REPLY_THRESHOLD:
        score += LONG_REPLY_BONUS
        factors.append(f"long_reply(+{LONG_REPLY_BONUS})")
        explanations.append(f"Wrote a detailed reply ({word_count} words)")
    elif word_count >= SHORT_REPLY_THRESHOLD:
        score += SHORT_REPLY_BONUS
        factors.append(f"engaged_reply(+{SHORT_REPLY_BONUS})")
        explanations.append(f"Wrote a substantive reply ({word_count} words)")

    # --- 6. Company size ICP match ---
    custom_vars = config.get("custom_variables", {})
    employee_count = custom_vars.get("employee_count")
    if employee_count is not None:
        try:
            emp = int(str(employee_count).replace(",", "").strip())
            if ICP_SIZE_MIN <= emp <= ICP_SIZE_MAX:
                score += ICP_SIZE_BONUS
                factors.append(f"icp_size_match(+{ICP_SIZE_BONUS})")
                explanations.append(f"Company has {emp} employees (ideal ICP range {ICP_SIZE_MIN}-{ICP_SIZE_MAX})")
        except (ValueError, TypeError):
            logger.debug("Non-numeric employee_count: %s", employee_count)

    # --- 7. Industry match ---
    if _check_industry_match(company_name, config):
        score += ICP_INDUSTRY_BONUS
        factors.append(f"icp_industry(+{ICP_INDUSTRY_BONUS})")
        explanations.append(f"{company_name} matches target industry vertical")

    # --- 8. Multi-touch bonus (replied to multiple emails = higher intent) ---
    prev_reply_count = _count_previous_replies(contact_email, processed)
    if prev_reply_count >= 3:
        score += MULTI_TOUCH_3_BONUS
        factors.append(f"multi_touch_3+(+{MULTI_TOUCH_3_BONUS})")
        explanations.append(f"Replied {prev_reply_count + 1} times across campaigns (very high intent)")
    elif prev_reply_count >= 1:
        score += MULTI_TOUCH_2_BONUS
        factors.append(f"multi_touch(+{MULTI_TOUCH_2_BONUS})")
        explanations.append(f"Replied {prev_reply_count + 1} times (repeat engagement)")

    # --- 9. Recency weighting (recent activity scores higher) ---
    reply_age_days = _get_latest_reply_age_days(contact_email, processed)
    if reply_age_days is not None and reply_age_days > RECENCY_STALE_DAYS:
        score += RECENCY_STALE_PENALTY
        factors.append(f"stale_activity({RECENCY_STALE_PENALTY})")
        explanations.append(f"Last activity was {reply_age_days:.0f} days ago (cooling off)")

    # Clamp score to 1-20
    score = max(1, min(20, score))

    priority = _get_priority(score)

    # Build explanation string
    explanation = _build_explanation(
        score, priority, contact_name, company_name, explanations
    )

    return {
        "score": score,
        "factors": factors,
        "priority": priority,
        "explanation": explanation,
    }


def _build_explanation(
    score: int,
    priority: str,
    contact_name: str,
    company_name: str,
    explanations: list[str],
) -> str:
    """Build a plain-English explanation of why this lead scored this way.

    This gives Dylan immediate context on WHY a lead is hot without
    having to decode factor codes.
    """
    name = contact_name or "This prospect"
    company = f" at {company_name}" if company_name else ""

    urgency_map = {
        "critical": "CALL IMMEDIATELY",
        "high": "Call today",
        "medium": "Follow up soon",
        "low": "Monitor",
    }
    action = urgency_map.get(priority, "Review")

    lines = [f"Score {score}/20 ({priority.upper()}) - {action}"]
    lines.append(f"{name}{company}:")
    for exp in explanations:
        lines.append(f"  - {exp}")

    return "\n".join(lines)


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
        Factors: category:direct_intent(+8), first_from_domain(+3), velocity_fast(+3)
        WHY: They want to book a call | First person from smithdental.com to reply | Replied 12min after opening email

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
    explanation = score_result.get("explanation", "")

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

    msg = (
        f"[SCORE {score}/20 {priority}] "
        f"{name_part} at {company_part} {action_summary} | "
        f"Factors: {factors_str}"
    )

    # Append the explanation for quick context
    if explanation:
        # Extract just the bullet points from the explanation
        exp_lines = [l.strip() for l in explanation.split("\n") if l.strip().startswith("- ")]
        if exp_lines:
            msg += "\n  WHY: " + " | ".join(l.lstrip("- ") for l in exp_lines)

    return msg


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
    parser.add_argument("--industry", default=None, help="Company industry")
    parser.add_argument("--contacted-at", default=None, help="ISO timestamp of initial contact")
    parser.add_argument("--opened-at", default=None, help="ISO timestamp when email was opened")
    parser.add_argument("--replied-at", default=None, help="ISO timestamp when prospect replied")
    parser.add_argument("--config", default=None, help="Path to config.json")

    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    config: dict = {}
    if args.config and os.path.exists(args.config):
        with open(args.config, encoding="utf-8") as f:
            config = json.load(f)

    if args.employee_count is not None:
        config.setdefault("custom_variables", {})["employee_count"] = args.employee_count

    if args.industry:
        config.setdefault("custom_variables", {})["industry"] = args.industry

    if args.contacted_at:
        config["contacted_at"] = args.contacted_at

    if args.opened_at:
        config["opened_at"] = args.opened_at

    if args.replied_at:
        config["replied_at"] = args.replied_at

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
    print()
    print("Explanation:")
    print(result.get("explanation", "(none)"))
    print()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
