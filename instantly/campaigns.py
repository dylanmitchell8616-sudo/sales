"""Campaign management for Instantly."""

import yaml
from pathlib import Path
from .client import InstantlyClient


class CampaignManager:
    """High-level campaign management - create, configure, and launch campaigns."""

    def __init__(self, client: InstantlyClient, config: dict = None):
        self.client = client
        self.config = config or {}
        self.campaign_defaults = self.config.get("campaigns", {})

    def create_full_campaign(self, name: str, sequences: list[dict],
                              account_emails: list[str], leads: list[dict],
                              schedule: dict = None) -> dict:
        """Create a complete campaign with sequences, accounts, leads, and schedule.

        Args:
            name: Campaign name
            sequences: List of email sequence steps, each with:
                - subject: Email subject line (supports spintax)
                - body: Email body (supports spintax and {{variables}})
                - delay: Days to wait before this step (0 for first)
            account_emails: List of sending account emails
            leads: List of lead dicts with at least 'email' field
            schedule: Optional sending schedule override
        """
        # Create campaign
        print(f"  Creating campaign: {name}")
        result = self.client.create_campaign(name=name)
        campaign_id = result.get("id") or result.get("campaign_id")
        print(f"  Campaign ID: {campaign_id}")

        # Set sequences (email steps)
        formatted_sequences = self._format_sequences(sequences)
        print(f"  Setting {len(sequences)} email sequence step(s)...")
        self.client.set_campaign_sequences(campaign_id, formatted_sequences)

        # Assign sending accounts
        print(f"  Assigning {len(account_emails)} sending account(s)...")
        self.client.set_campaign_accounts(campaign_id, account_emails)

        # Set schedule
        sending_schedule = schedule or self._default_schedule()
        print(f"  Setting sending schedule...")
        self.client.set_campaign_schedule(campaign_id, sending_schedule)

        # Add leads
        print(f"  Adding {len(leads)} lead(s)...")
        formatted_leads = self._format_leads(leads)
        self.client.add_leads_to_campaign(campaign_id, formatted_leads)

        return {"campaign_id": campaign_id, "name": name, "status": "created"}

    def launch(self, campaign_id: str) -> dict:
        """Launch a campaign."""
        print(f"  Launching campaign {campaign_id}...")
        return self.client.launch_campaign(campaign_id)

    def pause(self, campaign_id: str) -> dict:
        """Pause a campaign."""
        return self.client.pause_campaign(campaign_id)

    def get_stats(self, campaign_id: str) -> dict:
        """Get campaign performance stats."""
        summary = self.client.get_campaign_summary(campaign_id)
        return {
            "sent": summary.get("sent", 0),
            "opened": summary.get("opened", 0),
            "replied": summary.get("replied", 0),
            "bounced": summary.get("bounced", 0),
            "open_rate": self._calc_rate(summary.get("opened", 0), summary.get("sent", 0)),
            "reply_rate": self._calc_rate(summary.get("replied", 0), summary.get("sent", 0)),
            "bounce_rate": self._calc_rate(summary.get("bounced", 0), summary.get("sent", 0)),
        }

    def list_all(self) -> list:
        """List all campaigns."""
        return self.client.list_campaigns()

    def add_leads(self, campaign_id: str, leads: list[dict]) -> dict:
        """Add more leads to an existing campaign."""
        formatted = self._format_leads(leads)
        return self.client.add_leads_to_campaign(campaign_id, formatted)

    def _format_sequences(self, sequences: list[dict]) -> list:
        """Format sequences for the Instantly API."""
        steps = []
        for i, seq in enumerate(sequences):
            step = {
                "subject": seq["subject"],
                "body": seq["body"],
            }
            if i > 0:
                delay_days = seq.get("delay", self.campaign_defaults.get(
                    "default_sequence_delay_days", 3))
                step["delay"] = delay_days
            steps.append(step)
        return [{"steps": steps}]

    def _format_leads(self, leads: list[dict]) -> list:
        """Format leads for the Instantly API."""
        formatted = []
        for lead in leads:
            entry = {"email": lead["email"]}
            # Map common fields to Instantly's custom variables
            for field in ["first_name", "last_name", "company", "title",
                          "website", "phone", "linkedin", "custom1", "custom2"]:
                if field in lead:
                    entry[field] = lead[field]
            formatted.append(entry)
        return formatted

    def _default_schedule(self) -> list:
        """Create default sending schedule from config."""
        sending = self.config.get("sending", {})
        start = sending.get("sending_window_start", "08:00")
        end = sending.get("sending_window_end", "17:00")
        tz = sending.get("timezone", "America/New_York")

        # Monday-Friday schedule
        return {
            "schedules": [{
                "name": "Default",
                "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                "timezone": tz,
                "timing": {"from": start, "to": end},
            }],
        }

    @staticmethod
    def _calc_rate(numerator: int, denominator: int) -> str:
        if denominator == 0:
            return "0%"
        return f"{(numerator / denominator) * 100:.1f}%"
