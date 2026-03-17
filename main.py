#!/usr/bin/env python3
"""Cold Email Automation System - CLI Interface.

Fully automates cold email campaigns using Instantly.ai.
Generates free inboxes, manages campaigns, handles deliverability.

Usage:
    python main.py setup
    python main.py inboxes checklist
    python main.py campaign create --template "SaaS Cold Outreach" --leads leads.csv
    python main.py dashboard
"""

import os
import sys
import csv
import yaml
import click
from pathlib import Path
from dotenv import load_dotenv

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

load_dotenv()

from instantly import InstantlyClient, CampaignManager, AccountManager, LeadManager
from inboxes.bulk_creator import BulkInboxCreator
from inboxes.dns_setup import DNSSetup
from inboxes.outlook_creator import OutlookInboxProvisioner
from inboxes.zoho_creator import ZohoInboxProvisioner
from templates.engine import TemplateEngine
from campaigns.automation import CampaignAutomation


def get_config() -> dict:
    config_path = Path("config.yaml")
    if config_path.exists():
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    return {}


def get_client() -> InstantlyClient:
    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        click.echo("Error: INSTANTLY_API_KEY not set. Run 'python main.py setup' first.")
        sys.exit(1)
    return InstantlyClient(api_key)


@click.group()
def cli():
    """Cold Email Automation System - Powered by Instantly.ai"""
    pass


# ============================================================
# SETUP
# ============================================================

@cli.command()
def setup():
    """Interactive setup wizard."""
    click.echo("\n=== Cold Email Automation Setup ===\n")

    # Check .env
    env_path = Path(".env")
    api_key = os.getenv("INSTANTLY_API_KEY")

    if not api_key:
        click.echo("No Instantly API key found.")
        api_key = click.prompt("Enter your Instantly API key")
        with open(env_path, "a") as f:
            f.write(f"\nINSTANTLY_API_KEY={api_key}\n")
        click.echo("API key saved to .env")
        os.environ["INSTANTLY_API_KEY"] = api_key

    # Test connection
    click.echo("\nTesting Instantly API connection...")
    try:
        client = InstantlyClient(api_key)
        accounts = client.list_accounts()
        if isinstance(accounts, list):
            click.echo(f"Connected! {len(accounts)} email account(s) found.")
        else:
            click.echo("Connected to Instantly API.")
    except Exception as e:
        click.echo(f"Connection failed: {e}")
        return

    # Show status
    click.echo("\nSetup complete! Next steps:")
    click.echo("  1. Add inboxes:     python main.py inboxes checklist")
    click.echo("  2. Import leads:    python main.py leads import --file leads.csv")
    click.echo("  3. Create campaign: python main.py campaign create")
    click.echo("  4. View dashboard:  python main.py dashboard")


# ============================================================
# INBOXES
# ============================================================

@cli.group()
def inboxes():
    """Manage email sending inboxes."""
    pass


@inboxes.command("checklist")
@click.option("--strategy", default="outlook_free",
              type=click.Choice(["outlook_free", "zoho_free", "custom_domain"]),
              help="Inbox creation strategy")
@click.option("--count", default=5, help="Number of inboxes to plan")
@click.option("--domain", default=None, help="Domain for zoho/custom strategy")
def inboxes_checklist(strategy, count, domain):
    """Print step-by-step guide to creating free inboxes."""
    creator = BulkInboxCreator(strategy=strategy, domain=domain or "")
    plan = creator.generate_inbox_plan(count=count, domain=domain)
    creator.print_creation_checklist(plan)
    creator.export_to_csv(plan)
    click.echo("\nInbox plan exported to inboxes/inbox_plan.csv")
    click.echo("Fill in passwords after creating accounts, then run:")
    click.echo("  python main.py inboxes bulk-add --file inboxes/inbox_plan.csv")


@inboxes.command("generate")
@click.option("--strategy", default="outlook_free")
@click.option("--count", default=10)
@click.option("--domain", default=None)
def inboxes_generate(strategy, count, domain):
    """Generate inbox name suggestions."""
    creator = BulkInboxCreator(strategy=strategy, domain=domain or "")
    plan = creator.generate_inbox_plan(count=count, domain=domain)
    click.echo("\nSuggested inboxes:")
    for i, inbox in enumerate(plan, 1):
        click.echo(f"  {i}. {inbox['email']}")


@inboxes.command("add")
@click.option("--email", required=True, help="Email address")
@click.option("--password", required=True, help="Password or app password")
@click.option("--name", required=True, help="Sender first name")
@click.option("--provider", default="outlook",
              type=click.Choice(["outlook", "gmail", "zoho", "yahoo"]))
@click.option("--daily-limit", default=30)
def inboxes_add(email, password, name, provider, daily_limit):
    """Add a single inbox to Instantly."""
    client = get_client()
    config = get_config()
    manager = AccountManager(client, config)
    try:
        result = manager.add_inbox(
            email=email, password=password, first_name=name,
            provider=provider, daily_limit=daily_limit,
        )
        click.echo(f"Inbox added: {email}")
        click.echo(f"Warmup: enabled (will take ~14 days)")
    except Exception as e:
        click.echo(f"Error: {e}")


@inboxes.command("bulk-add")
@click.option("--file", "filepath", required=True,
              help="CSV file with columns: email, password, first_name, provider")
def inboxes_bulk_add(filepath):
    """Add multiple inboxes from a CSV file."""
    client = get_client()
    config = get_config()
    manager = AccountManager(client, config)

    inboxes_list = []
    with open(filepath, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if row.get("password") and row["password"] != "FILL_IN":
                inboxes_list.append({
                    "email": row["email"],
                    "password": row["password"],
                    "first_name": row.get("first_name", ""),
                    "provider": row.get("provider", "outlook"),
                })

    if not inboxes_list:
        click.echo("No valid inboxes found. Make sure passwords are filled in.")
        return

    click.echo(f"Adding {len(inboxes_list)} inbox(es) to Instantly...")
    results = manager.add_bulk_inboxes(inboxes_list)

    added = sum(1 for r in results if r["status"] == "added")
    failed = sum(1 for r in results if r["status"] == "error")
    click.echo(f"\nResults: {added} added, {failed} failed")


@inboxes.command("list")
def inboxes_list():
    """List all connected inboxes."""
    client = get_client()
    accounts = client.list_accounts()

    if not accounts:
        click.echo("No inboxes connected. Run: python main.py inboxes checklist")
        return

    click.echo(f"\nConnected Inboxes ({len(accounts)}):")
    for acc in accounts:
        email = acc if isinstance(acc, str) else acc.get("email", "unknown")
        click.echo(f"  - {email}")


@inboxes.command("warmup-all")
def inboxes_warmup_all():
    """Enable warmup on all inboxes."""
    client = get_client()
    config = get_config()
    manager = AccountManager(client, config)
    results = manager.bulk_enable_warmup()
    click.echo(f"\nWarmup enabled for {len(results)} account(s)")


@inboxes.command("status")
def inboxes_status():
    """Show warmup status for all inboxes."""
    client = get_client()
    accounts = client.list_accounts()

    if not accounts:
        click.echo("No inboxes connected.")
        return

    click.echo("\nInbox Warmup Status:")
    for acc in accounts:
        email = acc if isinstance(acc, str) else acc.get("email", "unknown")
        try:
            status = client.get_warmup_status(email)
            warmup = status.get("status", "unknown") if isinstance(status, dict) else "unknown"
            click.echo(f"  {email}: {warmup}")
        except Exception:
            click.echo(f"  {email}: unable to fetch status")


# ============================================================
# CAMPAIGNS
# ============================================================

@cli.group()
def campaign():
    """Manage email campaigns."""
    pass


@campaign.command("create")
@click.option("--template", "template_name", required=True,
              help="Template name from library.yaml")
@click.option("--leads", "leads_csv", required=True,
              help="Path to leads CSV file")
@click.option("--name", default=None, help="Campaign name override")
def campaign_create(template_name, leads_csv, name):
    """Create a campaign from a template and leads CSV."""
    client = get_client()
    config = get_config()
    automation = CampaignAutomation(client, config)

    try:
        result = automation.create_from_template(
            template_name=template_name,
            leads_csv=leads_csv,
            campaign_name=name,
        )
        click.echo(f"\nCampaign ready! ID: {result['campaign_id']}")
        click.echo(f"Launch it: python main.py campaign launch --id {result['campaign_id']}")
    except Exception as e:
        click.echo(f"Error: {e}")


@campaign.command("list")
def campaign_list():
    """List all campaigns."""
    client = get_client()
    campaigns_mgr = CampaignManager(client)
    campaigns = campaigns_mgr.list_all()

    if not campaigns:
        click.echo("No campaigns found.")
        return

    click.echo(f"\nCampaigns ({len(campaigns)}):")
    for c in campaigns:
        if isinstance(c, dict):
            cid = c.get("id", c.get("campaign_id", "?"))
            name = c.get("name", "Unnamed")
            status = c.get("status", "unknown")
            click.echo(f"  [{status}] {name} (ID: {cid})")
        else:
            click.echo(f"  {c}")


@campaign.command("launch")
@click.option("--id", "campaign_id", required=True, help="Campaign ID")
def campaign_launch(campaign_id):
    """Launch a campaign."""
    client = get_client()
    campaigns_mgr = CampaignManager(client)
    campaigns_mgr.launch(campaign_id)
    click.echo(f"Campaign {campaign_id} launched!")


@campaign.command("pause")
@click.option("--id", "campaign_id", required=True, help="Campaign ID")
def campaign_pause(campaign_id):
    """Pause a campaign."""
    client = get_client()
    campaigns_mgr = CampaignManager(client)
    campaigns_mgr.pause(campaign_id)
    click.echo(f"Campaign {campaign_id} paused.")


@campaign.command("stats")
@click.option("--id", "campaign_id", required=True, help="Campaign ID")
def campaign_stats(campaign_id):
    """Show campaign analytics."""
    client = get_client()
    campaigns_mgr = CampaignManager(client)
    stats = campaigns_mgr.get_stats(campaign_id)

    click.echo(f"\nCampaign Stats ({campaign_id}):")
    click.echo(f"  Sent:     {stats.get('sent', 0)}")
    click.echo(f"  Opened:   {stats.get('opened', 0)} ({stats.get('open_rate', '0%')})")
    click.echo(f"  Replied:  {stats.get('replied', 0)} ({stats.get('reply_rate', '0%')})")
    click.echo(f"  Bounced:  {stats.get('bounced', 0)} ({stats.get('bounce_rate', '0%')})")


@campaign.command("add-leads")
@click.option("--id", "campaign_id", required=True, help="Campaign ID")
@click.option("--file", "leads_csv", required=True, help="Leads CSV file")
def campaign_add_leads(campaign_id, leads_csv):
    """Add more leads to an existing campaign."""
    client = get_client()
    config = get_config()
    automation = CampaignAutomation(client, config)
    result = automation.scale_campaign(campaign_id, leads_csv)
    click.echo(f"Added {result['added']} leads to campaign {campaign_id}")


@campaign.command("health")
@click.option("--id", "campaign_id", required=True, help="Campaign ID")
def campaign_health(campaign_id):
    """Check campaign health and auto-pause if needed."""
    client = get_client()
    config = get_config()
    automation = CampaignAutomation(client, config)
    health = automation.auto_pause_if_unhealthy(campaign_id)

    click.echo(f"\nCampaign Health: {health['health']}")
    if health.get("issues"):
        for issue in health["issues"]:
            click.echo(f"  ! {issue}")
    if health.get("action"):
        click.echo(f"  Action: {health['action']}")


@campaign.command("report")
@click.option("--id", "campaign_id", default=None, help="Campaign ID (all if omitted)")
def campaign_report(campaign_id):
    """Generate performance report."""
    client = get_client()
    config = get_config()
    automation = CampaignAutomation(client, config)
    report = automation.generate_report(campaign_id)

    click.echo("\n=== Campaign Performance Report ===\n")
    for c in report["campaigns"]:
        if "error" in c:
            click.echo(f"  {c['id']}: Error - {c['error']}")
            continue
        stats = c.get("stats", {})
        click.echo(f"  Campaign: {c['id']}")
        click.echo(f"    Health: {c['health']}")
        click.echo(f"    Sent: {stats.get('sent', 0)} | Opens: {stats.get('open_rate', '0%')} | Replies: {stats.get('reply_rate', '0%')}")
        if c.get("issues"):
            for issue in c["issues"]:
                click.echo(f"    ! {issue}")
        click.echo()

    totals = report["totals"]
    click.echo(f"  TOTALS: {totals['sent']} sent, {totals['opened']} opened, "
               f"{totals['replied']} replied, {totals['bounced']} bounced")


# ============================================================
# LEADS
# ============================================================

@cli.group()
def leads():
    """Manage leads."""
    pass


@leads.command("import")
@click.option("--file", "filepath", required=True, help="CSV file path")
@click.option("--campaign-id", default=None, help="Add directly to campaign")
def leads_import(filepath, campaign_id):
    """Import leads from a CSV file."""
    client = get_client()
    config = get_config()
    lead_mgr = LeadManager(client, config)
    result = lead_mgr.import_from_csv(filepath, campaign_id=campaign_id)
    click.echo(f"\nImported {len(result)} valid leads")
    if campaign_id:
        click.echo(f"Added to campaign: {campaign_id}")


@leads.command("sample")
@click.option("--output", default="leads/sample_leads.csv", help="Output file path")
def leads_sample(output):
    """Generate a sample leads CSV file."""
    client = get_client()
    lead_mgr = LeadManager(client)
    lead_mgr.generate_sample_csv(output)
    click.echo(f"Sample CSV created: {output}")


# ============================================================
# TEMPLATES
# ============================================================

@cli.group()
def templates():
    """Manage email templates."""
    pass


@templates.command("list")
def templates_list():
    """List available email templates."""
    lib_path = Path("templates/library.yaml")
    if not lib_path.exists():
        click.echo("No template library found.")
        return

    with open(lib_path) as f:
        library = yaml.safe_load(f)

    click.echo("\nAvailable Templates:")
    for seq in library.get("sequences", []):
        steps = len(seq.get("steps", []))
        click.echo(f"  - {seq['name']} ({steps} steps)")
        click.echo(f"    {seq.get('description', '')}")


@templates.command("preview")
@click.option("--name", required=True, help="Template name")
def templates_preview(name):
    """Preview a template with sample data."""
    lib_path = Path("templates/library.yaml")
    if not lib_path.exists():
        click.echo("No template library found.")
        return

    with open(lib_path) as f:
        library = yaml.safe_load(f)

    template = None
    for seq in library.get("sequences", []):
        if seq["name"].lower() == name.lower():
            template = seq
            break

    if not template:
        click.echo(f"Template '{name}' not found.")
        return

    from utils.spintax import resolve_spintax

    sample = {
        "first_name": "Alex",
        "company": "TechCorp",
        "title": "VP of Sales",
        "website": "techcorp.com",
        "sender_name": "Your Name",
    }

    click.echo(f"\n=== Preview: {template['name']} ===\n")
    for i, step in enumerate(template["steps"], 1):
        subject = resolve_spintax(step["subject"])
        body = resolve_spintax(step["body"])
        for key, val in sample.items():
            subject = subject.replace("{{" + key + "}}", val)
            body = body.replace("{{" + key + "}}", val)

        delay = step.get("delay_days", 0)
        click.echo(f"--- Step {i} (delay: {delay} days) ---")
        click.echo(f"Subject: {subject}")
        click.echo(body)


# ============================================================
# DNS
# ============================================================

@cli.group()
def dns():
    """DNS and deliverability setup."""
    pass


@dns.command("generate")
@click.option("--domain", required=True, help="Your sending domain")
@click.option("--provider", default="zoho",
              type=click.Choice(["zoho", "gmail", "outlook", "custom"]))
def dns_generate(domain, provider):
    """Generate DNS records for a domain."""
    setup = DNSSetup(domain)
    records = setup.generate_all_records(provider=provider)

    click.echo(f"\nDNS Records for {domain} ({provider}):\n")
    for rec in records:
        rtype = rec.get("type", "?")
        name = rec.get("name", "?")
        value = rec.get("value", "?")
        click.echo(f"  {rtype:6s}  {name:30s}  {value}")
        if rec.get("priority"):
            click.echo(f"         Priority: {rec['priority']}")
        click.echo()


@dns.command("verify")
@click.option("--domain", required=True, help="Domain to verify")
def dns_verify(domain):
    """Verify DNS setup for a domain."""
    setup = DNSSetup(domain)
    try:
        results = setup.verify_all()
    except RuntimeError as e:
        click.echo(f"Error: {e}")
        return

    click.echo(f"\nDNS Verification for {domain}:\n")
    for key, check in results.items():
        if key in ("domain",):
            continue
        status = check.get("status", "unknown")
        icon = "PASS" if status == "pass" else "FAIL" if status == "fail" else "SKIP"
        click.echo(f"  [{icon}] {key}")
        if check.get("values"):
            for v in check["values"]:
                click.echo(f"         {v}")
        if check.get("error"):
            click.echo(f"         Error: {check['error']}")


@dns.command("checklist")
@click.option("--domain", required=True, help="Your sending domain")
@click.option("--provider", default="zoho")
def dns_checklist(domain, provider):
    """Print DNS setup checklist."""
    setup = DNSSetup(domain)
    setup.print_checklist(provider=provider)


@dns.command("cloudflare-setup")
@click.option("--domain", required=True, help="Domain in Cloudflare")
@click.option("--provider", default="zoho")
def dns_cloudflare(domain, provider):
    """Auto-add DNS records via Cloudflare API."""
    cf_token = os.getenv("CLOUDFLARE_API_TOKEN")
    if not cf_token:
        click.echo("Error: CLOUDFLARE_API_TOKEN not set in .env")
        return

    setup = DNSSetup(domain)
    click.echo(f"Adding DNS records for {domain} via Cloudflare...")
    try:
        results = setup.add_via_cloudflare(api_token=cf_token, provider=provider)
        for r in results:
            status = r.get("status", "?")
            name = r.get("name", r.get("record", "?"))
            click.echo(f"  [{status}] {name}")
    except Exception as e:
        click.echo(f"Error: {e}")


# ============================================================
# DASHBOARD
# ============================================================

@cli.command()
def dashboard():
    """Show overview dashboard."""
    client = get_client()
    config = get_config()

    click.echo("\n" + "=" * 50)
    click.echo("  COLD EMAIL AUTOMATION DASHBOARD")
    click.echo("=" * 50)

    # Accounts
    try:
        accounts = client.list_accounts()
        acc_count = len(accounts) if isinstance(accounts, list) else 0
        click.echo(f"\n  Inboxes Connected:  {acc_count}")
    except Exception:
        click.echo(f"\n  Inboxes Connected:  (unable to fetch)")

    # Campaigns
    try:
        campaigns = client.list_campaigns()
        camp_count = len(campaigns) if isinstance(campaigns, list) else 0
        click.echo(f"  Active Campaigns:   {camp_count}")
    except Exception:
        click.echo(f"  Active Campaigns:   (unable to fetch)")

    # Quick actions
    click.echo(f"\n  Quick Actions:")
    click.echo(f"    python main.py inboxes checklist    # Get free inboxes")
    click.echo(f"    python main.py inboxes list         # List inboxes")
    click.echo(f"    python main.py campaign create      # New campaign")
    click.echo(f"    python main.py campaign report      # Performance report")
    click.echo(f"    python main.py templates list       # Browse templates")
    click.echo()


if __name__ == "__main__":
    cli()
