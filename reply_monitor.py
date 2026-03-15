#!/usr/bin/env python3
"""Daemon that monitors Instantly campaigns for new replies and auto-responds.

Usage:
    python reply_monitor.py          # Run as a long-running daemon (polls every 2 min)
    python reply_monitor.py --once   # Single poll cycle, then exit
"""

import os, sys, time, json, schedule, signal
from pathlib import Path
from datetime import datetime, timezone, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv
load_dotenv()

from instantly.client import InstantlyClient
from replies.responder import AutoResponder

# ======================================================================
# Constants
# ======================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
REPLIES_DIR = PROJECT_ROOT / "replies"
HANDLED_REPLIES_PATH = REPLIES_DIR / "handled_replies.json"
REPLY_LOG_PATH = REPLIES_DIR / "reply_log.json"

CAMPAIGN_IDS = {
    "672fa45d-ed45-463e-9198-6137ee7043d9": "Cost Angle",
    "c5d69ff5-357b-42c6-bd3a-f5eff9c8ca22": "Time Angle",
    "0571c68e-e187-41c6-9e32-0cf7b8a7d84d": "Social Proof",
}

POLL_INTERVAL_MINUTES = 2

# ANSI colors for terminal output
class Color:
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


# ======================================================================
# Persistence helpers
# ======================================================================

def load_handled_replies() -> set:
    """Load the set of already-handled reply IDs from disk."""
    if HANDLED_REPLIES_PATH.exists():
        try:
            with open(HANDLED_REPLIES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return set(data) if isinstance(data, list) else set()
        except (json.JSONDecodeError, IOError):
            return set()
    return set()


def save_handled_replies(handled: set):
    """Persist the set of handled reply IDs to disk."""
    REPLIES_DIR.mkdir(parents=True, exist_ok=True)
    with open(HANDLED_REPLIES_PATH, "w", encoding="utf-8") as f:
        json.dump(sorted(handled), f, indent=2)


def append_to_log(entry: dict):
    """Append a single log entry to the reply log JSON file."""
    REPLIES_DIR.mkdir(parents=True, exist_ok=True)

    log = []
    if REPLY_LOG_PATH.exists():
        try:
            with open(REPLY_LOG_PATH, "r", encoding="utf-8") as f:
                log = json.load(f)
                if not isinstance(log, list):
                    log = []
        except (json.JSONDecodeError, IOError):
            log = []

    log.append(entry)

    with open(REPLY_LOG_PATH, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2)


# ======================================================================
# Stats tracker
# ======================================================================

class Stats:
    """Tracks reply-handling statistics for the current session."""

    def __init__(self):
        self.total_handled = 0
        self.by_category: dict[str, int] = {}
        self.errors = 0
        self.skipped_ooo = 0
        self.skipped_already_handled = 0
        self.polls = 0

    def record(self, category: str):
        self.total_handled += 1
        self.by_category[category] = self.by_category.get(category, 0) + 1

    def print_summary(self):
        print(f"\n{Color.BOLD}{'=' * 56}{Color.RESET}")
        print(f"{Color.BOLD}  SESSION STATS{Color.RESET}")
        print(f"{'=' * 56}")
        print(f"  Polls completed:        {self.polls}")
        print(f"  Total replies handled:  {self.total_handled}")
        print(f"  Skipped (already done):  {self.skipped_already_handled}")
        print(f"  Skipped (out-of-office): {self.skipped_ooo}")
        print(f"  Errors:                 {self.errors}")
        if self.by_category:
            print(f"\n  Breakdown by category:")
            for cat, count in sorted(self.by_category.items(), key=lambda x: -x[1]):
                print(f"    {cat:30s} {count}")
        print(f"{'=' * 56}\n")


# ======================================================================
# Core monitor logic
# ======================================================================

class ReplyMonitor:
    """Polls Instantly for new replies and sends auto-responses."""

    def __init__(self):
        api_key = os.getenv("INSTANTLY_API_KEY")
        if not api_key:
            print(f"{Color.RED}ERROR: INSTANTLY_API_KEY not set in .env{Color.RESET}")
            sys.exit(1)

        self.client = InstantlyClient(api_key)
        self.responder = AutoResponder()
        self.handled = load_handled_replies()
        self.stats = Stats()
        self._shutdown = False

    def fetch_replies(self, campaign_id: str) -> list[dict]:
        """Fetch reply emails for a campaign from Instantly API v2.

        Tries the campaign-scoped email listing endpoint. Falls back
        gracefully on API errors so the daemon never crashes.
        """
        try:
            result = self.client.get(
                "emails",
                params={
                    "campaign_id": campaign_id,
                    "email_type": "reply",
                    "limit": 100,
                },
            )
            if isinstance(result, dict):
                return result.get("items", result.get("data", []))
            if isinstance(result, list):
                return result
            return []
        except Exception as exc:
            campaign_name = CAMPAIGN_IDS.get(campaign_id, campaign_id[:8])
            print(
                f"  {Color.RED}Error fetching replies for "
                f"{campaign_name}: {exc}{Color.RESET}"
            )
            self.stats.errors += 1
            return []

    def send_reply(self, email_id: str, html_body: str) -> bool:
        """Send a reply via the Instantly API.

        Tries POST emails/{id}/reply first. If that fails with a 4xx,
        falls back to POST emails/reply with reply_to_uuid.
        """
        # Primary endpoint
        try:
            self.client.post(
                f"emails/{email_id}/reply",
                json={"body": html_body},
            )
            return True
        except Exception:
            pass

        # Fallback endpoint
        try:
            self.client.post(
                "emails/reply",
                json={"reply_to_uuid": email_id, "body": html_body},
            )
            return True
        except Exception as exc:
            print(
                f"    {Color.RED}Failed to send reply for "
                f"{email_id}: {exc}{Color.RESET}"
            )
            self.stats.errors += 1
            return False

    def remove_lead_from_campaign(self, campaign_id: str, email: str):
        """Remove a lead from a campaign (used for not_interested replies)."""
        try:
            self.client.delete_lead(campaign_id, email)
            print(
                f"    {Color.YELLOW}Removed {email} from campaign{Color.RESET}"
            )
        except Exception as exc:
            print(
                f"    {Color.RED}Failed to remove lead {email}: {exc}{Color.RESET}"
            )
            self.stats.errors += 1

    def _extract_reply_id(self, reply: dict) -> str | None:
        """Extract a unique identifier from a reply object."""
        return (
            reply.get("id")
            or reply.get("uuid")
            or reply.get("email_id")
            or reply.get("message_id")
        )

    def _extract_lead_data(self, reply: dict) -> dict:
        """Build lead_data dict for the AutoResponder from reply fields."""
        # Instantly may nest lead info differently; try common patterns.
        lead = reply.get("lead", {}) if isinstance(reply.get("lead"), dict) else {}

        first_name = (
            lead.get("first_name")
            or reply.get("first_name")
            or reply.get("from_name", "").split()[0] if reply.get("from_name") else ""
        )
        company = (
            lead.get("company")
            or reply.get("company")
            or lead.get("company_name")
            or reply.get("company_name")
            or ""
        )
        email = (
            lead.get("email")
            or reply.get("from_email")
            or reply.get("from")
            or reply.get("email")
            or ""
        )

        return {
            "firstName": first_name or "",
            "companyName": company or "",
            "email": email,
        }

    def _extract_reply_text(self, reply: dict) -> str:
        """Get the plain text body of a reply."""
        return (
            reply.get("body_text")
            or reply.get("text_body")
            or reply.get("body")
            or reply.get("text")
            or ""
        )

    def process_reply(self, reply: dict, campaign_id: str) -> bool:
        """Process a single reply. Returns True if handled successfully."""
        reply_id = self._extract_reply_id(reply)
        if not reply_id:
            return False

        # Already handled?
        if reply_id in self.handled:
            self.stats.skipped_already_handled += 1
            return False

        reply_text = self._extract_reply_text(reply)
        lead_data = self._extract_lead_data(reply)
        lead_email = lead_data.get("email", "unknown")

        # Classify
        category = self.responder.classify_reply(reply_text)

        # Skip out-of-office
        if category == "out_of_office":
            print(
                f"    {Color.DIM}[OOO] {lead_email} — skipped "
                f"(out-of-office){Color.RESET}"
            )
            self.handled.add(reply_id)
            save_handled_replies(self.handled)
            self.stats.skipped_ooo += 1
            append_to_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lead_email": lead_email,
                "campaign_id": campaign_id,
                "campaign_name": CAMPAIGN_IDS.get(campaign_id, ""),
                "classification": category,
                "response_sent": False,
                "action": "skipped_ooo",
            })
            return False

        # Check if we should auto-respond (human review guard)
        if not self.responder.should_respond(reply_text):
            print(
                f"    {Color.MAGENTA}[HUMAN] {lead_email} — flagged for "
                f"human review{Color.RESET}"
            )
            self.handled.add(reply_id)
            save_handled_replies(self.handled)
            append_to_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lead_email": lead_email,
                "campaign_id": campaign_id,
                "campaign_name": CAMPAIGN_IDS.get(campaign_id, ""),
                "classification": category,
                "response_sent": False,
                "action": "flagged_human_review",
            })
            return False

        # Generate response
        response_text = self.responder.generate_response(reply_text, lead_data)
        if response_text is None:
            self.handled.add(reply_id)
            save_handled_replies(self.handled)
            return False

        response_html = AutoResponder.format_reply_html(response_text)

        # Send the reply
        color = Color.GREEN if category == "positive" else Color.YELLOW
        print(
            f"    {color}[{category.upper()}] {lead_email} — "
            f"sending response...{Color.RESET}"
        )

        sent = self.send_reply(reply_id, response_html)

        if sent:
            self.handled.add(reply_id)
            save_handled_replies(self.handled)
            self.stats.record(category)

            # Remove lead from campaign if not interested
            if category == "not_interested":
                self.remove_lead_from_campaign(campaign_id, lead_email)

            append_to_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lead_email": lead_email,
                "campaign_id": campaign_id,
                "campaign_name": CAMPAIGN_IDS.get(campaign_id, ""),
                "classification": category,
                "response_sent": True,
                "response_preview": response_text[:120],
            })

            print(
                f"    {Color.GREEN}Sent reply to {lead_email}{Color.RESET}"
            )
            return True
        else:
            # Don't mark as handled — will retry on next poll
            append_to_log({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "lead_email": lead_email,
                "campaign_id": campaign_id,
                "campaign_name": CAMPAIGN_IDS.get(campaign_id, ""),
                "classification": category,
                "response_sent": False,
                "action": "send_failed_will_retry",
            })
            return False

    def poll(self):
        """Run one poll cycle across all monitored campaigns."""
        self.stats.polls += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(
            f"\n{Color.CYAN}{Color.BOLD}[{now}] "
            f"Polling for new replies...{Color.RESET}"
        )

        total_new = 0

        for campaign_id, campaign_name in CAMPAIGN_IDS.items():
            print(f"\n  {Color.BOLD}{campaign_name}{Color.RESET} ({campaign_id[:8]}...)")

            replies = self.fetch_replies(campaign_id)

            if not replies:
                print(f"    {Color.DIM}No replies found{Color.RESET}")
                continue

            new_count = 0
            for reply in replies:
                reply_id = self._extract_reply_id(reply)
                if reply_id and reply_id not in self.handled:
                    new_count += 1

            if new_count == 0:
                print(
                    f"    {Color.DIM}{len(replies)} replies total, "
                    f"all already handled{Color.RESET}"
                )
                continue

            print(
                f"    {Color.GREEN}{new_count} new "
                f"repl{'y' if new_count == 1 else 'ies'} "
                f"(of {len(replies)} total){Color.RESET}"
            )

            for reply in replies:
                try:
                    if self.process_reply(reply, campaign_id):
                        total_new += 1
                except Exception as exc:
                    lead_email = self._extract_lead_data(reply).get("email", "?")
                    print(
                        f"    {Color.RED}Error processing reply from "
                        f"{lead_email}: {exc}{Color.RESET}"
                    )
                    self.stats.errors += 1

        if total_new > 0:
            print(
                f"\n{Color.GREEN}{Color.BOLD}Handled {total_new} new "
                f"repl{'y' if total_new == 1 else 'ies'} this cycle"
                f"{Color.RESET}"
            )
        else:
            print(
                f"\n  {Color.DIM}No new replies to handle{Color.RESET}"
            )

    def request_shutdown(self):
        """Signal the daemon to stop after the current cycle."""
        self._shutdown = True

    def run_daemon(self):
        """Run the monitor as a long-running daemon with scheduled polling."""
        print(f"\n{Color.BOLD}{'=' * 56}{Color.RESET}")
        print(f"{Color.BOLD}  REPLY MONITOR DAEMON{Color.RESET}")
        print(f"  Monitoring {len(CAMPAIGN_IDS)} campaigns")
        print(f"  Poll interval: every {POLL_INTERVAL_MINUTES} minutes")
        print(f"  Handled replies file: {HANDLED_REPLIES_PATH}")
        print(f"  Log file: {REPLY_LOG_PATH}")
        print(f"  Already handled: {len(self.handled)} replies")
        print(f"  Press Ctrl+C to stop")
        print(f"{'=' * 56}\n")

        # Run first poll immediately
        self.poll()

        # Schedule subsequent polls
        schedule.every(POLL_INTERVAL_MINUTES).minutes.do(self.poll)

        while not self._shutdown:
            try:
                schedule.run_pending()
                time.sleep(1)
            except KeyboardInterrupt:
                break

        self.stats.print_summary()
        print(f"{Color.GREEN}Daemon stopped gracefully.{Color.RESET}")

    def run_once(self):
        """Run a single poll cycle and exit."""
        print(f"\n{Color.BOLD}{'=' * 56}{Color.RESET}")
        print(f"{Color.BOLD}  REPLY MONITOR (one-shot){Color.RESET}")
        print(f"  Monitoring {len(CAMPAIGN_IDS)} campaigns")
        print(f"  Already handled: {len(self.handled)} replies")
        print(f"{'=' * 56}")

        self.poll()
        self.stats.print_summary()


# ======================================================================
# Entry point
# ======================================================================

def main():
    monitor = ReplyMonitor()

    # Graceful shutdown on SIGTERM (systemd, Docker, etc.)
    def handle_signal(signum, frame):
        print(f"\n{Color.YELLOW}Received signal {signum}, shutting down...{Color.RESET}")
        monitor.request_shutdown()

    signal.signal(signal.SIGTERM, handle_signal)

    if "--once" in sys.argv:
        monitor.run_once()
    else:
        try:
            monitor.run_daemon()
        except KeyboardInterrupt:
            monitor.stats.print_summary()
            print(f"{Color.GREEN}Daemon stopped gracefully.{Color.RESET}")


if __name__ == "__main__":
    main()
