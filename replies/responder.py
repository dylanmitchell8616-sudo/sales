"""
Auto-reply engine for cold email campaigns.

Monitors replies to cold email campaigns sent via Instantly,
classifies them by intent, handles objections, and books meetings
via Calendly link.
"""

import re
from html import escape


CALENDLY_LINK = "https://calendly.com/realsideai"
SENDER_NAME = "Dylan"

# Words that flag a reply for human review instead of auto-response.
HUMAN_REVIEW_KEYWORDS = [
    "legal", "lawsuit", "lawyer", "attorney", "angry", "reported",
    "harassment", "spam report", "compliance", "cease and desist",
    "threatening", "authorities",
]

# Category keyword definitions. Order matters — earlier categories take
# priority when multiple could match.
CATEGORY_KEYWORDS = {
    "out_of_office": [
        "out of office", "ooo", "on vacation", "on leave", "away from",
        "auto-reply", "automatic reply", "will return",
    ],
    "not_interested": [
        "not interested", "no thanks", "remove me", "unsubscribe",
        "stop emailing", "don't contact", "take me off", "no thank you",
    ],
    "objection_budget": [
        "expensive", "budget", "cost too", "afford", "not in budget",
        "too much", "pricing concern",
    ],
    "objection_timing": [
        "not right now", "bad timing", "maybe later", "next quarter",
        "busy right now", "circle back", "not a priority", "revisit",
        "down the road", "few months",
    ],
    "objection_competitor": [
        "already have", "already use", "using another", "competitor",
        "current solution", "happy with", "switched to", "contract with",
    ],
    "objection_not_relevant": [
        "not hiring", "no open roles", "not relevant", "doesn't apply",
        "wrong person", "not my department", "not looking",
    ],
    "positive": [
        "interested", "tell me more", "sounds good", "let's chat",
        "sure", "love to", "set up a time", "sounds interesting",
        "how does it work", "pricing", "cost", "demo", "learn more",
        "open to", "yes", "absolutely", "definitely",
    ],
}

RESPONSES = {
    "positive": (
        "Great to hear, {{firstName}}! Happy to walk you through how it "
        "works for {{companyName}}. Here's a link to grab 10 minutes on "
        f"my calendar: {CALENDLY_LINK} — pick whatever works best for "
        f"you.\n\nTalk soon,\n{SENDER_NAME}"
    ),
    "objection_budget": (
        "Totally understand, {{firstName}}. Most of our clients actually "
        "save money — the average is $2,800 less per hire compared to "
        "traditional recruiting. Happy to show you the numbers in 10 "
        f"minutes: {CALENDLY_LINK}\n\n— {SENDER_NAME}"
    ),
    "objection_timing": (
        "No rush at all, {{firstName}}. When the timing is right, I'm "
        "here. That said, a lot of teams set it up now so it's ready "
        "when they need it. If you want a quick look at how it works, "
        f"here's my calendar: {CALENDLY_LINK}\n\n— {SENDER_NAME}"
    ),
    "objection_competitor": (
        "Good to hear you have something in place, {{firstName}}. "
        "Curious though — does your current solution handle everything "
        "from sourcing through scheduling, or is your team still "
        "involved in the middle steps? If you ever want to compare, "
        f"happy to do a quick walkthrough: {CALENDLY_LINK}\n\n"
        f"— {SENDER_NAME}"
    ),
    "objection_not_relevant": (
        "Appreciate you letting me know, {{firstName}}. My mistake on "
        "the targeting. Out of curiosity, is there someone else at "
        "{{companyName}} who handles recruiting that I should reach out "
        f"to instead? Either way, sorry for the noise.\n\n— {SENDER_NAME}"
    ),
    "not_interested": (
        "Understood, {{firstName}}. Appreciate you letting me know. "
        "I'll make sure you don't hear from me again. Wishing you and "
        f"{{{{companyName}}}} all the best.\n\n— {SENDER_NAME}"
    ),
    "out_of_office": None,
    "question": (
        "Great question, {{firstName}}. The short answer is — our AI "
        "handles the full recruiting pipeline (sourcing, screening, "
        "assessments, scheduling) so your team only steps in for the "
        "final interview. Happy to go deeper on a quick call: "
        f"{CALENDLY_LINK}\n\n— {SENDER_NAME}"
    ),
}


class AutoResponder:
    """Classifies cold-email replies and generates appropriate responses."""

    def __init__(self):
        self.responses = dict(RESPONSES)

    # ------------------------------------------------------------------
    # 1. Classification
    # ------------------------------------------------------------------

    def classify_reply(self, reply_text: str) -> str:
        """Classify an incoming reply into a category using keyword matching.

        Args:
            reply_text: The raw text of the reply email.

        Returns:
            A category string such as "positive", "objection_budget", etc.
        """
        text_lower = reply_text.lower()

        # Check each category in priority order.
        for category, keywords in CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in text_lower:
                    return category

        # Fall back to "question" if the reply contains a question mark.
        if "?" in reply_text:
            return "question"

        # Default: treat as positive (they replied, so there is some interest).
        return "positive"

    # ------------------------------------------------------------------
    # 2. Response generation
    # ------------------------------------------------------------------

    def generate_response(
        self,
        reply_text: str,
        lead_data: dict,
    ) -> str | None:
        """Generate a personalised response for a reply.

        Args:
            reply_text: The raw text of the reply email.
            lead_data: Dict with at least ``firstName``, ``companyName``,
                and ``email``.

        Returns:
            The filled-in response string, or ``None`` for categories
            that should be skipped (e.g. out-of-office).
        """
        category = self.classify_reply(reply_text)
        template = self.responses.get(category)

        if template is None:
            return None

        # Fill in template variables.
        response = template.replace("{{firstName}}", lead_data.get("firstName", ""))
        response = response.replace("{{companyName}}", lead_data.get("companyName", ""))
        response = response.replace("{{email}}", lead_data.get("email", ""))

        return response

    # ------------------------------------------------------------------
    # 3. Guard: should we auto-respond?
    # ------------------------------------------------------------------

    def should_respond(self, reply_text: str) -> bool:
        """Decide whether an auto-response is appropriate.

        Returns ``False`` for out-of-office replies and for messages that
        contain sensitive keywords suggesting the situation needs human
        review.

        Args:
            reply_text: The raw text of the reply email.

        Returns:
            ``True`` if an auto-reply should be sent, ``False`` otherwise.
        """
        text_lower = reply_text.lower()

        # Skip out-of-office auto-replies.
        if self.classify_reply(reply_text) == "out_of_office":
            return False

        # Flag anything that sounds like it needs a human.
        for keyword in HUMAN_REVIEW_KEYWORDS:
            if keyword in text_lower:
                return False

        return True

    # ------------------------------------------------------------------
    # 4. HTML formatting
    # ------------------------------------------------------------------

    @staticmethod
    def format_reply_html(text: str) -> str:
        """Convert a plain-text response to an HTML ``<div>`` for the
        Instantly API.

        Args:
            text: Plain-text email body.

        Returns:
            HTML string wrapped in a ``<div>``.
        """
        if text is None:
            return ""

        html_body = escape(text)
        # Convert newlines to <br> tags.
        html_body = html_body.replace("\n", "<br>")
        # Make the Calendly link clickable.
        html_body = html_body.replace(
            escape(CALENDLY_LINK),
            f'<a href="{CALENDLY_LINK}">{CALENDLY_LINK}</a>',
        )

        return f"<div>{html_body}</div>"
