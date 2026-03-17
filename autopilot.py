#!/usr/bin/env python3
"""Fully automated campaign pipeline -- scrape, template, create, launch.

Run it and walk away:

    python autopilot.py --niche "dentists" --location "Texas" --source apollo
    python autopilot.py --niche "HVAC companies" --location "Florida" --source google_maps
    python autopilot.py --niche "roofing contractors" --location "California"
    python autopilot.py --batch campaigns.yaml

Given a niche and location this script will:
  1. Scrape leads (Apollo or Google Maps)
  2. Pick the best email template for the niche
  3. Create a campaign in Instantly
  4. Assign all available inboxes
  5. Add the leads
  6. Launch the campaign
  7. Print a summary
"""

import os
import sys
import csv
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from dotenv import load_dotenv

load_dotenv()

import click
import yaml

from instantly import InstantlyClient, CampaignManager, AccountManager, LeadManager
from leads.scraper import LeadScraper
from campaigns.automation import CampaignAutomation
from templates.engine import TemplateEngine
from utils.spintax import resolve_spintax

# ======================================================================
# Constants
# ======================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
LEADS_DIR = PROJECT_ROOT / "leads"
TEMPLATE_LIBRARY = PROJECT_ROOT / "templates" / "library.yaml"
SEPARATOR = "=" * 64
THIN_SEP = "-" * 64

# Niches that map to the "Agency Services" template (user is pitching
# services TO these businesses, not selling SaaS).
SERVICE_BUSINESS_KEYWORDS = [
    "dental", "dentist",
    "hvac", "heating", "cooling", "air condition",
    "roofing", "roofer",
    "plumbing", "plumber",
    "insurance",
    "real estate", "realtor",
    "landscap",
    "cleaning",
    "auto repair", "mechanic",
    "chiropractic", "chiropractor",
    "veterinar", "vet clinic",
    "salon", "barber",
    "gym", "fitness",
    "restaurant",
    "accounting", "accountant", "cpa",
    "law firm", "lawyer", "attorney",
    "contractor",
    "electrician", "electrical",
    "pest control",
    "moving",
    "photography", "photographer",
    "clinic", "medical",
    "therapy", "therapist",
]


# ======================================================================
# Template auto-selection
# ======================================================================

def pick_template(niche: str) -> str:
    """Choose the best email template name for a given business niche.

    Rules (evaluated in order):
      1. Contains "recruit" or "hire"     -> "Recruiting"
      2. Contains "partner" or "collab"   -> "Partnership"
      3. Contains "consult"               -> "Consulting"
      4. Service / local businesses        -> "Agency Services"
      5. Default                           -> "SaaS Cold Outreach"
    """
    lower = niche.lower()

    if "recruit" in lower or "hire" in lower or "hiring" in lower:
        return "Recruiting"

    if "partner" in lower or "collab" in lower:
        return "Partnership"

    if "consult" in lower:
        return "Consulting"

    for keyword in SERVICE_BUSINESS_KEYWORDS:
        if keyword in lower:
            return "Agency Services"

    return "SaaS Cold Outreach"


# ======================================================================
# Lead CSV helpers
# ======================================================================

def _normalize_leads(raw_leads: list[dict], source: str) -> list[dict]:
    """Normalize raw scraped leads into the Instantly-compatible format.

    Ensures every lead has at least: email, first_name, company.
    """
    normalized: list[dict] = []
    seen_emails: set[str] = set()

    for lead in raw_leads:
        email = (lead.get("email") or "").strip().lower()
        if not email or email in seen_emails:
            continue
        seen_emails.add(email)

        entry = {
            "email": email,
            "first_name": lead.get("first_name") or "",
            "last_name": lead.get("last_name") or "",
            "company": lead.get("company") or lead.get("business_name") or "",
            "title": lead.get("title") or "",
            "website": lead.get("website") or "",
        }

        # Optional fields
        for key in ("linkedin", "phone", "address"):
            if lead.get(key):
                entry[key] = lead[key]

        normalized.append(entry)

    return normalized


def save_leads_csv(leads: list[dict], niche: str, location: str) -> Path:
    """Save leads to a timestamped CSV inside the leads/ directory.

    Returns the Path to the written file.
    """
    LEADS_DIR.mkdir(parents=True, exist_ok=True)

    slug_niche = niche.lower().replace(" ", "_")
    slug_location = location.lower().replace(" ", "_")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{slug_niche}_{slug_location}_{timestamp}.csv"
    csv_path = LEADS_DIR / filename

    fieldnames = [
        "email", "first_name", "last_name", "company",
        "title", "website", "linkedin", "phone", "address",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(leads)

    return csv_path


# ======================================================================
# Core pipeline
# ======================================================================

def run_pipeline(
    niche: str,
    location: str,
    source: str = "apollo",
    limit: int = 100,
    template_override: str | None = None,
    dry_run: bool = False,
    auto_launch: bool = True,
) -> dict:
    """Execute the full autopilot pipeline for one niche/location combo.

    Returns a summary dict with campaign details or error info.
    """
    summary: dict = {
        "niche": niche,
        "location": location,
        "source": source,
        "status": "pending",
    }

    print(f"\n{SEPARATOR}")
    print(f"  AUTOPILOT: {niche} in {location}")
    print(f"  Source: {source} | Limit: {limit}")
    print(SEPARATOR)

    # ------------------------------------------------------------------
    # Step 1 -- Scrape leads
    # ------------------------------------------------------------------
    print(f"\n[1/6] Scraping leads from {source}...")

    try:
        scraper = LeadScraper()
        if source in ("apollo",):
            raw_leads = scraper.scrape_apollo(niche, location, limit=limit)
        elif source in ("google_maps", "googlemaps", "gmaps"):
            query = f"{niche} in {location}"
            raw_leads = scraper.scrape_google_maps(query, limit=limit)
        else:
            raise ValueError(f"Unknown source: {source!r}")
    except Exception as exc:
        print(f"  ERROR scraping leads: {exc}")
        summary["status"] = "failed"
        summary["error"] = f"Scraping failed: {exc}"
        return summary

    # Enrich leads that are missing emails (website scraping)
    print(f"  Raw leads scraped: {len(raw_leads)}")
    raw_leads = scraper.enrich_leads(raw_leads)

    leads = _normalize_leads(raw_leads, source)
    print(f"  Leads with valid email: {len(leads)}")

    if not leads:
        print("  ERROR: No leads with email addresses found.")
        print("  Try a different niche, location, or source.")
        summary["status"] = "failed"
        summary["error"] = "No leads with valid emails found"
        return summary

    # Save to CSV
    csv_path = save_leads_csv(leads, niche, location)
    print(f"  Saved to: {csv_path}")
    summary["leads_count"] = len(leads)
    summary["leads_csv"] = str(csv_path)

    # ------------------------------------------------------------------
    # Step 2 -- Pick template
    # ------------------------------------------------------------------
    template_name = template_override or pick_template(niche)
    print(f"\n[2/6] Template selected: {template_name}")
    summary["template"] = template_name

    # Validate template exists in the library
    if not TEMPLATE_LIBRARY.exists():
        print(f"  ERROR: Template library not found at {TEMPLATE_LIBRARY}")
        summary["status"] = "failed"
        summary["error"] = "Template library missing"
        return summary

    try:
        engine = TemplateEngine(str(TEMPLATE_LIBRARY))
    except Exception as exc:
        print(f"  ERROR loading template library: {exc}")
        summary["status"] = "failed"
        summary["error"] = f"Template load failed: {exc}"
        return summary

    if template_name not in engine.sequences:
        available = engine.list_sequences()
        print(f"  ERROR: Template '{template_name}' not found.")
        print(f"  Available: {', '.join(available)}")
        summary["status"] = "failed"
        summary["error"] = f"Template '{template_name}' not found"
        return summary

    seq_info = engine.sequences[template_name]
    step_count = len(seq_info.get("steps", []))
    print(f"  Description: {seq_info.get('description', 'N/A')}")
    print(f"  Sequence steps: {step_count}")

    # ------------------------------------------------------------------
    # Step 3 -- Connect to Instantly & get inboxes
    # ------------------------------------------------------------------
    print(f"\n[3/6] Connecting to Instantly...")

    api_key = os.getenv("INSTANTLY_API_KEY")
    if not api_key:
        print("  ERROR: INSTANTLY_API_KEY not set in environment or .env")
        summary["status"] = "failed"
        summary["error"] = "INSTANTLY_API_KEY missing"
        return summary

    try:
        client = InstantlyClient(api_key)
        account_mgr = AccountManager(client)
        accounts = account_mgr.list_all()
    except Exception as exc:
        print(f"  ERROR connecting to Instantly: {exc}")
        summary["status"] = "failed"
        summary["error"] = f"Instantly connection failed: {exc}"
        return summary

    inbox_emails = []
    for acc in accounts:
        email = acc if isinstance(acc, str) else acc.get("email", "")
        if email:
            inbox_emails.append(email)

    if not inbox_emails:
        print("  ERROR: No sending accounts found in Instantly.")
        print("  Add inboxes first: python main.py inboxes checklist")
        summary["status"] = "failed"
        summary["error"] = "No sending accounts available"
        return summary

    print(f"  Inboxes available: {len(inbox_emails)}")
    summary["inbox_count"] = len(inbox_emails)

    # ------------------------------------------------------------------
    # Dry run -- stop here
    # ------------------------------------------------------------------
    if dry_run:
        print(f"\n{'=' * 64}")
        print("  DRY RUN -- no campaign created")
        print(f"{'=' * 64}")
        print(f"  Niche:      {niche}")
        print(f"  Location:   {location}")
        print(f"  Source:      {source}")
        print(f"  Leads:      {len(leads)}")
        print(f"  Template:   {template_name} ({step_count} steps)")
        print(f"  Inboxes:    {len(inbox_emails)}")
        print(f"  Leads CSV:  {csv_path}")
        print(f"  Auto-launch: {auto_launch}")
        summary["status"] = "dry_run"
        return summary

    # ------------------------------------------------------------------
    # Step 4 -- Create campaign
    # ------------------------------------------------------------------
    campaign_name = (
        f"{template_name} - {niche.title()} - {location.title()} "
        f"({len(leads)} leads)"
    )
    print(f"\n[4/6] Creating campaign: {campaign_name}")

    try:
        config = _load_config()
        automation = CampaignAutomation(client, config,
                                        template_library_path=str(TEMPLATE_LIBRARY))
        result = automation.create_campaign_from_template(
            template_name=template_name,
            leads_csv=str(csv_path),
            inbox_emails=inbox_emails,
            campaign_name=campaign_name,
        )
    except Exception as exc:
        print(f"  ERROR creating campaign: {exc}")
        summary["status"] = "failed"
        summary["error"] = f"Campaign creation failed: {exc}"
        return summary

    campaign_id = result.get("campaign_id")
    summary["campaign_id"] = campaign_id
    summary["campaign_name"] = campaign_name
    print(f"  Campaign ID: {campaign_id}")

    # ------------------------------------------------------------------
    # Step 5 -- Launch campaign
    # ------------------------------------------------------------------
    if auto_launch:
        print(f"\n[5/6] Launching campaign...")
        try:
            campaign_mgr = CampaignManager(client, config)
            campaign_mgr.launch(campaign_id)
            summary["launched"] = True
            print("  Campaign launched successfully.")
        except Exception as exc:
            print(f"  WARNING: Could not auto-launch: {exc}")
            print("  Launch manually: python main.py campaign launch "
                  f"--id {campaign_id}")
            summary["launched"] = False
            summary["launch_error"] = str(exc)
    else:
        print(f"\n[5/6] Skipping auto-launch (--no-auto-launch)")
        print(f"  Launch manually: python main.py campaign launch "
              f"--id {campaign_id}")
        summary["launched"] = False

    # ------------------------------------------------------------------
    # Step 6 -- Summary
    # ------------------------------------------------------------------
    print(f"\n[6/6] Campaign summary")
    print(SEPARATOR)
    print(f"  Campaign:   {campaign_name}")
    print(f"  Campaign ID: {campaign_id}")
    print(f"  Template:   {template_name} ({step_count} steps)")
    print(f"  Leads:      {len(leads)}")
    print(f"  Inboxes:    {len(inbox_emails)}")
    print(f"  Leads CSV:  {csv_path}")
    print(f"  Status:     {'LAUNCHED' if summary.get('launched') else 'CREATED (not launched)'}")

    # Estimated send capacity
    daily_capacity = len(inbox_emails) * 30  # ~30 emails/inbox/day
    days_to_send = (len(leads) // daily_capacity) + 1 if daily_capacity else 0
    print(f"\n  Estimated daily capacity: ~{daily_capacity} emails/day")
    print(f"  Estimated days to reach all leads: ~{days_to_send}")

    print(f"\n  Next steps:")
    if not summary.get("launched"):
        print(f"    1. Launch:   python main.py campaign launch --id {campaign_id}")
        print(f"    2. Monitor:  python main.py campaign health --id {campaign_id}")
        print(f"    3. Report:   python main.py campaign report --id {campaign_id}")
    else:
        print(f"    1. Monitor:  python main.py campaign health --id {campaign_id}")
        print(f"    2. Report:   python main.py campaign report --id {campaign_id}")
        print(f"    3. Stats:    python main.py campaign stats --id {campaign_id}")
    print(SEPARATOR)

    summary["status"] = "success"
    return summary


# ======================================================================
# Batch mode
# ======================================================================

def run_batch(batch_file: str, source: str, template_override: str | None,
              dry_run: bool, auto_launch: bool) -> list[dict]:
    """Run multiple campaigns from a YAML batch file.

    Expected YAML format::

        campaigns:
          - niche: "dentists"
            location: "Texas"
            limit: 200
          - niche: "HVAC companies"
            location: "Florida"
            limit: 150
            source: "google_maps"
            template: "Agency Services"
    """
    path = Path(batch_file)
    if not path.exists():
        raise click.ClickException(f"Batch file not found: {batch_file}")

    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict) or "campaigns" not in data:
        raise click.ClickException(
            "Batch YAML must have a top-level 'campaigns' key with a list."
        )

    entries = data["campaigns"]
    if not entries:
        raise click.ClickException("No campaigns defined in batch file.")

    print(f"\n{SEPARATOR}")
    print(f"  BATCH MODE: {len(entries)} campaign(s) from {batch_file}")
    print(SEPARATOR)

    results: list[dict] = []

    for i, entry in enumerate(entries, 1):
        niche = entry.get("niche")
        location = entry.get("location")

        if not niche or not location:
            print(f"\n  [SKIP] Entry {i}: missing niche or location")
            results.append({
                "entry": i,
                "status": "skipped",
                "error": "Missing niche or location",
            })
            continue

        entry_source = entry.get("source", source)
        entry_limit = entry.get("limit", 100)
        entry_template = entry.get("template", template_override)

        print(f"\n  [{i}/{len(entries)}] {niche} in {location}")

        result = run_pipeline(
            niche=niche,
            location=location,
            source=entry_source,
            limit=entry_limit,
            template_override=entry_template,
            dry_run=dry_run,
            auto_launch=auto_launch,
        )
        results.append(result)

    # Batch summary
    print(f"\n\n{SEPARATOR}")
    print(f"  BATCH SUMMARY")
    print(SEPARATOR)

    succeeded = [r for r in results if r.get("status") == "success"]
    failed = [r for r in results if r.get("status") == "failed"]
    skipped = [r for r in results if r.get("status") == "skipped"]
    dry_runs = [r for r in results if r.get("status") == "dry_run"]

    print(f"  Total:     {len(results)}")
    print(f"  Succeeded: {len(succeeded)}")
    print(f"  Failed:    {len(failed)}")
    print(f"  Skipped:   {len(skipped)}")
    if dry_runs:
        print(f"  Dry runs:  {len(dry_runs)}")

    if succeeded:
        total_leads = sum(r.get("leads_count", 0) for r in succeeded)
        print(f"\n  Total leads across campaigns: {total_leads}")
        print(f"\n  Campaign IDs:")
        for r in succeeded:
            print(f"    - {r.get('campaign_id')}: "
                  f"{r.get('niche')} / {r.get('location')} "
                  f"({r.get('leads_count', 0)} leads)")

    if failed:
        print(f"\n  Failed campaigns:")
        for r in failed:
            print(f"    - {r.get('niche', '?')} / {r.get('location', '?')}: "
                  f"{r.get('error', 'unknown error')}")

    print(SEPARATOR)
    return results


# ======================================================================
# Config loader
# ======================================================================

def _load_config() -> dict:
    """Load config.yaml if it exists, otherwise return empty dict."""
    config_path = PROJECT_ROOT / "config.yaml"
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    return {}


# ======================================================================
# CLI
# ======================================================================

@click.command()
@click.option(
    "--niche", type=str, default=None,
    help="Business type to target (e.g. 'dentists', 'HVAC companies').",
)
@click.option(
    "--location", type=str, default=None,
    help="Geographic area (e.g. 'Texas', 'New York City').",
)
@click.option(
    "--source", type=click.Choice(["apollo", "google_maps"], case_sensitive=False),
    default="apollo", show_default=True,
    help="Lead source.",
)
@click.option(
    "--limit", type=int, default=100, show_default=True,
    help="Maximum number of leads to scrape.",
)
@click.option(
    "--template", "template_override", type=str, default=None,
    help="Template name override (default: auto-pick based on niche).",
)
@click.option(
    "--dry-run", is_flag=True, default=False,
    help="Show what would happen without creating a campaign.",
)
@click.option(
    "--auto-launch/--no-auto-launch", default=True, show_default=True,
    help="Auto-launch the campaign after creation.",
)
@click.option(
    "--batch", "batch_file", type=click.Path(), default=None,
    help="YAML file with multiple niche/location combos for batch mode.",
)
def main(niche, location, source, limit, template_override, dry_run,
         auto_launch, batch_file):
    """Fully automated cold email campaign pipeline.

    Scrapes leads, picks a template, creates and launches a campaign in
    Instantly -- completely hands-free.

    \b
    Single campaign:
        python autopilot.py --niche "dentists" --location "Texas"
        python autopilot.py --niche "HVAC companies" --location "Florida" --source google_maps

    \b
    Batch mode:
        python autopilot.py --batch campaigns.yaml

    \b
    Dry run (preview only):
        python autopilot.py --niche "roofing contractors" --location "California" --dry-run
    """
    print(f"\n{SEPARATOR}")
    print("  COLD EMAIL AUTOPILOT")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(SEPARATOR)

    # ------------------------------------------------------------------
    # Batch mode
    # ------------------------------------------------------------------
    if batch_file:
        results = run_batch(
            batch_file=batch_file,
            source=source,
            template_override=template_override,
            dry_run=dry_run,
            auto_launch=auto_launch,
        )
        failed = [r for r in results if r.get("status") == "failed"]
        if failed:
            sys.exit(1)
        return

    # ------------------------------------------------------------------
    # Single campaign mode -- require niche and location
    # ------------------------------------------------------------------
    if not niche:
        raise click.UsageError(
            "Missing --niche. Provide a niche or use --batch for batch mode.\n"
            "  Example: python autopilot.py --niche \"dentists\" --location \"Texas\""
        )
    if not location:
        raise click.UsageError(
            "Missing --location. Provide a location.\n"
            "  Example: python autopilot.py --niche \"dentists\" --location \"Texas\""
        )

    result = run_pipeline(
        niche=niche,
        location=location,
        source=source,
        limit=limit,
        template_override=template_override,
        dry_run=dry_run,
        auto_launch=auto_launch,
    )

    if result.get("status") == "failed":
        sys.exit(1)


if __name__ == "__main__":
    main()
