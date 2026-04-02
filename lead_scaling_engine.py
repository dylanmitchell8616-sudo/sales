#!/usr/bin/env python3
"""
Lead Scaling Engine — Unified Orchestrator
=============================================
Combines Instantly Evergreen + Supersearch (Perplexity) + Apify fallback
into one system that auto-scales your lead pipeline.

Priority order (cheapest first):
  1. Instantly Evergreen — auto-adds leads on a schedule (included in plan)
  2. Instantly Supersearch + Perplexity — AI-enriched lead search (credits)
  3. Apify Google Maps — fallback scraper (pay per result)

Usage:
    python lead_scaling_engine.py --setup                    # First-time setup
    python lead_scaling_engine.py --run --target 100         # Run full pipeline
    python lead_scaling_engine.py --run --target 200 --campaign-id ABC123
    python lead_scaling_engine.py --status                   # Check pipeline health
    python lead_scaling_engine.py --dry-run --target 50      # Preview mode
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
ENGINE_STATE_PATH = os.path.join(OUTPUT_DIR, "scaling_engine_state.json")
PROCESSED_LEADS_PATH = os.path.join(OUTPUT_DIR, "processed_leads.json")

# Import our modules
sys.path.insert(0, SCRIPT_DIR)

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

try:
    from instantly_evergreen import (
        create_evergreen_campaign, enable_evergreen_on_existing,
        list_campaigns, list_sending_accounts, show_status as show_evergreen_status,
        search_leads_supersearch, SCHEDULE_PRESETS, DEFAULT_SEARCH_FILTERS,
        api_request,
    )
    from instantly_supersearch import (
        supersearch, bulk_search, waterfall_enrich, export_leads_csv,
        NICHE_CONFIGS, TOP_METROS,
    )
    from apify_lead_fallback import (
        scrape_google_maps, enrich_with_contacts, format_for_instantly,
        upload_to_instantly, export_csv as export_apify_csv, NICHE_QUERIES,
    )
except ImportError as e:
    print(f"Error importing modules: {e}")
    print("Make sure instantly_evergreen.py, instantly_supersearch.py, and apify_lead_fallback.py exist.")
    sys.exit(1)


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def load_engine_state() -> dict:
    if os.path.exists(ENGINE_STATE_PATH):
        try:
            with open(ENGINE_STATE_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {
        "runs": [],
        "total_leads_sourced": 0,
        "source_breakdown": {"evergreen": 0, "supersearch": 0, "apify": 0},
        "last_run": None,
        "setup_complete": False,
    }


def save_engine_state(state: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(ENGINE_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def load_processed_leads() -> set:
    if os.path.exists(PROCESSED_LEADS_PATH):
        try:
            with open(PROCESSED_LEADS_PATH, "r") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return set(data.get("emails", []))
            return set(data)
        except (json.JSONDecodeError, IOError):
            pass
    return set()


def save_processed_leads(emails: set):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    existing = {}
    if os.path.exists(PROCESSED_LEADS_PATH):
        try:
            with open(PROCESSED_LEADS_PATH, "r") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, IOError):
            existing = {}

    if isinstance(existing, dict):
        all_emails = set(existing.get("emails", []))
        all_emails.update(emails)
        existing["emails"] = sorted(all_emails)
    else:
        existing = {"emails": sorted(emails), "domains": []}

    with open(PROCESSED_LEADS_PATH, "w") as f:
        json.dump(existing, f, indent=2)


def setup_wizard(instantly_key: str, apify_key: str, dry_run: bool = False):
    """Interactive setup for the scaling engine."""
    print("\n" + "=" * 60)
    print("  LEAD SCALING ENGINE — SETUP")
    print("=" * 60)

    state = load_engine_state()

    # Step 1: Verify Instantly connection
    print("\n[1/4] Verifying Instantly API connection...")
    campaigns = list_campaigns(instantly_key)

    # Step 2: Check sending accounts
    print("\n[2/4] Checking sending accounts...")
    accounts = list_sending_accounts(instantly_key)
    if accounts:
        print(f"  Found {len(accounts)} sending account(s):")
        for a in accounts:
            print(f"    - {a.get('email', a.get('id', '?'))}")
    else:
        print("  WARNING: No sending accounts found. Add accounts in Instantly first.")

    # Step 3: Verify Apify connection
    print("\n[3/4] Verifying Apify API connection...")
    if apify_key:
        resp = requests.get(f"https://api.apify.com/v2/users/me",
                            params={"token": apify_key}, timeout=10)
        if resp.status_code == 200:
            user_data = resp.json().get("data", {})
            print(f"  Apify connected: {user_data.get('username', 'OK')}")
            plan = user_data.get("plan", {})
            if plan:
                print(f"  Plan: {plan.get('id', '?')} | Credits: {plan.get('monthlyUsageCreditsUsd', '?')}")
        else:
            print(f"  Apify connection failed: {resp.status_code}")
    else:
        print("  No Apify key configured (fallback source unavailable)")

    # Step 4: Recommended configuration
    print("\n[4/4] Recommended scaling configuration:")
    print()
    print("  Source Priority (cheapest first):")
    print("  ┌─────────────────────────────────────────────────────────┐")
    print("  │ 1. Evergreen Enrichment  — FREE (included in plan)     │")
    print("  │    Auto-adds 15-30 leads/day to campaigns              │")
    print("  │                                                        │")
    print("  │ 2. Supersearch + Perplexity — LOW COST (credits)       │")
    print("  │    AI-enriched search of 300M+ contacts                │")
    print("  │                                                        │")
    print("  │ 3. Apify Google Maps — PAY PER USE (fallback)          │")
    print("  │    Scrape + enrich when Instantly sources run dry       │")
    print("  └─────────────────────────────────────────────────────────┘")
    print()
    print("  Recommended preset: 'balanced' (15 leads/day evergreen)")
    print("  Recommended niches: med_spa, dental, wellness")
    print("  Recommended locations: Top 10 US metros")

    state["setup_complete"] = True
    state["setup_date"] = datetime.now().isoformat()
    save_engine_state(state)

    print("\n  Setup complete! Run with: python lead_scaling_engine.py --run --target 100")


def run_pipeline(instantly_key: str, apify_key: str, target: int = 100,
                  campaign_id: str = None, niches: list = None,
                  locations: list = None, dry_run: bool = False):
    """
    Run the full lead scaling pipeline.
    Waterfall: Evergreen → Supersearch → Apify fallback.
    """
    print("\n" + "=" * 60)
    print(f"  LEAD SCALING ENGINE — TARGET: {target} LEADS")
    print("=" * 60)

    state = load_engine_state()
    existing_emails = load_processed_leads()
    all_new_leads = []
    source_counts = {"evergreen": 0, "supersearch": 0, "apify": 0}

    niches = niches or ["med_spa", "dental", "wellness"]
    locations = locations or TOP_METROS[:10]
    start_time = time.time()

    # ─── SOURCE 1: Instantly Supersearch (Perplexity-powered) ───────────
    print(f"\n{'─' * 50}")
    print(f"  SOURCE 1: Instantly Supersearch + Perplexity")
    print(f"{'─' * 50}")

    remaining = target - len(all_new_leads)
    if remaining > 0:
        supersearch_leads = bulk_search(
            instantly_key, niches, locations[:5],
            leads_per_combo=max(5, remaining // (len(niches) * min(5, len(locations)))),
            dry_run=dry_run,
        )

        # Dedup
        for lead in supersearch_leads:
            email = lead.get("email", "").lower()
            if email and email not in existing_emails:
                existing_emails.add(email)
                lead["_source"] = "supersearch"
                all_new_leads.append(lead)
                source_counts["supersearch"] += 1

        print(f"\n  Supersearch delivered: {source_counts['supersearch']} new leads")

    # ─── SOURCE 2: Apify Fallback (if still short) ──────────────────────
    remaining = target - len(all_new_leads)
    if remaining > 0 and apify_key:
        print(f"\n{'─' * 50}")
        print(f"  SOURCE 2: Apify Google Maps Fallback ({remaining} still needed)")
        print(f"{'─' * 50}")

        # Only use Apify for remaining deficit
        per_niche_location = max(5, remaining // (len(niches) * min(3, len(locations))))

        apify_businesses = []
        for niche in niches:
            if len(all_new_leads) >= target:
                break
            queries = NICHE_QUERIES.get(niche, [niche.replace("_", " ")])
            for location in locations[:3]:  # Limit Apify to 3 locations
                if len(all_new_leads) >= target:
                    break
                results = scrape_google_maps(apify_key, queries[:1], location,
                                              max_results=per_niche_location,
                                              dry_run=dry_run)
                apify_businesses.extend(results)

        # Enrich with contact info
        if apify_businesses and not dry_run:
            apify_businesses = enrich_with_contacts(apify_key, apify_businesses, dry_run=dry_run)

        # Dedup and convert
        for biz in apify_businesses:
            email = biz.get("email", "").lower()
            if email and email not in existing_emails:
                existing_emails.add(email)
                lead = {
                    "email": email,
                    "first_name": "",
                    "last_name": "",
                    "company_name": biz.get("business_name", ""),
                    "phone": biz.get("phone", ""),
                    "website": biz.get("website", ""),
                    "title": "",
                    "industry": biz.get("category", ""),
                    "city": biz.get("location", ""),
                    "_source": "apify",
                }
                all_new_leads.append(lead)
                source_counts["apify"] += 1

        print(f"\n  Apify delivered: {source_counts['apify']} new leads")
    elif remaining > 0 and not apify_key:
        print(f"\n  Skipping Apify fallback (no API key configured)")

    # ─── RESULTS ─────────────────────────────────────────────────────────
    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  PIPELINE COMPLETE")
    print(f"{'=' * 60}")
    print(f"\n  Target: {target} | Delivered: {len(all_new_leads)} | Time: {elapsed:.0f}s")
    print(f"\n  Source breakdown:")
    print(f"    Supersearch: {source_counts['supersearch']}")
    print(f"    Apify:       {source_counts['apify']}")
    print(f"    Total:       {len(all_new_leads)}")

    # Upload to campaign if specified
    if campaign_id and all_new_leads and not dry_run:
        print(f"\n  Uploading to campaign {campaign_id}...")
        # Format all leads for upload
        formatted_leads = []
        for lead in all_new_leads:
            formatted_leads.append({
                "email": lead.get("email", ""),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company_name": lead.get("company_name", lead.get("company", "")),
                "phone": lead.get("phone", ""),
                "website": lead.get("website", ""),
                "custom_variables": {
                    "title": lead.get("title", ""),
                    "industry": lead.get("industry", ""),
                    "city": lead.get("city", ""),
                    "source": lead.get("_source", "scaling_engine"),
                },
            })

        # Upload in batches
        batch_size = 50
        uploaded = 0
        for i in range(0, len(formatted_leads), batch_size):
            batch = formatted_leads[i:i + batch_size]
            result = api_request("POST", f"campaigns/{campaign_id}/leads",
                                  instantly_key, {"leads": batch})
            if "error" not in result:
                uploaded += len(batch)
            time.sleep(1)

        print(f"  Uploaded: {uploaded}/{len(formatted_leads)}")

    # Export CSV
    if all_new_leads:
        export_leads_csv(all_new_leads, f"scaling_engine_{datetime.now().strftime('%Y%m%d')}.csv")

    # Save dedup state
    if not dry_run:
        save_processed_leads(existing_emails)

    # Update engine state
    run_record = {
        "timestamp": datetime.now().isoformat(),
        "target": target,
        "delivered": len(all_new_leads),
        "sources": source_counts,
        "campaign_id": campaign_id,
        "elapsed_seconds": round(elapsed),
    }
    state["runs"].append(run_record)
    state["total_leads_sourced"] += len(all_new_leads)
    for src, count in source_counts.items():
        state["source_breakdown"][src] = state["source_breakdown"].get(src, 0) + count
    state["last_run"] = datetime.now().isoformat()
    save_engine_state(state)

    return all_new_leads


def show_status():
    """Show scaling engine health and stats."""
    state = load_engine_state()
    existing = load_processed_leads()

    print("\n" + "=" * 60)
    print("  LEAD SCALING ENGINE — STATUS")
    print("=" * 60)

    print(f"\n  Setup: {'Complete' if state.get('setup_complete') else 'Not run yet'}")
    print(f"  Last run: {state.get('last_run', 'never')}")
    print(f"  Total leads sourced: {state.get('total_leads_sourced', 0)}")
    print(f"  Unique emails in dedup tracker: {len(existing)}")

    breakdown = state.get("source_breakdown", {})
    if breakdown:
        print(f"\n  Source breakdown (all time):")
        for src, count in breakdown.items():
            pct = (count / max(1, state.get('total_leads_sourced', 1))) * 100
            print(f"    {src:>15}: {count:>5} ({pct:.0f}%)")

    runs = state.get("runs", [])
    if runs:
        print(f"\n  Recent runs:")
        for run in runs[-5:]:
            ts = run.get("timestamp", "?")[:16]
            delivered = run.get("delivered", 0)
            target = run.get("target", 0)
            elapsed = run.get("elapsed_seconds", 0)
            print(f"    {ts} | {delivered}/{target} leads | {elapsed}s")

    # Show evergreen status
    print()
    show_evergreen_status("")


def main():
    parser = argparse.ArgumentParser(description="Lead Scaling Engine — Unified Orchestrator")
    parser.add_argument("--setup", action="store_true", help="Run first-time setup wizard")
    parser.add_argument("--run", action="store_true", help="Run the scaling pipeline")
    parser.add_argument("--target", type=int, default=100, help="Target number of leads (default: 100)")
    parser.add_argument("--campaign-id", help="Instantly campaign ID to upload leads to")
    parser.add_argument("--niches", help="Comma-separated niches (default: med_spa,dental,wellness)")
    parser.add_argument("--locations", help="Comma-separated locations (default: top US metros)")
    parser.add_argument("--status", action="store_true", help="Show pipeline status and stats")
    parser.add_argument("--instantly-key", help="Instantly API key")
    parser.add_argument("--apify-key", help="Apify API key")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    config = load_config()
    instantly_key = args.instantly_key or config.get("instantly_api_key", "")
    apify_key = args.apify_key or config.get("apify_api_key", "")

    if not instantly_key:
        print("Error: No Instantly API key. Use --instantly-key or set in config.json")
        sys.exit(1)

    niches = [n.strip() for n in args.niches.split(",")] if args.niches else None
    locations = [l.strip() for l in args.locations.split(",")] if args.locations else None

    if args.status:
        show_status()
        return

    if args.setup:
        setup_wizard(instantly_key, apify_key, dry_run=args.dry_run)
        return

    if args.run:
        run_pipeline(
            instantly_key, apify_key,
            target=args.target,
            campaign_id=args.campaign_id,
            niches=niches,
            locations=locations,
            dry_run=args.dry_run,
        )
        return

    # Default: show status
    show_status()
    print("\nQuick start:")
    print("  python lead_scaling_engine.py --setup")
    print("  python lead_scaling_engine.py --run --target 100 --dry-run")
    print("  python lead_scaling_engine.py --run --target 200 --campaign-id YOUR_CAMPAIGN_ID")


if __name__ == "__main__":
    main()
