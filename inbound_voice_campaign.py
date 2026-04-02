#!/usr/bin/env python3
"""
Inbound Voice Agent Auto-Campaign
====================================
End-to-end automated campaign builder that:
1. Finds leads via Instantly lead finder (cheapest) or Apify (fallback)
2. Researches each business for phone-heavy pain points
3. Generates high-intent personalized emails about AI inbound receptionists
4. Creates & uploads to a new Instantly campaign with Evergreen enrichment

Targeting: businesses that rely on phone bookings and lose revenue from
missed calls, slow follow-up, and front-desk overflow.

Usage:
    python inbound_voice_campaign.py --target 100 --dry-run
    python inbound_voice_campaign.py --target 200
    python inbound_voice_campaign.py --niches "dental,med_spa" --locations "Miami,Dallas"
    python inbound_voice_campaign.py --apify-fallback --target 50
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

try:
    import anthropic
except ImportError:
    print("Warning: anthropic package not found. Email generation will be skipped.")
    anthropic = None

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "output")
CONFIG_PATH = os.path.join(SCRIPT_DIR, "config.json")
CAMPAIGN_STATE_PATH = os.path.join(OUTPUT_DIR, "inbound_voice_campaign_state.json")

INSTANTLY_BASE = "https://api.instantly.ai/api/v2"
APIFY_BASE = "https://api.apify.com/v2"
GOOGLE_MAPS_ACTOR = "compass~crawler-google-places"

# High-intent niches for inbound voice agents (phone-heavy businesses)
VOICE_AGENT_NICHES = {
    "dental": {
        "queries": ["dental office", "dentist", "dental clinic"],
        "pain": "missed patient calls, after-hours booking requests, front desk overwhelm",
        "result": "capture every call 24/7, book appointments automatically, zero missed patients",
        "titles": ["owner", "dentist", "practice manager", "office manager"],
        "industries": ["medical practice", "hospital & health care"],
    },
    "med_spa": {
        "queries": ["med spa", "medical spa", "aesthetics clinic", "cosmetic clinic"],
        "pain": "missed consultation calls, slow lead follow-up from ads, receptionist turnover",
        "result": "instant lead response, 24/7 booking, 20-40% more appointments from existing ad spend",
        "titles": ["owner", "founder", "medical director", "practice manager"],
        "industries": ["health, wellness & fitness", "cosmetics", "medical practice"],
    },
    "wellness": {
        "queries": ["wellness center", "iv therapy", "holistic health center"],
        "pain": "missed new client calls, can't answer during sessions, losing leads to competitors",
        "result": "never miss a call, AI books while you treat, clients feel heard 24/7",
        "titles": ["owner", "founder", "director", "wellness director"],
        "industries": ["health, wellness & fitness", "alternative medicine"],
    },
    "chiropractic": {
        "queries": ["chiropractor", "chiropractic clinic"],
        "pain": "phone rings during adjustments, missed new patient calls, manual scheduling",
        "result": "AI answers every call, books new patients, handles insurance questions",
        "titles": ["owner", "chiropractor", "practice manager"],
        "industries": ["health, wellness & fitness", "medical practice"],
    },
    "hvac": {
        "queries": ["HVAC company", "heating and cooling", "AC repair"],
        "pain": "missed emergency calls after hours, dispatchers overwhelmed in peak season",
        "result": "24/7 call handling, auto-dispatch for emergencies, never lose a service call",
        "titles": ["owner", "founder", "general manager", "operations manager"],
        "industries": ["construction", "consumer services"],
    },
    "roofing": {
        "queries": ["roofing company", "roofing contractor"],
        "pain": "miss calls while on job sites, lose storm-damage leads to faster competitors",
        "result": "AI qualifies leads from roof, books estimates, speed-to-lead advantage",
        "titles": ["owner", "founder", "president", "general manager"],
        "industries": ["construction"],
    },
    "plumbing": {
        "queries": ["plumber", "plumbing company", "plumbing service"],
        "pain": "emergency calls go to voicemail, office staff can't keep up during busy season",
        "result": "24/7 emergency triage, auto-scheduling, capture every service request",
        "titles": ["owner", "founder", "general manager"],
        "industries": ["construction", "consumer services"],
    },
    "insurance": {
        "queries": ["insurance agency", "insurance broker"],
        "pain": "prospects call once and never again, quoting takes too long, staff drowning in calls",
        "result": "instant quote intake, 24/7 availability, warm transfer hot leads to agents",
        "titles": ["owner", "agent", "broker", "principal", "founder"],
        "industries": ["insurance", "financial services"],
    },
    "veterinary": {
        "queries": ["veterinary clinic", "vet hospital", "animal hospital"],
        "pain": "phone floods with appointment requests, urgent calls buried in routine ones",
        "result": "AI triages urgent vs routine, books wellness visits, frees up vet techs",
        "titles": ["owner", "veterinarian", "hospital director", "practice manager"],
        "industries": ["veterinary"],
    },
}

# High-value US metro areas
TARGET_METROS = [
    "Miami FL", "Dallas TX", "Houston TX", "Phoenix AZ", "Los Angeles CA",
    "Tampa FL", "Orlando FL", "Atlanta GA", "Denver CO", "Nashville TN",
    "Charlotte NC", "Austin TX", "San Diego CA", "Las Vegas NV", "Scottsdale AZ",
]


def load_config():
    with open(CONFIG_PATH) as f:
        return json.load(f)


def api_request(method, endpoint, api_key, data=None):
    url = f"{INSTANTLY_BASE}/{endpoint.lstrip('/')}"
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


def apify_request(method, url, apify_key, **kwargs):
    """Apify API request with retry."""
    for attempt in range(4):
        try:
            resp = requests.request(method, url, params={"token": apify_key}, timeout=30, **kwargs)
            if resp.status_code == 429:
                time.sleep((2 ** attempt) * 2)
                continue
            if resp.status_code >= 400:
                return None
            return resp
        except requests.exceptions.RequestException:
            if attempt < 3:
                time.sleep(2 ** (attempt + 1))
    return None


GENERIC_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "noreply", "no-reply", "donotreply", "billing",
    "reception", "frontdesk", "general", "mail",
}


def is_quality_lead(lead):
    email = lead.get("email", "")
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower()
    if local in GENERIC_PREFIXES:
        return False
    domain = email.split("@")[1].lower()
    if domain in {"gmail.com", "yahoo.com", "hotmail.com", "outlook.com", "aol.com"}:
        return False
    return True


# ─── LEAD SOURCING ──────────────────────────────────────────────────────

def find_leads_instantly(api_key, niche_key, location, limit=25):
    """Find leads via Instantly's lead finder."""
    niche = VOICE_AGENT_NICHES.get(niche_key, {})

    payload = {
        "limit": limit,
        "titles": niche.get("titles", ["owner"]),
        "industry": niche.get("industries", []),
        "employee_range": ["11-50", "51-200"],
        "location": [location] if location else ["United States"],
    }
    if niche.get("queries"):
        payload["keywords"] = niche["queries"]

    result = api_request("POST", "lead-finder/search/people", api_key, payload)
    if "error" in result:
        result = api_request("POST", "lead-finder", api_key, payload)
    if "error" in result:
        return []

    leads = result.get("items", result.get("leads", result.get("data", [])))
    if isinstance(leads, dict):
        leads = leads.get("items", [])
    return [l for l in (leads if isinstance(leads, list) else []) if is_quality_lead(l)]


def _extract_email_from_website(website):
    """Quick scrape a website for email addresses."""
    if not website:
        return ""
    url = website if website.startswith("http") else f"https://{website}"
    # Clean tracking params
    url = re.sub(r'\?utm_.*$', '', url)

    contact_paths = ["", "/contact", "/about", "/contact-us", "/about-us"]
    emails_found = []

    for path in contact_paths:
        try:
            resp = requests.get(url.rstrip("/") + path, timeout=8,
                                headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True)
            if resp.status_code != 200:
                continue
            # Find emails in page
            found = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', resp.text)
            for e in found:
                e_lower = e.lower()
                # Skip junk
                if any(e_lower.endswith(d) for d in [".png", ".jpg", ".gif", ".svg"]):
                    continue
                domain = e_lower.split("@")[1]
                if domain in {"example.com", "wix.com", "wixpress.com", "sentry.io",
                              "sentry-next.wixpress.com", "godaddy.com", "squarespace.com",
                              "facebook.com", "instagram.com", "google.com", "gmail.com",
                              "yahoo.com", "hotmail.com", "outlook.com"}:
                    continue
                emails_found.append(e_lower)
        except Exception:
            continue

    if not emails_found:
        return ""

    # Prefer personal emails over generic
    personal = [e for e in emails_found if e.split("@")[0] not in GENERIC_PREFIXES]
    if personal:
        return personal[0]
    return emails_found[0]


def find_leads_apify(apify_key, niche_key, location, limit=20):
    """Fallback: find leads via Apify Google Maps scraper + email extraction."""
    niche = VOICE_AGENT_NICHES.get(niche_key, {})
    queries = niche.get("queries", [niche_key.replace("_", " ")])

    all_leads = []
    for query in queries[:2]:
        search_term = f"{query} in {location}"
        print(f"    Apify scraping: {search_term}...")

        run_url = f"{APIFY_BASE}/acts/{GOOGLE_MAPS_ACTOR}/runs"
        resp = apify_request("POST", run_url, apify_key, json={
            "searchStringsArray": [search_term],
            "maxCrawledPlacesPerSearch": limit,
            "language": "en",
            "maxImages": 0,
            "maxReviews": 0,
        })
        if not resp:
            continue

        run_data = resp.json()
        run_id = run_data.get("data", {}).get("id")
        if not run_id:
            continue

        # Poll for completion
        status_url = f"{APIFY_BASE}/actor-runs/{run_id}"
        status = ""
        for _ in range(60):
            time.sleep(5)
            s_resp = apify_request("GET", status_url, apify_key)
            if not s_resp:
                break
            status = s_resp.json().get("data", {}).get("status", "")
            if status in ("SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"):
                break

        if status != "SUCCEEDED":
            continue

        dataset_id = run_data.get("data", {}).get("defaultDatasetId")
        if not dataset_id:
            continue

        items_resp = apify_request("GET", f"{APIFY_BASE}/datasets/{dataset_id}/items", apify_key)
        if not items_resp:
            continue

        raw_items = items_resp.json()
        print(f"    Found {len(raw_items)} businesses, extracting emails...")

        for item in raw_items:
            if not item.get("title") or not item.get("website"):
                continue

            website = item.get("website", "")
            # Extract email from their website
            email = _extract_email_from_website(website)

            lead = {
                "company_name": item.get("title", ""),
                "phone": item.get("phone", ""),
                "website": re.sub(r'\?utm_.*$', '', website),
                "category": item.get("categoryName", ""),
                "city": location,
                "source": "apify",
            }

            if email:
                lead["email"] = email
                # Try to extract name from email
                local = email.split("@")[0]
                if "." in local:
                    parts = local.split(".")
                    lead["first_name"] = parts[0].capitalize()
                    lead["last_name"] = parts[-1].capitalize()

            all_leads.append(lead)

        time.sleep(2)

    with_email = sum(1 for l in all_leads if l.get("email"))
    print(f"    Total: {len(all_leads)} businesses, {with_email} with email")
    return all_leads


# ─── EMAIL GENERATION ────────────────────────────────────────────────────

def generate_inbound_emails(leads, niche_key, anthropic_key):
    """Generate high-intent personalized emails for inbound voice agent pitch."""
    if not anthropic or not anthropic_key:
        print("  Skipping AI email generation (no API key)")
        return leads

    niche = VOICE_AGENT_NICHES.get(niche_key, {})
    pain = niche.get("pain", "missed calls and slow follow-up")
    result_text = niche.get("result", "24/7 call handling and automatic booking")

    client = anthropic.Anthropic(api_key=anthropic_key)
    generated = 0

    for lead in leads:
        name = lead.get("first_name", "")
        company = lead.get("company_name", lead.get("business_name", ""))
        title = lead.get("title", "")
        city = lead.get("city", "")

        if not company:
            continue

        prompt = f"""Write a cold email from Dylan Mitchell at Realside AI to {name or 'the owner'} at {company}.

Context:
- {company} is a {niche_key.replace('_', ' ')} business{f' in {city}' if city else ''}
- Their role: {title or 'owner/decision-maker'}
- Their pain: {pain}
- What we solve: {result_text}
- Product: AI Inbound Receptionist that answers calls 24/7, books appointments, handles FAQs, follows up on missed calls
- Proof: recovers 20-40% of missed calls, adds 10-25% more bookings
- CTA: Book a 15-min demo at calendly.com/realsideai

Rules:
- Under 100 words
- Open with something specific to their business (not generic)
- One clear pain point about missed/mishandled calls
- End with curiosity-driven CTA, not hard sell
- Tone: friendly, direct, peer-to-peer
- No "I hope this email finds you"
- No dashes (--)
- Subject line should be casual, under 8 words, spark curiosity

Return ONLY valid JSON:
{{"subject": "...", "body": "..."}}"""

        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text.strip()
            # Extract JSON
            match = re.search(r'\{[^{}]*"subject"[^{}]*"body"[^{}]*\}', text, re.DOTALL)
            if match:
                email_data = json.loads(match.group())
                lead["custom_subject"] = email_data.get("subject", "")
                lead["custom_body"] = email_data.get("body", "")
                generated += 1
        except Exception as e:
            print(f"    Error generating email for {company}: {e}")

        time.sleep(0.5)  # Rate limit

    print(f"  Generated {generated}/{len(leads)} personalized emails")
    return leads


# ─── CAMPAIGN CREATION ───────────────────────────────────────────────────

def create_inbound_campaign(api_key, leads, leads_per_day=15, dry_run=False):
    """Create a new Instantly campaign with Evergreen, upload personalized leads."""
    print("\n" + "=" * 60)
    print("  CREATING INBOUND VOICE AGENT CAMPAIGN")
    print("=" * 60)

    # Get sending accounts
    accounts_result = api_request("GET", "accounts", api_key, {"limit": 100})
    accounts = []
    if "error" not in accounts_result:
        accounts = accounts_result.get("items", accounts_result.get("data", []))
        if isinstance(accounts, dict):
            accounts = accounts.get("items", [])
    account_emails = [a.get("email") for a in accounts if a.get("email")]

    if not account_emails:
        print("  No sending accounts found!")
        return None

    config = load_config()
    opts = config.get("campaign_options", {})

    campaign_name = f"Realside AI — Inbound Voice Agent ({datetime.now().strftime('%b %d')})"

    # All voice agent niches for Evergreen
    all_keywords = []
    all_titles = set()
    all_industries = set()
    for info in VOICE_AGENT_NICHES.values():
        all_keywords.extend(info.get("queries", []))
        all_titles.update(info.get("titles", []))
        all_industries.update(info.get("industries", []))

    campaign_data = {
        "name": campaign_name,
        "campaign_schedule": {
            "schedules": [
                {
                    "name": "Morning",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {"from": "07:00", "to": "09:00"},
                },
                {
                    "name": "Afternoon",
                    "days": {"1": True, "2": True, "3": True, "4": True, "5": True},
                    "timezone": opts.get("timezone", "America/Chicago"),
                    "timing": {"from": "13:00", "to": "15:00"},
                },
            ]
        },
        "sending_accounts": account_emails,
        "daily_limit": opts.get("daily_limit_per_account", 30),
        "open_tracking": True,
        "link_tracking": False,
        "evergreen": {
            "enabled": True,
            "leads_per_cycle": leads_per_day,
            "frequency": "daily",
            "search_filters": {
                "titles": list(all_titles),
                "industries": list(all_industries),
                "keywords": list(dict.fromkeys(all_keywords)),
                "employee_ranges": ["11-50", "51-200"],
                "locations": ["United States", "Canada"],
            },
        },
    }

    if dry_run:
        print(f"  [DRY RUN] Would create: {campaign_name}")
        print(f"  Leads to upload: {len(leads)}")
        print(f"  Evergreen: {leads_per_day}/day")
        return {"dry_run": True, "name": campaign_name}

    result = api_request("POST", "campaigns", api_key, campaign_data)
    if "error" in result:
        print(f"  Error creating campaign: {result.get('error', '')[:200]}")
        return result

    campaign_id = result.get("id", "unknown")
    print(f"  Campaign created: {campaign_id}")
    print(f"  Name: {campaign_name}")
    print(f"  Evergreen: {leads_per_day} leads/day auto-added")

    # Upload leads (only those with email — Instantly requires email)
    leads_with_email = [l for l in leads if l.get("email")]
    leads_no_email = len(leads) - len(leads_with_email)
    if leads_no_email:
        print(f"  Skipping {leads_no_email} leads without email (phone-only)")

    if leads_with_email:
        print(f"\n  Uploading {len(leads_with_email)} leads with email...")
        uploaded = 0
        for i, lead in enumerate(leads_with_email):
            payload = {
                "campaign": campaign_id,
                "email": lead.get("email", ""),
                "first_name": lead.get("first_name", ""),
                "last_name": lead.get("last_name", ""),
                "company_name": lead.get("company_name", lead.get("business_name", "")),
                "website": lead.get("website", ""),
                "custom_variables": {
                    "subject": lead.get("custom_subject", ""),
                    "body": lead.get("custom_body", ""),
                    "title": lead.get("title", ""),
                    "industry": lead.get("industry", ""),
                    "city": lead.get("city", ""),
                    "phone": lead.get("phone", ""),
                    "niche": lead.get("niche", ""),
                    "source": lead.get("source", "scaling_engine"),
                },
            }
            r = api_request("POST", "leads", api_key, payload)
            if "error" not in r:
                uploaded += 1
            if (i + 1) % 25 == 0:
                print(f"  Progress: {uploaded}/{i + 1}")
                time.sleep(1)

        print(f"  Uploaded: {uploaded}/{len(leads_with_email)}")

    # Save state
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(CAMPAIGN_STATE_PATH, "w") as f:
        json.dump({
            "campaign_id": campaign_id,
            "campaign_name": campaign_name,
            "leads_uploaded": len(leads),
            "leads_per_day_evergreen": leads_per_day,
            "created_at": datetime.now().isoformat(),
        }, f, indent=2)

    print(f"\n  Status: DRAFT — activate in Instantly when ready")
    return result


# ─── MAIN PIPELINE ───────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Inbound Voice Agent Auto-Campaign")
    parser.add_argument("--target", type=int, default=100, help="Target leads (default: 100)")
    parser.add_argument("--niches", help="Comma-separated niches (default: all voice-heavy)")
    parser.add_argument("--locations", help="Comma-separated locations (default: top US metros)")
    parser.add_argument("--leads-per-day", type=int, default=15, help="Evergreen leads/day")
    parser.add_argument("--apify-fallback", action="store_true", help="Use Apify as lead source")
    parser.add_argument("--skip-emails", action="store_true", help="Skip AI email generation")
    parser.add_argument("--export", action="store_true", help="Export leads to CSV")
    parser.add_argument("--dry-run", action="store_true", help="Preview mode")
    args = parser.parse_args()

    config = load_config()
    instantly_key = config.get("instantly_api_key", "")
    apify_key = config.get("apify_api_key", "")
    anthropic_key = config.get("anthropic_api_key", "")

    if not instantly_key:
        print("Error: No Instantly API key in config.json")
        sys.exit(1)

    niches = [n.strip().lower().replace(" ", "_") for n in args.niches.split(",")] if args.niches else list(VOICE_AGENT_NICHES.keys())
    locations = [l.strip() for l in args.locations.split(",")] if args.locations else TARGET_METROS[:8]

    print("\n" + "=" * 60)
    print("  INBOUND VOICE AGENT — AUTO CAMPAIGN BUILDER")
    print("=" * 60)
    print(f"\n  Target: {args.target} leads")
    print(f"  Niches: {', '.join(niches)}")
    print(f"  Locations: {', '.join(locations[:5])}{'...' if len(locations) > 5 else ''}")
    print(f"  Source: {'Apify' if args.apify_fallback else 'Instantly Lead Finder'}")

    start_time = time.time()
    all_leads = []
    seen_emails = set()

    # ─── FIND LEADS ──────────────────────────────────────────────────
    print(f"\n{'─' * 50}")
    print(f"  STEP 1: Finding leads")
    print(f"{'─' * 50}")

    for niche in niches:
        if len(all_leads) >= args.target:
            break

        for location in locations:
            if len(all_leads) >= args.target:
                break

            remaining = args.target - len(all_leads)
            per_search = min(25, remaining)

            print(f"\n  {niche} in {location} (need {remaining} more)...")

            if args.dry_run:
                print(f"    [DRY RUN] Would search for {per_search} leads")
                continue

            if args.apify_fallback and apify_key:
                leads = find_leads_apify(apify_key, niche, location, limit=per_search)
            else:
                leads = find_leads_instantly(instantly_key, niche, location, limit=per_search)

            # Dedup — use email if available, otherwise website
            new = 0
            for lead in leads:
                email = lead.get("email", "").lower()
                website = lead.get("website", "").lower()
                dedup_key = email or website
                if dedup_key and dedup_key not in seen_emails:
                    seen_emails.add(dedup_key)
                    lead["niche"] = niche
                    lead["city"] = lead.get("city", location)
                    all_leads.append(lead)
                    new += 1

            print(f"    Found {len(leads)}, {new} new")
            time.sleep(1)

    print(f"\n  Total leads found: {len(all_leads)}")

    # ─── GENERATE EMAILS ─────────────────────────────────────────────
    if all_leads and not args.skip_emails and not args.dry_run:
        print(f"\n{'─' * 50}")
        print(f"  STEP 2: Generating personalized emails")
        print(f"{'─' * 50}")

        # Group by niche for better prompts
        by_niche = {}
        for lead in all_leads:
            n = lead.get("niche", "dental")
            by_niche.setdefault(n, []).append(lead)

        for niche, niche_leads in by_niche.items():
            print(f"\n  Generating for {niche} ({len(niche_leads)} leads)...")
            generate_inbound_emails(niche_leads, niche, anthropic_key)

    # ─── EXPORT CSV ──────────────────────────────────────────────────
    if all_leads and args.export:
        csv_path = os.path.join(OUTPUT_DIR, f"inbound_voice_leads_{datetime.now().strftime('%Y%m%d')}.csv")
        os.makedirs(OUTPUT_DIR, exist_ok=True)
        fields = ["email", "first_name", "last_name", "company_name", "title",
                   "phone", "website", "city", "niche", "custom_subject", "custom_body"]
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for lead in all_leads:
                lead["company_name"] = lead.get("company_name", lead.get("business_name", ""))
                writer.writerow(lead)
        print(f"\n  Exported to {csv_path}")

    # ─── CREATE CAMPAIGN + UPLOAD ────────────────────────────────────
    print(f"\n{'─' * 50}")
    print(f"  STEP 3: Creating campaign + uploading leads")
    print(f"{'─' * 50}")

    create_inbound_campaign(instantly_key, all_leads,
                             leads_per_day=args.leads_per_day,
                             dry_run=args.dry_run)

    elapsed = time.time() - start_time
    print(f"\n{'=' * 60}")
    print(f"  COMPLETE — {len(all_leads)} leads, {elapsed:.0f}s")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
