#!/usr/bin/env python3
"""
Run Scaling Engine on All Active Campaigns
=============================================
1. Enables Evergreen enrichment on all active Instantly campaigns
2. Uploads pending Halifax leads (owner campaign + NS leads)
3. Runs Supersearch to top up each campaign with fresh leads

Usage:
    python run_scaling_all_campaigns.py
    python run_scaling_all_campaigns.py --dry-run
    python run_scaling_all_campaigns.py --evergreen-only
    python run_scaling_all_campaigns.py --upload-only
"""

import argparse
import csv
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
BASE_URL = "https://api.instantly.ai/api/v2"

# Campaign IDs and their niche for Evergreen targeting
CAMPAIGN_NICHE_MAP = {
    "fa700df4-0801-4895-ad18-04197799c0fb": {
        "name": "Dental Campaign",
        "niches": ["dental office", "dentist", "dental clinic", "family dentistry", "orthodontics"],
        "titles": ["owner", "dentist", "practice manager", "office manager", "founder"],
        "industries": ["medical practice", "hospital & health care"],
    },
    "e405ef7d-b54b-47a7-bb47-1969b0af5024": {
        "name": "HVAC Campaign",
        "niches": ["HVAC company", "heating and cooling", "air conditioning service"],
        "titles": ["owner", "founder", "ceo", "president", "general manager"],
        "industries": ["construction", "consumer services"],
    },
    "e04737bb-aa8f-4f6d-8226-d07a09d43d6f": {
        "name": "Private clinic Campaign",
        "niches": ["private clinic", "medical clinic", "aesthetic clinic", "med spa", "wellness center"],
        "titles": ["owner", "medical director", "founder", "practice manager", "ceo"],
        "industries": ["medical practice", "health, wellness & fitness", "hospital & health care"],
    },
    "a0ef9df5-9fb5-4148-b7b7-c80b71472a5b": {
        "name": "Roofing campaign",
        "niches": ["roofing company", "roofing contractor", "roof repair"],
        "titles": ["owner", "founder", "president", "general manager"],
        "industries": ["construction", "consumer services"],
    },
    "0d051290-be7a-4ca3-a458-03d2eeafc729": {
        "name": "Insurance Campaign",
        "niches": ["insurance agency", "insurance broker", "insurance office"],
        "titles": ["owner", "agent", "broker", "principal", "founder", "president"],
        "industries": ["insurance", "financial services"],
    },
    "054ab8e5-f26f-4a5e-916a-09656107f116": {
        "name": "Realside AI — Halifax Owners",
        "niches": ["Halifax business owner", "Nova Scotia service business"],
        "titles": ["owner", "founder", "ceo", "president", "operator"],
        "industries": ["construction", "consumer services", "health, wellness & fitness"],
    },
    "01c5b232-1b32-4747-8afb-ff3d29c7d0ef": {
        "name": "Estate lynx Campaign",
        "niches": ["real estate agency", "property management", "real estate broker"],
        "titles": ["owner", "broker", "managing director", "founder", "principal"],
        "industries": ["real estate", "commercial real estate"],
    },
}

# Halifax-specific campaigns
HALIFAX_OWNERS_CAMPAIGN = "054ab8e5-f26f-4a5e-916a-09656107f116"
HALIFAX_BLUE_COLLAR_CAMPAIGN = "ac5b88e8-38bd-4d43-ab6b-2f09deb73d60"


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_request(method, endpoint, api_key, data=None):
    url = f"{BASE_URL}/{endpoint.lstrip('/')}"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    for attempt in range(4):
        try:
            if method == "GET":
                resp = requests.get(url, headers=headers, params=data, timeout=30)
            elif method == "POST":
                resp = requests.post(url, headers=headers, json=data, timeout=30)
            elif method == "PATCH":
                resp = requests.patch(url, headers=headers, json=data, timeout=30)
            else:
                raise ValueError(f"Unsupported: {method}")
            if resp.status_code == 429:
                wait = (2 ** attempt) * 2
                print(f"  Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            if resp.status_code >= 400:
                print(f"  API error {resp.status_code}: {resp.text[:200]}")
                return {"error": resp.text, "status_code": resp.status_code}
            return resp.json() if resp.text else {}
        except requests.exceptions.RequestException as e:
            if attempt < 3:
                wait = 2 ** (attempt + 1)
                print(f"  Network error, retrying in {wait}s: {e}")
                time.sleep(wait)
            else:
                return {"error": str(e)}
    return {"error": "Max retries exceeded"}


def get_sending_accounts(api_key):
    result = api_request("GET", "accounts", api_key, {"limit": 100})
    if "error" in result:
        return []
    accounts = result.get("items", result.get("data", result))
    if isinstance(accounts, dict):
        accounts = accounts.get("items", [])
    return accounts if isinstance(accounts, list) else []


# ─── EVERGREEN SETUP ────────────────────────────────────────────────────

def create_evergreen_campaign(api_key, leads_per_day=15, dry_run=False):
    """Create a NEW dedicated Evergreen campaign with auto-enrichment.
    All niches feed into one campaign so leads scale automatically."""
    print("\n" + "=" * 60)
    print("  CREATING DEDICATED EVERGREEN CAMPAIGN")
    print("=" * 60)

    # Get sending accounts
    accounts_result = api_request("GET", "accounts", api_key, {"limit": 100})
    if "error" in accounts_result:
        print(f"  Error getting accounts: {accounts_result.get('error', '')[:100]}")
        return None
    accounts = accounts_result.get("items", accounts_result.get("data", accounts_result))
    if isinstance(accounts, dict):
        accounts = accounts.get("items", [])
    if not isinstance(accounts, list):
        accounts = []
    account_emails = [a.get("email", a.get("id", "")) for a in accounts if a.get("email")]

    if not account_emails:
        print("  No sending accounts found! Add accounts in Instantly first.")
        return None

    print(f"  Sending accounts: {len(account_emails)}")

    config = load_config()
    opts = config.get("campaign_options", {})

    # All ICP keywords combined for max coverage
    all_keywords = []
    for info in CAMPAIGN_NICHE_MAP.values():
        all_keywords.extend(info.get("niches", []))
    # Deduplicate
    all_keywords = list(dict.fromkeys(all_keywords))

    all_titles = ["owner", "ceo", "founder", "president", "principal",
                  "managing partner", "practice manager", "office manager",
                  "medical director", "general manager", "marketing director"]

    all_industries = []
    for info in CAMPAIGN_NICHE_MAP.values():
        all_industries.extend(info.get("industries", []))
    all_industries = list(dict.fromkeys(all_industries))

    campaign_name = f"Realside AI — Evergreen Auto-Scale ({datetime.now().strftime('%b %Y')})"

    campaign_data = {
        "name": campaign_name,
        "campaign_schedule": {
            "schedules": [
                {
                    "name": "Morning",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {"from": opts.get("morning_start", "07:00"),
                               "to": opts.get("morning_end", "09:00")},
                },
                {
                    "name": "Afternoon",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {"from": opts.get("afternoon_start", "13:00"),
                               "to": opts.get("afternoon_end", "15:00")},
                },
            ]
        },
        "sending_accounts": account_emails,
        "daily_limit": opts.get("daily_limit_per_account", 30),
        "open_tracking": opts.get("open_tracking", True),
        "link_tracking": opts.get("link_tracking", False),
        "evergreen": {
            "enabled": True,
            "leads_per_cycle": leads_per_day,
            "frequency": "daily",
            "search_filters": {
                "titles": all_titles,
                "industries": all_industries,
                "keywords": all_keywords,
                "employee_ranges": ["11-50", "51-200"],
                "locations": ["United States", "Canada"],
            },
        },
    }

    print(f"\n  Campaign: {campaign_name}")
    print(f"  Evergreen: {leads_per_day} leads/day auto-added")
    print(f"  Keywords: {len(all_keywords)} across all niches")
    print(f"  Titles: {', '.join(all_titles[:5])}...")

    if dry_run:
        print(f"\n  [DRY RUN] Would create campaign with payload:")
        print(json.dumps(campaign_data, indent=2)[:500] + "...")
        return {"dry_run": True, "name": campaign_name}

    result = api_request("POST", "campaigns", api_key, campaign_data)
    if "error" in result:
        print(f"  Error creating campaign: {result.get('error', '')[:200]}")
        return result

    campaign_id = result.get("id", "unknown")
    print(f"\n  Campaign created: {campaign_id}")
    print(f"  Status: DRAFT — activate in Instantly when ready")
    print(f"  Evergreen will auto-add {leads_per_day} leads/day once activated")

    # Save campaign ID for future reference
    state_path = os.path.join(OUTPUT_DIR, "evergreen_campaign.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(state_path, "w") as f:
        json.dump({
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "leads_per_day": leads_per_day,
            "created_at": datetime.now().isoformat(),
            "keywords": all_keywords,
            "titles": all_titles,
        }, f, indent=2)

    return result


# ─── HALIFAX UPLOADS ─────────────────────────────────────────────────────

def _upload_lead(api_key, campaign_id, lead):
    """Upload a single lead using the correct Instantly API format."""
    payload = {
        "campaign": campaign_id,
        "email": lead.get("email", ""),
        "first_name": lead.get("first_name", ""),
        "last_name": lead.get("last_name", ""),
        "company_name": lead.get("company_name", ""),
        "website": lead.get("website", ""),
        "custom_variables": lead.get("custom_variables", {}),
    }
    return api_request("POST", "leads", api_key, payload)


def _is_owner_title(title):
    """Check if title indicates owner/CEO/founder."""
    if not title:
        return False
    title_lower = title.lower()
    owner_keywords = ("owner", "ceo", "founder", "president", "principal",
                      "managing partner", "co-founder", "co-owner", "operator",
                      "managing director")
    return any(k in title_lower for k in owner_keywords)


def upload_halifax_owner_emails(api_key, dry_run=False):
    """Upload owner-only leads to Halifax Owners campaign."""
    print("\n" + "=" * 60)
    print("  UPLOADING HALIFAX OWNER CAMPAIGN EMAILS (OWNERS ONLY)")
    print("=" * 60)

    # Load from both sources: owner_campaign_emails + halifax_owners_enriched
    all_leads = []

    # Source 1: Owner campaign emails (already filtered)
    csv_path = os.path.join(OUTPUT_DIR, "owner_campaign_emails.csv")
    if os.path.exists(csv_path):
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").strip()
                if not email or "@" not in email:
                    continue
                all_leads.append({
                    "email": email,
                    "first_name": row.get("first_name", ""),
                    "last_name": row.get("last_name", ""),
                    "company_name": row.get("company_name", row.get("company", "")),
                    "website": row.get("website", row.get("domain", "")),
                    "custom_variables": {
                        "subject_1": row.get("subject_1", row.get("subject", "")),
                        "body_1": row.get("body_1", row.get("body", "")),
                        "subject_2": row.get("subject_2", ""),
                        "body_2": row.get("body_2", ""),
                        "subject_3": row.get("subject_3", ""),
                        "body_3": row.get("body_3", ""),
                        "subject_4": row.get("subject_4", ""),
                        "body_4": row.get("body_4", ""),
                        "title": row.get("title", ""),
                        "industry": row.get("industry", ""),
                        "source": "halifax_owner_campaign",
                    },
                })
        print(f"  Loaded {len(all_leads)} from owner_campaign_emails.csv")

    # Source 2: Halifax owners enriched (filter for owners with emails)
    enriched_path = os.path.join(OUTPUT_DIR, "halifax_owners_enriched.csv")
    enriched_added = 0
    existing_emails = {l["email"].lower() for l in all_leads}
    if os.path.exists(enriched_path):
        with open(enriched_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = row.get("email", "").strip()
                if not email or "@" not in email:
                    continue
                if email.lower() in existing_emails:
                    continue
                title = row.get("title", "")
                if not _is_owner_title(title):
                    continue
                existing_emails.add(email.lower())
                enriched_added += 1
                all_leads.append({
                    "email": email,
                    "first_name": row.get("first_name", ""),
                    "last_name": row.get("last_name", ""),
                    "company_name": row.get("company_name", ""),
                    "website": "",
                    "custom_variables": {
                        "title": title,
                        "industry": row.get("industry", ""),
                        "source": "halifax_owners_enriched",
                    },
                })
        print(f"  Added {enriched_added} owners from halifax_owners_enriched.csv")

    print(f"  Total owner leads to upload: {len(all_leads)}")

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(all_leads)} leads to Halifax Owners campaign")
        return len(all_leads)

    # Upload one-by-one (correct Instantly API format)
    uploaded = 0
    for i, lead in enumerate(all_leads):
        result = _upload_lead(api_key, HALIFAX_OWNERS_CAMPAIGN, lead)
        if "error" not in result:
            uploaded += 1
        else:
            if i < 3:  # Only log first few errors
                print(f"  Failed {lead['email']}: {result.get('error', '')[:80]}")
        if (i + 1) % 25 == 0:
            print(f"  Progress: {uploaded}/{i + 1}")
            time.sleep(1)

    print(f"\n  Total uploaded to Halifax Owners: {uploaded}/{len(all_leads)}")
    return uploaded


def upload_ns_leads_to_blue_collar(api_key, dry_run=False):
    """Upload NS qualified leads to Halifax blue collar campaign."""
    print("\n" + "=" * 60)
    print("  UPLOADING NS LEADS TO HALIFAX BLUE COLLAR CAMPAIGN")
    print("=" * 60)

    # Try NS campaign emails first (has personalized subjects/bodies)
    csv_path = os.path.join(OUTPUT_DIR, "ns_campaign_emails.csv")
    if not os.path.exists(csv_path):
        csv_path = os.path.join(OUTPUT_DIR, "ns_leads_qualified.csv")
    if not os.path.exists(csv_path):
        print("  No NS lead files found")
        return 0

    leads = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            email = row.get("email", "").strip()
            if not email or "@" not in email:
                continue

            # Skip junk emails
            local = email.split("@")[0].lower()
            junk = {"noreply", "no-reply", "donotreply", "do-not-reply"}
            if local in junk:
                continue

            leads.append({
                "email": email,
                "first_name": row.get("first_name", ""),
                "last_name": row.get("last_name", ""),
                "company_name": row.get("company_name", row.get("company", "")),
                "website": row.get("domain", ""),
                "custom_variables": {
                    "subject": row.get("subject", ""),
                    "body": row.get("body", ""),
                    "category": row.get("category", ""),
                    "city": row.get("city", ""),
                    "domain": row.get("domain", ""),
                    "source": "ns_campaign",
                },
            })

    # Deduplicate by email
    seen = set()
    unique_leads = []
    for lead in leads:
        if lead["email"].lower() not in seen:
            seen.add(lead["email"].lower())
            unique_leads.append(lead)

    print(f"  Loaded {len(unique_leads)} unique leads from {csv_path}")

    if dry_run:
        print(f"  [DRY RUN] Would upload {len(unique_leads)} leads to Halifax Blue Collar")
        return len(unique_leads)

    # Upload one-by-one (correct Instantly API format)
    uploaded = 0
    for i, lead in enumerate(unique_leads):
        result = _upload_lead(api_key, HALIFAX_BLUE_COLLAR_CAMPAIGN, lead)
        if "error" not in result:
            uploaded += 1
        else:
            if i < 3:
                print(f"  Failed {lead['email']}: {result.get('error', '')[:80]}")
        if (i + 1) % 25 == 0:
            print(f"  Progress: {uploaded}/{i + 1}")
            time.sleep(1)

    print(f"\n  Total uploaded to Halifax Blue Collar: {uploaded}/{len(unique_leads)}")
    return uploaded


# ─── SUPERSEARCH TOP-UP ─────────────────────────────────────────────────

def supersearch_topup(api_key, leads_per_campaign=25, dry_run=False):
    """Run Supersearch to add fresh leads to each active campaign."""
    print("\n" + "=" * 60)
    print("  SUPERSEARCH TOP-UP: ALL ACTIVE CAMPAIGNS")
    print("=" * 60)

    total_added = 0

    for campaign_id, info in CAMPAIGN_NICHE_MAP.items():
        name = info["name"]
        print(f"\n--- {name} ---")

        # Build search payload
        search_payload = {
            "limit": leads_per_campaign,
            "titles": info.get("titles", []),
            "industry": info.get("industries", []),
            "employee_range": ["11-50", "51-200"],
            "location": ["United States", "Canada"],
        }

        if info.get("niches"):
            search_payload["keywords"] = info["niches"]

        if dry_run:
            print(f"  [DRY RUN] Would search for {leads_per_campaign} leads")
            print(f"    Keywords: {info.get('niches', [])[:3]}")
            continue

        # Search via Instantly lead finder
        print(f"  Searching for {leads_per_campaign} leads...")
        result = api_request("POST", "lead-finder/search/people", api_key, search_payload)
        if "error" in result:
            result = api_request("POST", "lead-finder", api_key, search_payload)

        if "error" in result:
            print(f"  Search failed: {result.get('error', '')[:100]}")
            time.sleep(1)
            continue

        leads_data = result.get("items", result.get("leads", result.get("data", [])))
        if isinstance(leads_data, dict):
            leads_data = leads_data.get("items", [])
        if not isinstance(leads_data, list):
            leads_data = []

        # Filter quality leads
        quality = []
        for lead in leads_data:
            email = lead.get("email", "")
            if not email or "@" not in email:
                continue
            local = email.split("@")[0].lower()
            skip_prefixes = {"noreply", "no-reply", "donotreply", "info", "contact", "support"}
            if local in skip_prefixes:
                continue
            quality.append({
                "email": email,
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company_name": lead.get("company_name", lead.get("company", "")),
                "website": lead.get("website", ""),
                "custom_variables": {
                    "title": lead.get("title", ""),
                    "industry": lead.get("industry", ""),
                    "city": lead.get("city", ""),
                    "source": "supersearch_topup",
                },
            })

        print(f"  Found {len(leads_data)} raw, {len(quality)} quality leads")

        if quality:
            # Upload leads one by one (correct API format)
            uploaded = 0
            for lead in quality:
                r = _upload_lead(api_key, campaign_id, lead)
                if "error" not in r:
                    uploaded += 1
            total_added += uploaded
            print(f"  Added {uploaded}/{len(quality)} leads to campaign")

        time.sleep(2)  # Rate limit between campaigns

    print(f"\n  Total leads added across all campaigns: {total_added}")
    return total_added


# ─── MAIN ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Run scaling engine on all active campaigns")
    parser.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    parser.add_argument("--evergreen-only", action="store_true", help="Only enable Evergreen")
    parser.add_argument("--upload-only", action="store_true", help="Only upload Halifax leads")
    parser.add_argument("--topup-only", action="store_true", help="Only run Supersearch top-up")
    parser.add_argument("--leads-per-day", type=int, default=15, help="Evergreen leads/day (default: 15)")
    parser.add_argument("--topup-leads", type=int, default=25, help="Supersearch leads per campaign (default: 25)")
    args = parser.parse_args()

    config = load_config()
    api_key = config.get("instantly_api_key", "")
    if not api_key:
        print("Error: No Instantly API key in config.json")
        sys.exit(1)

    start = time.time()
    run_all = not (args.evergreen_only or args.upload_only or args.topup_only)

    # Step 1: Create dedicated Evergreen auto-scale campaign
    if run_all or args.evergreen_only:
        create_evergreen_campaign(api_key, leads_per_day=args.leads_per_day, dry_run=args.dry_run)

    # Step 2: Upload pending Halifax leads (owners only to Owners campaign)
    if run_all or args.upload_only:
        upload_halifax_owner_emails(api_key, dry_run=args.dry_run)
        upload_ns_leads_to_blue_collar(api_key, dry_run=args.dry_run)

    # Step 3: Supersearch top-up for all campaigns
    if run_all or args.topup_only:
        supersearch_topup(api_key, leads_per_campaign=args.topup_leads, dry_run=args.dry_run)

    elapsed = time.time() - start
    print(f"\n{'=' * 60}")
    print(f"  ALL DONE — {elapsed:.0f}s elapsed")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
