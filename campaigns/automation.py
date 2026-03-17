"""Campaign automation engine for cold email outreach via Instantly.ai.

Provides high-level orchestration: create campaigns from templates, monitor
health metrics, auto-pause on high bounce rates, rotate inboxes, generate
reports, and scale campaigns up or down.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from instantly.client import InstantlyClient
from instantly.campaigns import CampaignManager
from instantly.accounts import AccountManager
from instantly.leads import LeadManager
from templates.engine import TemplateEngine


class CampaignAutomation:
    """High-level campaign automation on top of Instantly.ai.

    Ties together the template engine, campaign manager, lead manager,
    and Instantly client to provide end-to-end campaign workflows.

    Usage::

        from instantly.client import InstantlyClient
        from campaigns.automation import CampaignAutomation

        client = InstantlyClient(api_key="your-key")
        auto = CampaignAutomation(client, config=config)

        result = auto.create_campaign_from_template(
            template_name="SaaS Cold Outreach",
            leads_csv="leads/my_leads.csv",
            inbox_emails=["inbox1@domain.com", "inbox2@domain.com"],
            template_vars={"sender_name": "Alex", ...},
        )
    """

    # Default thresholds (can be overridden via config)
    DEFAULT_MAX_BOUNCE_RATE = 5.0   # percent
    DEFAULT_MIN_REPLY_RATE = 0.5    # percent — below this an inbox is "underperforming"
    DEFAULT_MIN_SENT_FOR_EVAL = 50  # need at least N sends before evaluating

    def __init__(self, client: InstantlyClient, config: dict = None,
                 template_library_path: Optional[str] = None):
        """Initialize the automation engine.

        Args:
            client: An authenticated InstantlyClient.
            config: Project config dict (typically loaded from config.yaml).
            template_library_path: Path to the YAML template library.
                Defaults to templates/library.yaml relative to project root.
        """
        self.client = client
        self.config = config or {}
        self.campaign_mgr = CampaignManager(client, config)
        self.account_mgr = AccountManager(client, config)
        self.lead_mgr = LeadManager(client, config)

        lib_path = template_library_path or str(
            Path(__file__).resolve().parent.parent / "templates" / "library.yaml"
        )
        self.template_engine = TemplateEngine(lib_path)

        # Thresholds from config
        deliv = self.config.get("deliverability", {})
        self.max_bounce_rate = deliv.get(
            "max_bounce_rate_percent", self.DEFAULT_MAX_BOUNCE_RATE
        )
        self.auto_pause_enabled = deliv.get("auto_pause_on_high_bounce", True)

    # ------------------------------------------------------------------
    # Campaign creation
    # ------------------------------------------------------------------

    def create_campaign_from_template(
        self,
        template_name: str,
        leads_csv: str,
        inbox_emails: list[str] = None,
        template_vars: dict = None,
        campaign_name: Optional[str] = None,
        schedule: dict = None,
        field_mapping: dict = None,
    ) -> dict:
        """Create a full Instantly campaign from a template name and leads CSV.

        This is the main entry point for launching a new campaign. It:
        1. Renders every step of the chosen template sequence (resolving spintax).
        2. Imports and deduplicates leads from the CSV.
        3. Creates the campaign in Instantly with sequences, inboxes, and leads.

        Args:
            template_name: Name of the sequence in the template library.
            leads_csv: Path to a CSV file with lead data.
            inbox_emails: List of sending account email addresses. If None,
                          all connected accounts are used.
            template_vars: Extra variables to merge into every lead's context
                           (e.g. sender_name, calendar_link).
            campaign_name: Optional campaign name override.
            schedule: Optional sending schedule override.
            field_mapping: Optional CSV column-name mapping.

        Returns:
            Dict with campaign_id, name, lead_count, and step_count.

        Raises:
            KeyError: If the template name is not found.
            FileNotFoundError: If the leads CSV does not exist.
            ValueError: If no valid leads are found or no inboxes are available.
        """
        # Validate template exists
        if template_name not in self.template_engine.sequences:
            raise KeyError(
                f"Template '{template_name}' not found. "
                f"Available: {self.template_engine.list_sequences()}"
            )

        # Import leads
        leads = self.lead_mgr.import_from_csv(leads_csv, field_mapping=field_mapping)
        if not leads:
            raise ValueError(f"No valid leads found in {leads_csv}")

        # Resolve sending accounts
        if not inbox_emails:
            accounts = self.account_mgr.list_all()
            inbox_emails = [
                a if isinstance(a, str) else a.get("email", "")
                for a in accounts
            ]
            inbox_emails = [e for e in inbox_emails if e]

        if not inbox_emails:
            raise ValueError("No sending accounts available. Add inboxes first.")

        # Merge template_vars into a sample lead for rendering sequences.
        # Instantly handles per-lead variable substitution via its own {{}} syntax,
        # so we resolve spintax now but keep {{lead_var}} placeholders for Instantly.
        sample_lead = dict(template_vars or {})
        sample_lead.setdefault("first_name", "{{first_name}}")
        sample_lead.setdefault("company", "{{company}}")
        sample_lead.setdefault("title", "{{title}}")
        sample_lead.setdefault("last_name", "{{last_name}}")
        sample_lead.setdefault("website", "{{website}}")

        # Render sequences (resolves spintax, keeps Instantly placeholders)
        rendered_steps = self.template_engine.render_all_steps(
            template_name, sample_lead
        )

        # Convert to the format CampaignManager expects
        sequences = []
        for step in rendered_steps:
            sequences.append({
                "subject": step["subject"],
                "body": step["body"],
                "delay": step["delay_days"],
            })

        # Create campaign
        name = campaign_name or f"{template_name} - {len(leads)} leads"
        result = self.campaign_mgr.create_full_campaign(
            name=name,
            sequences=sequences,
            account_emails=inbox_emails,
            leads=leads,
            schedule=schedule,
        )

        result["lead_count"] = len(leads)
        result["step_count"] = len(sequences)
        print(f"\n  Campaign created: {name}")
        print(f"  Leads: {len(leads)}")
        print(f"  Inboxes: {len(inbox_emails)}")
        print(f"  Sequence steps: {len(sequences)}")
        print(f"  Campaign ID: {result['campaign_id']}")
        return result

    # ------------------------------------------------------------------
    # Health monitoring
    # ------------------------------------------------------------------

    def monitor_campaign_health(self, campaign_id: str) -> dict:
        """Check campaign health metrics and return a status report.

        Evaluates bounce rate, open rate, and reply rate against thresholds
        and returns a health status of GOOD, WARNING, or CRITICAL.

        Args:
            campaign_id: The Instantly campaign ID.

        Returns:
            Dict with stats, health status, and a list of flagged issues.
        """
        stats = self.campaign_mgr.get_stats(campaign_id)

        sent = stats.get("sent", 0)
        bounced = stats.get("bounced", 0)
        replied = stats.get("replied", 0)
        opened = stats.get("opened", 0)

        bounce_rate = (bounced / sent * 100) if sent > 0 else 0.0
        reply_rate = (replied / sent * 100) if sent > 0 else 0.0
        open_rate = (opened / sent * 100) if sent > 0 else 0.0

        issues = []

        if bounce_rate > self.max_bounce_rate:
            issues.append(
                f"HIGH BOUNCE RATE: {bounce_rate:.1f}% exceeds threshold "
                f"({self.max_bounce_rate}%)"
            )
        if sent >= self.DEFAULT_MIN_SENT_FOR_EVAL and open_rate < 15:
            issues.append(
                f"LOW OPEN RATE: {open_rate:.1f}% is below 15% — consider "
                f"improving subject lines"
            )
        if sent >= self.DEFAULT_MIN_SENT_FOR_EVAL and reply_rate < 0.5:
            issues.append(
                f"LOW REPLY RATE: {reply_rate:.1f}% is very low — consider "
                f"revising email copy"
            )

        if len(issues) > 1:
            health_status = "CRITICAL"
        elif issues:
            health_status = "WARNING"
        else:
            health_status = "GOOD"

        return {
            "campaign_id": campaign_id,
            "stats": stats,
            "sent": sent,
            "bounced": bounced,
            "replied": replied,
            "opened": opened,
            "bounce_rate": round(bounce_rate, 2),
            "reply_rate": round(reply_rate, 2),
            "open_rate": round(open_rate, 2),
            "health": health_status,
            "issues": issues,
        }

    # ------------------------------------------------------------------
    # Auto-pause
    # ------------------------------------------------------------------

    def auto_pause_if_unhealthy(self, campaign_id: str) -> dict:
        """Pause a campaign if its bounce rate exceeds the configured threshold.

        Args:
            campaign_id: The Instantly campaign ID.

        Returns:
            Dict with health data and action taken.
        """
        health = self.monitor_campaign_health(campaign_id)

        if health["health"] == "CRITICAL" and self.auto_pause_enabled:
            self.campaign_mgr.pause(campaign_id)
            health["action"] = "PAUSED - fix issues before resuming"
            print(f"  [AUTO-PAUSE] Campaign {campaign_id} paused — "
                  f"bounce rate {health['bounce_rate']}%")
        else:
            health["action"] = "none"

        return health

    def auto_pause_all(self) -> list[dict]:
        """Check all active campaigns and pause any with critical health.

        Returns:
            List of health dicts for every campaign (with action taken).
        """
        campaigns = self.campaign_mgr.list_all()
        results = []

        for campaign in campaigns:
            cid = campaign if isinstance(campaign, str) else campaign.get(
                "id", campaign.get("campaign_id", "")
            )
            if cid:
                result = self.auto_pause_if_unhealthy(cid)
                results.append(result)

        return results

    # ------------------------------------------------------------------
    # Inbox rotation
    # ------------------------------------------------------------------

    def auto_rotate_inboxes(self, campaign_id: str,
                            all_available_inboxes: list[str] = None,
                            min_reply_rate: float = None) -> dict:
        """Replace underperforming inboxes in a campaign with fresh ones.

        An inbox is considered underperforming if its reply rate is below
        the minimum threshold after sufficient send volume.

        Args:
            campaign_id: The Instantly campaign ID.
            all_available_inboxes: Full pool of available inbox emails.
                If None, uses all connected accounts.
            min_reply_rate: Minimum acceptable reply rate (percent).
                            Defaults to DEFAULT_MIN_REPLY_RATE.

        Returns:
            Dict with lists of removed and added inbox emails.
        """
        if min_reply_rate is None:
            min_reply_rate = self.DEFAULT_MIN_REPLY_RATE

        # Get all connected accounts
        accounts = self.account_mgr.list_all()
        underperforming = []
        current_inboxes = set()

        for account in accounts:
            email = account if isinstance(account, str) else account.get("email", "")
            if not email:
                continue
            current_inboxes.add(email)

            try:
                analytics = self.client.get_account_analytics(email)
                sent = analytics.get("sent", 0)
                replied = analytics.get("replied", 0)

                if sent >= self.DEFAULT_MIN_SENT_FOR_EVAL:
                    rate = (replied / sent * 100) if sent > 0 else 0.0
                    if rate < min_reply_rate:
                        underperforming.append(email)
            except Exception:
                continue

        if not underperforming:
            return {
                "campaign_id": campaign_id,
                "removed": [],
                "added": [],
                "message": "All inboxes performing within thresholds.",
            }

        # Find replacement inboxes from the available pool
        if all_available_inboxes is None:
            all_available_inboxes = list(current_inboxes)

        available = [
            e for e in all_available_inboxes
            if e not in current_inboxes and e not in underperforming
        ]
        replacements = available[:len(underperforming)]

        # Build the new inbox set and apply it
        new_inbox_set = [
            e for e in current_inboxes if e not in underperforming
        ] + replacements

        if new_inbox_set:
            self.client.set_campaign_accounts(campaign_id, new_inbox_set)

        result = {
            "campaign_id": campaign_id,
            "removed": underperforming,
            "added": replacements,
            "message": (
                f"Rotated {len(underperforming)} underperforming inbox(es). "
                f"Added {len(replacements)} replacement(s)."
            ),
        }
        print(f"  [ROTATE] {result['message']}")
        return result

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def generate_performance_report(
        self,
        campaign_ids: list[str] = None,
        period: str = "daily",
    ) -> dict:
        """Generate a performance report across one or more campaigns.

        Args:
            campaign_ids: List of campaign IDs to include. If None, reports
                          on all campaigns.
            period: 'daily' or 'weekly' — used for the report title.

        Returns:
            Dict containing per-campaign stats, aggregate totals, and a
            human-readable summary string.
        """
        if campaign_ids is None:
            campaigns = self.campaign_mgr.list_all()
            campaign_ids = []
            for c in campaigns:
                cid = c if isinstance(c, str) else c.get(
                    "id", c.get("campaign_id", "")
                )
                if cid:
                    campaign_ids.append(cid)

        report = {
            "generated_at": datetime.now().isoformat(),
            "period": period,
            "campaigns": [],
            "totals": {
                "sent": 0, "opened": 0, "replied": 0, "bounced": 0,
            },
        }

        for cid in campaign_ids:
            health = self.monitor_campaign_health(cid)
            report["campaigns"].append(health)

            report["totals"]["sent"] += health["sent"]
            report["totals"]["opened"] += health["opened"]
            report["totals"]["replied"] += health["replied"]
            report["totals"]["bounced"] += health["bounced"]

        totals = report["totals"]
        total_sent = totals["sent"]
        if total_sent > 0:
            totals["open_rate"] = round(totals["opened"] / total_sent * 100, 2)
            totals["reply_rate"] = round(totals["replied"] / total_sent * 100, 2)
            totals["bounce_rate"] = round(totals["bounced"] / total_sent * 100, 2)
        else:
            totals["open_rate"] = 0.0
            totals["reply_rate"] = 0.0
            totals["bounce_rate"] = 0.0

        report["summary"] = (
            f"{period.capitalize()} report — "
            f"{len(campaign_ids)} campaign(s), "
            f"{total_sent} sent, "
            f"{totals['open_rate']}% opens, "
            f"{totals['reply_rate']}% replies, "
            f"{totals['bounce_rate']}% bounces."
        )

        print(f"  [REPORT] {report['summary']}")
        return report

    # ------------------------------------------------------------------
    # Scaling
    # ------------------------------------------------------------------

    def scale_up(self, campaign_id: str, additional_leads_csv: str,
                 field_mapping: dict = None,
                 additional_inboxes: list[str] = None) -> dict:
        """Add more leads (and optionally more inboxes) to a running campaign.

        Args:
            campaign_id: The Instantly campaign ID.
            additional_leads_csv: Path to CSV with additional leads.
            field_mapping: Optional CSV column mapping.
            additional_inboxes: Optional list of extra inbox emails to assign.

        Returns:
            Dict with counts of leads and inboxes added.
        """
        leads = self.lead_mgr.import_from_csv(
            additional_leads_csv, field_mapping=field_mapping
        )
        if leads:
            self.campaign_mgr.add_leads(campaign_id, leads)

        if additional_inboxes:
            campaign = self.client.get_campaign(campaign_id)
            current = campaign.get("accounts", [])
            combined = list(set(current + additional_inboxes))
            self.client.set_campaign_accounts(campaign_id, combined)

        result = {
            "campaign_id": campaign_id,
            "leads_added": len(leads),
            "inboxes_added": len(additional_inboxes) if additional_inboxes else 0,
        }
        print(f"  [SCALE UP] Added {result['leads_added']} leads, "
              f"{result['inboxes_added']} inboxes to campaign {campaign_id}.")
        return result

    def scale_down(self, campaign_id: str,
                   remove_lead_emails: list[str] = None,
                   remove_inbox_emails: list[str] = None,
                   pause: bool = False) -> dict:
        """Remove leads and/or inboxes from a campaign, optionally pausing it.

        Args:
            campaign_id: The Instantly campaign ID.
            remove_lead_emails: List of lead emails to remove.
            remove_inbox_emails: List of inbox emails to unassign.
            pause: If True, also pause the campaign.

        Returns:
            Dict with counts of leads and inboxes removed plus pause status.
        """
        leads_removed = 0
        inboxes_removed = 0

        if remove_lead_emails:
            for email in remove_lead_emails:
                try:
                    self.client.delete_lead(campaign_id, email)
                    leads_removed += 1
                except Exception as e:
                    print(f"  Warning: could not remove lead {email}: {e}")

        if remove_inbox_emails:
            campaign = self.client.get_campaign(campaign_id)
            current = campaign.get("accounts", [])
            updated = [e for e in current if e not in remove_inbox_emails]
            if updated:
                self.client.set_campaign_accounts(campaign_id, updated)
                inboxes_removed = len(current) - len(updated)
            else:
                print("  Warning: cannot remove all inboxes — at least one required.")

        if pause:
            self.campaign_mgr.pause(campaign_id)

        result = {
            "campaign_id": campaign_id,
            "leads_removed": leads_removed,
            "inboxes_removed": inboxes_removed,
            "paused": pause,
        }
        print(f"  [SCALE DOWN] Removed {leads_removed} leads, "
              f"{inboxes_removed} inboxes from campaign {campaign_id}.")
        return result
