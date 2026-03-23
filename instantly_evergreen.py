#!/usr/bin/env python3
"""
Instantly Evergreen Enrichment Configurator
=============================================
Configures Instantly.ai campaigns with Evergreen enrichment — automatically
adds fresh leads to campaigns on a recurring schedule using Instantly's
built-in lead database + Perplexity Supersearch.

This eliminates manual CSV uploads. Instantly finds and adds leads matching
your ICP criteria on autopilot.

Usage:
    python instantly_evergreen.py --list-campaigns
    python instantly_evergreen.py --campaign-id ABC123 --enable --leads-per-day 10
    python instantly_evergreen.py --campaign-id ABC123 --search-filters '{"title":"owner","industry":"dental"}'
    python instantly_evergreen.py --create-campaign "Med Spa Evergreen" --leads-per-day 15
    python instantly_evergreen.py --status
    python instantly_evergreen.py --dry-run
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
EVERGREEN_STATE_PATH = os.path.join(OUTPUT_DIR, "evergreen_state.json")

BASE_URL = "https://api.instantly.ai/api/v2"

# ICP search filters for service businesses
DEFAULT_SEARCH_FILTERS = {
    "titles": [
        "owner", "ceo", "founder", "president", "managing partner",
        "practice manager", "office manager", "operations manager",
        "marketing director", "marketing manager"
    ],
    "industries": [
        "health, wellness & fitness",
        "medical practice",
        "hospital & health care",
        "cosmetics",
        "consumer services",
    ],
    "employee_ranges": ["11-50", "51-200"],
    "locations": ["United States", "Canada"],
    "keywords": [
        "med spa", "medical spa", "dental", "dentist", "aesthetics",
        "wellness center", "dermatology", "plastic surgery", "iv therapy",
        "chiropractic", "physical therapy", "veterinary", "optometry",
        "orthodontics", "oral surgery", "cosmetic surgery",
        "hvac", "heating and air", "air conditioning", "plumbing heating",
        "hvac contractor", "furnace", "ac repair"
    ],
}

# Evergreen schedule presets
SCHEDULE_PRESETS = {
    "conservative": {"leads_per_cycle": 5, "frequency": "daily", "description": "5 leads/day — low burn, steady growth"},
    "balanced": {"leads_per_cycle": 15, "frequency": "daily", "description": "15 leads/day — good balance of volume and quality"},
    "aggressive": {"leads_per_cycle": 30, "frequency": "daily", "description": "30 leads/day — max volume for scaling fast"},
    "weekly_burst": {"leads_per_cycle": 50, "frequency": "weekly", "description": "50 leads/week — weekly batch for review"},
}


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, "r") as f:
            return json.load(f)
    return {}


def api_request(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    """Authenticated request to Instantly API with retry + backoff."""
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
                resp = requests.delete(url, headers=headers, timeout=30)
            else:
                raise ValueError(f"Unsupported method: {method}")

            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code >= 400:
                print(f"  API error {resp.status_code}: {resp.text[:300]}")
                return {"error": resp.text, "status_code": resp.status_code}

            return resp.json() if resp.text else {}

        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"  Failed after 4 attempts: {e}")
                return {"error": str(e)}

    return {"error": "Max retries exceeded"}


def load_evergreen_state() -> dict:
    """Load persistent state tracking evergreen configs."""
    if os.path.exists(EVERGREEN_STATE_PATH):
        try:
            with open(EVERGREEN_STATE_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {"campaigns": {}, "total_leads_added": 0, "last_updated": None}


def save_evergreen_state(state: dict):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    state["last_updated"] = datetime.now().isoformat()
    with open(EVERGREEN_STATE_PATH, "w") as f:
        json.dump(state, f, indent=2)


def list_campaigns(api_key: str):
    """List all campaigns with their status."""
    print("\n=== Instantly Campaigns ===\n")
    result = api_request("GET", "campaigns", api_key, {"limit": 100})
    if "error" in result:
        print(f"Error fetching campaigns: {result['error']}")
        return []

    campaigns = result.get("items", result) if isinstance(result, dict) else result
    if not campaigns:
        print("No campaigns found.")
        return []

    for c in campaigns:
        cid = c.get("id", "?")
        name = c.get("name", "Unnamed")
        status = c.get("status", "unknown")
        lead_count = c.get("leads_count", c.get("lead_count", "?"))
        print(f"  [{status:>8}] {name}")
        print(f"           ID: {cid}  |  Leads: {lead_count}")

    return campaigns


def list_sending_accounts(api_key: str) -> list:
    """Get all sending accounts."""
    result = api_request("GET", "accounts", api_key, {"limit": 100})
    if "error" in result:
        print(f"Error fetching accounts: {result['error']}")
        return []
    accounts = result.get("items", result) if isinstance(result, dict) else result
    return accounts if isinstance(accounts, list) else []


def search_leads_supersearch(api_key: str, filters: dict, limit: int = 50) -> list:
    """
    Use Instantly's Supersearch (Perplexity-powered) to find leads.
    This searches Instantly's 300M+ contact database with AI enrichment.
    """
    print(f"\n  Searching Instantly lead database (limit: {limit})...")

    search_payload = {
        "limit": limit,
        "titles": filters.get("titles", DEFAULT_SEARCH_FILTERS["titles"]),
        "industry": filters.get("industries", DEFAULT_SEARCH_FILTERS["industries"]),
        "employee_range": filters.get("employee_ranges", DEFAULT_SEARCH_FILTERS["employee_ranges"]),
        "location": filters.get("locations", DEFAULT_SEARCH_FILTERS["locations"]),
    }

    # Add keyword filtering if provided
    if filters.get("keywords"):
        search_payload["keywords"] = filters["keywords"]

    result = api_request("POST", "lead-search", api_key, search_payload)
    if "error" in result:
        # Try alternate endpoint
        result = api_request("POST", "leads/search", api_key, search_payload)
        if "error" in result:
            print(f"  Supersearch error: {result.get('error', 'unknown')}")
            return []

    leads = result.get("items", result.get("leads", []))
    if isinstance(leads, dict):
        leads = leads.get("items", [])

    print(f"  Found {len(leads)} leads via Supersearch")
    return leads if isinstance(leads, list) else []


def create_evergreen_campaign(api_key: str, name: str, sending_accounts: list,
                               schedule_preset: str = "balanced",
                               search_filters: dict = None,
                               dry_run: bool = False) -> dict:
    """
    Create a new campaign with Evergreen enrichment enabled.
    Evergreen = Instantly auto-adds leads matching your filters on a schedule.
    """
    config = load_config()
    opts = config.get("campaign_options", {})
    preset = SCHEDULE_PRESETS.get(schedule_preset, SCHEDULE_PRESETS["balanced"])

    print(f"\n=== Creating Evergreen Campaign ===")
    print(f"  Name: {name}")
    print(f"  Schedule: {preset['description']}")
    print(f"  Sending accounts: {len(sending_accounts)}")

    filters = search_filters or DEFAULT_SEARCH_FILTERS

    # Build campaign payload
    campaign_data = {
        "name": name,
        "campaign_schedule": {
            "schedules": [
                {
                    "name": "Morning",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {
                        "from": opts.get("morning_start", "07:00"),
                        "to": opts.get("morning_end", "09:00"),
                    },
                },
                {
                    "name": "Afternoon",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {
                        "from": opts.get("afternoon_start", "13:00"),
                        "to": opts.get("afternoon_end", "15:00"),
                    },
                },
            ]
        },
        "sending_accounts": sending_accounts,
        "daily_limit": opts.get("daily_limit_per_account", 30),
        "open_tracking": opts.get("open_tracking", True),
        "link_tracking": opts.get("link_tracking", False),
        # Evergreen enrichment settings
        "evergreen": {
            "enabled": True,
            "leads_per_cycle": preset["leads_per_cycle"],
            "frequency": preset["frequency"],
            "search_filters": {
                "titles": filters.get("titles", []),
                "industries": filters.get("industries", []),
                "employee_ranges": filters.get("employee_ranges", []),
                "locations": filters.get("locations", []),
                "keywords": filters.get("keywords", []),
            },
        },
    }

    if dry_run:
        print("\n  [DRY RUN] Would create campaign with payload:")
        print(json.dumps(campaign_data, indent=2))
        return {"dry_run": True, "payload": campaign_data}

    result = api_request("POST", "campaigns", api_key, campaign_data)
    if "error" in result:
        print(f"  Error creating campaign: {result['error']}")
        return result

    campaign_id = result.get("id", "unknown")
    print(f"  Campaign created: {campaign_id}")
    print(f"  Status: DRAFT (activate manually when ready)")

    # Save state
    state = load_evergreen_state()
    state["campaigns"][campaign_id] = {
        "name": name,
        "preset": schedule_preset,
        "leads_per_cycle": preset["leads_per_cycle"],
        "frequency": preset["frequency"],
        "filters": filters,
        "created_at": datetime.now().isoformat(),
        "status": "draft",
    }
    save_evergreen_state(state)

    return result


def enable_evergreen_on_existing(api_key: str, campaign_id: str,
                                  leads_per_day: int = 15,
                                  search_filters: dict = None,
                                  dry_run: bool = False) -> dict:
    """Enable Evergreen enrichment on an existing campaign."""
    filters = search_filters or DEFAULT_SEARCH_FILTERS

    print(f"\n=== Enabling Evergreen on Campaign {campaign_id} ===")
    print(f"  Leads per day: {leads_per_day}")

    evergreen_config = {
        "evergreen": {
            "enabled": True,
            "leads_per_cycle": leads_per_day,
            "frequency": "daily",
            "search_filters": {
                "titles": filters.get("titles", []),
                "industries": filters.get("industries", []),
                "employee_ranges": filters.get("employee_ranges", []),
                "locations": filters.get("locations", []),
                "keywords": filters.get("keywords", []),
            },
        }
    }

    if dry_run:
        print("\n  [DRY RUN] Would update campaign with:")
        print(json.dumps(evergreen_config, indent=2))
        return {"dry_run": True}

    result = api_request("PATCH", f"campaigns/{campaign_id}", api_key, evergreen_config)
    if "error" in result:
        print(f"  Error: {result['error']}")
        return result

    print(f"  Evergreen enabled successfully!")

    state = load_evergreen_state()
    state["campaigns"][campaign_id] = {
        "leads_per_day": leads_per_day,
        "enabled_at": datetime.now().isoformat(),
        "filters": filters,
        "status": "evergreen_active",
    }
    save_evergreen_state(state)

    return result


def show_status(api_key: str):
    """Show status of all evergreen-configured campaigns."""
    state = load_evergreen_state()
    print("\n=== Evergreen Enrichment Status ===\n")

    if not state["campaigns"]:
        print("  No evergreen campaigns configured yet.")
        print("  Use --create-campaign or --enable to get started.")
        return

    for cid, info in state["campaigns"].items():
        name = info.get("name", "Unknown")
        status = info.get("status", "unknown")
        leads_per = info.get("leads_per_cycle", info.get("leads_per_day", "?"))
        freq = info.get("frequency", "daily")
        created = info.get("created_at", info.get("enabled_at", "?"))

        print(f"  Campaign: {name}")
        print(f"    ID: {cid}")
        print(f"    Status: {status}")
        print(f"    Rate: {leads_per} leads/{freq}")
        print(f"    Since: {created}")
        print()

    print(f"  Total leads added (tracked): {state.get('total_leads_added', 0)}")
    print(f"  Last updated: {state.get('last_updated', 'never')}")


def main():
    parser = argparse.ArgumentParser(description="Instantly Evergreen Enrichment Configurator")
    parser.add_argument("--api-key", help="Instantly API key (or uses config.json)")
    parser.add_argument("--list-campaigns", action="store_true", help="List all campaigns")
    parser.add_argument("--campaign-id", help="Campaign ID to configure")
    parser.add_argument("--enable", action="store_true", help="Enable evergreen on a campaign")
    parser.add_argument("--leads-per-day", type=int, default=15, help="Leads to add per day (default: 15)")
    parser.add_argument("--create-campaign", metavar="NAME", help="Create a new evergreen campaign")
    parser.add_argument("--preset", choices=list(SCHEDULE_PRESETS.keys()), default="balanced",
                        help="Schedule preset (default: balanced)")
    parser.add_argument("--search-filters", help="JSON string of custom search filters")
    parser.add_argument("--search", action="store_true", help="Run a Supersearch to preview leads")
    parser.add_argument("--search-limit", type=int, default=25, help="Max leads for search preview")
    parser.add_argument("--status", action="store_true", help="Show evergreen status")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    args = parser.parse_args()

    config = load_config()
    api_key = args.api_key or config.get("instantly_api_key", "")
    if not api_key:
        print("Error: No API key. Use --api-key or set instantly_api_key in config.json")
        sys.exit(1)

    custom_filters = None
    if args.search_filters:
        try:
            custom_filters = json.loads(args.search_filters)
        except json.JSONDecodeError:
            print("Error: --search-filters must be valid JSON")
            sys.exit(1)

    if args.status:
        show_status(api_key)
        return

    if args.list_campaigns:
        list_campaigns(api_key)
        return

    if args.search:
        leads = search_leads_supersearch(api_key, custom_filters or DEFAULT_SEARCH_FILTERS, args.search_limit)
        if leads:
            print(f"\n  Preview of {len(leads)} leads found:")
            for i, lead in enumerate(leads[:10], 1):
                email = lead.get("email", "?")
                name = lead.get("first_name", "") + " " + lead.get("last_name", "")
                company = lead.get("company_name", lead.get("company", "?"))
                title = lead.get("title", "?")
                print(f"    {i}. {name.strip()} — {title} @ {company} ({email})")
        return

    if args.create_campaign:
        accounts = list_sending_accounts(api_key)
        if not accounts:
            print("Error: No sending accounts found. Add accounts in Instantly first.")
            sys.exit(1)
        account_emails = [a.get("email", a.get("id")) for a in accounts]
        print(f"  Using {len(account_emails)} sending account(s)")

        create_evergreen_campaign(
            api_key, args.create_campaign, account_emails,
            schedule_preset=args.preset,
            search_filters=custom_filters,
            dry_run=args.dry_run,
        )
        return

    if args.enable and args.campaign_id:
        enable_evergreen_on_existing(
            api_key, args.campaign_id,
            leads_per_day=args.leads_per_day,
            search_filters=custom_filters,
            dry_run=args.dry_run,
        )
        return

    # Default: show status + list presets
    show_status(api_key)
    print("\n=== Available Presets ===\n")
    for name, preset in SCHEDULE_PRESETS.items():
        print(f"  {name:>20}: {preset['description']}")
    print("\nUsage examples:")
    print("  python instantly_evergreen.py --create-campaign 'Med Spa Evergreen' --preset aggressive")
    print("  python instantly_evergreen.py --campaign-id ABC123 --enable --leads-per-day 20")
    print("  python instantly_evergreen.py --search --search-limit 50")


if __name__ == "__main__":
    main()
