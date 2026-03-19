#!/usr/bin/env python3
"""
Instantly.ai Campaign Uploader
===============================
Takes pipeline output CSVs and uploads them as campaigns to Instantly.ai
with fully custom per-lead emails using custom variables.

Usage:
    python instantly_uploader.py --api-key YOUR_KEY
    python instantly_uploader.py --api-key YOUR_KEY --csvs output/prospect_emails.csv output/case_study_emails.csv
    python instantly_uploader.py --api-key YOUR_KEY --list-campaigns
    python instantly_uploader.py --api-key YOUR_KEY --dry-run
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:
    print("Error: requests package required. Install with: pip install requests")
    sys.exit(1)

BASE_URL = "https://api.instantly.ai/api/v2"
DEFAULT_TIMEZONE = "America/Chicago"
BATCH_SIZE = 50  # leads per API call
RATE_LIMIT_DELAY = 1  # seconds between API calls

# Optimal cold-email sending defaults
DEFAULT_DAILY_LIMIT_PER_ACCOUNT = 30  # conservative to protect deliverability
DEFAULT_REPLY_TO_PERCENTAGE = 100  # reply tracking
DEFAULT_OPEN_TRACKING = True
DEFAULT_LINK_TRACKING = False  # link tracking hurts deliverability

# Map CSV filenames to campaign names
CAMPAIGN_NAMES = {
    "prospect_emails.csv": "Realside AI — Prospect Outreach",
    "case_study_emails.csv": "Realside AI — Case Study Match",
    "news_triggered_emails.csv": "Realside AI — News Trigger",
    "displacement_emails.csv": "Realside AI — Competitor Displacement",
    "social_outreach_emails.csv": "Realside AI — Social Warm Outreach",
    "job_signal_emails.csv": "Realside AI — Job Signal Outreach",
    "event_outreach_emails.csv": "Realside AI — Event Outreach",
    "followup_sequences.csv": "Realside AI — Follow-up Sequences",
    "objection_responses.csv": "Realside AI — Objection Responses",
    "engaged_followups.csv": "Realside AI — Engaged Follow-ups",
    "dental_dso_outreach.csv": "Realside AI — Dental DSO Outreach",
}


def api_request(method: str, endpoint: str, api_key: str, data: dict = None) -> dict:
    """Make an authenticated request to the Instantly API."""
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


PROCESSED_LEADS_PATH = "output/processed_leads.json"


def load_processed_leads(path: str = None) -> dict:
    """Load dedup tracker: {emails: set, domains: set}."""
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), PROCESSED_LEADS_PATH)
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "emails" in data:
                return {"emails": set(data["emails"]), "domains": set(data.get("domains", []))}
            # Legacy format: just a list of emails
            return {"emails": set(data), "domains": set()}
        except Exception:
            pass
    return {"emails": set(), "domains": set()}


def save_processed_leads(tracker: dict, path: str = None):
    """Persist dedup tracker to disk."""
    p = path or os.path.join(os.path.dirname(os.path.abspath(__file__)), PROCESSED_LEADS_PATH)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({
            "emails": sorted(tracker.get("emails", set())),
            "domains": sorted(tracker.get("domains", set())),
        }, f, indent=2)


def _extract_domain(email_or_domain: str) -> str:
    """Extract domain from an email address or return as-is if already a domain."""
    if "@" in email_or_domain:
        return email_or_domain.split("@")[-1].lower().strip()
    return email_or_domain.lower().strip()


GENERIC_EMAIL_PREFIXES = {
    "contact", "info", "admin", "hello", "support", "help", "sales",
    "team", "office", "general", "mail", "enquiries", "enquiry",
    "reception", "frontdesk", "billing", "accounts", "hr", "careers",
    "marketing", "press", "media", "partnerships", "feedback",
    "noreply", "no-reply", "donotreply", "do-not-reply",
}


def _is_personal_email(email: str) -> bool:
    """Check if an email is a real personal address, not a generic company one."""
    if not email or "@" not in email:
        return False
    local = email.split("@")[0].lower().strip()
    return local not in GENERIC_EMAIL_PREFIXES


def _is_owner_title(title: str) -> bool:
    """Check if a job title indicates an owner/CEO/founder."""
    title = title.lower()
    owner_keywords = ("owner", "ceo", "founder", "president", "principal",
                      "managing partner", "co-founder", "co-owner")
    return any(k in title for k in owner_keywords)


def _title_rank(title: str) -> int:
    """Rank a job title for priority selection. Lower = higher priority.

    Always picks the owner/CEO/founder first.
    """
    title = title.lower()
    if any(t in title for t in ("owner", "ceo", "founder", "president", "principal")):
        return 0
    if any(t in title for t in ("coo", "cmo", "cfo", "cto", "chief")):
        return 1
    if "evp" in title or "executive vice president" in title:
        return 2
    if "svp" in title or "senior vice president" in title:
        return 3
    if "vp" in title or "vice president" in title:
        return 4
    if "director" in title:
        return 5
    if "manager" in title:
        return 6
    return 7


def get_campaigns_by_name(api_key: str) -> dict:
    """Return dict of {campaign_name: campaign_id} for all existing campaigns."""
    result = api_request("GET", "/campaigns", api_key, {"limit": 100})
    if "error" in result:
        return {}
    if isinstance(result, list):
        items = result
    elif isinstance(result, dict):
        items = result.get("data", result.get("items", []))
        if isinstance(items, dict):
            items = items.get("items", [])
    else:
        items = []
    return {c.get("name", ""): c.get("id", "") for c in items if c.get("name") and c.get("id")}


def list_campaigns(api_key: str):
    """List existing campaigns."""
    result = api_request("GET", "/campaigns", api_key, {"limit": 50})
    if "error" in result:
        print(f"Error listing campaigns: {result['error']}")
        return []

    campaigns = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(campaigns, list):
        for c in campaigns:
            status = c.get("status", "unknown")
            name = c.get("name", "Unnamed")
            cid = c.get("id", "?")
            print(f"  [{status}] {name} (ID: {cid})")
        return campaigns
    elif isinstance(campaigns, dict) and "items" in campaigns:
        for c in campaigns["items"]:
            status = c.get("status", "unknown")
            name = c.get("name", "Unnamed")
            cid = c.get("id", "?")
            print(f"  [{status}] {name} (ID: {cid})")
        return campaigns["items"]
    else:
        print(f"  Response: {json.dumps(result, indent=2)[:500]}")
        return []


def list_accounts(api_key: str) -> list:
    """List connected email accounts."""
    result = api_request("GET", "/accounts", api_key, {"limit": 50})
    if "error" in result:
        print(f"Error listing accounts: {result['error']}")
        return []

    accounts = result.get("data", result) if isinstance(result, dict) else result
    if isinstance(accounts, list):
        return accounts
    elif isinstance(accounts, dict) and "items" in accounts:
        return accounts["items"]
    return []


def delete_lead(api_key: str, campaign_id: str, lead_email: str) -> bool:
    """Remove a lead from a campaign."""
    url = f"{BASE_URL}/leads"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"campaign_id": campaign_id, "email": lead_email, "delete_all_from_company": False}
    try:
        resp = requests.delete(url, headers=headers, json=payload, timeout=30)
        if resp.status_code in (200, 204):
            return True
        # Try alternate endpoint
        url2 = f"{BASE_URL}/leads/{lead_email}"
        resp2 = requests.delete(url2, headers=headers, json={"campaign_id": campaign_id}, timeout=30)
        return resp2.status_code in (200, 204)
    except Exception:
        return False


def cleanup_campaign(api_key: str, campaign_id: str, campaign_name: str,
                     dry_run: bool = False) -> dict:
    """Remove duplicate and non-owner leads from a campaign.

    Keeps only 1 lead per domain, must be owner/CEO/founder.
    """
    print(f"\n  Cleaning up: {campaign_name} ({campaign_id})")

    # Fetch all leads in the campaign
    leads = []
    skip = 0
    while True:
        result = api_request("GET", "/leads", api_key, {
            "campaign_id": campaign_id, "limit": 100, "skip": skip
        })
        if "error" in result:
            print(f"    Could not fetch leads: {result.get('error', '')[:100]}")
            break
        items = result.get("data", result.get("items", []))
        if isinstance(result, list):
            items = result
        if not items:
            break
        leads.extend(items)
        skip += len(items)
        if len(items) < 100:
            break

    if not leads:
        print("    No leads found in campaign.")
        return {"campaign": campaign_name, "total": 0, "removed": 0, "kept": 0}

    print(f"    Found {len(leads)} leads")

    # Group by domain, keep best owner per domain
    domain_leads = {}
    for lead in leads:
        email = lead.get("email", "").lower()
        if not email:
            continue
        domain = email.split("@")[-1] if "@" in email else ""
        if not domain:
            continue

        title = (lead.get("custom_variables", {}).get("contact_title", "")
                 or lead.get("title", "") or "").lower()
        is_owner = _is_owner_title(title)

        if domain not in domain_leads:
            domain_leads[domain] = []
        domain_leads[domain].append({
            "email": email,
            "name": f"{lead.get('first_name', '')} {lead.get('last_name', '')}".strip(),
            "title": title,
            "is_owner": is_owner,
            "rank": _title_rank(title),
        })

    # Decide who to keep vs remove
    to_remove = []
    to_keep = []
    for domain, contacts in domain_leads.items():
        # Sort by rank (lower = better)
        contacts.sort(key=lambda c: c["rank"])
        # Keep the best one (if they're an owner)
        best = contacts[0]
        if best["is_owner"]:
            to_keep.append(best)
            to_remove.extend(contacts[1:])
        else:
            # No owners — remove all
            to_remove.extend(contacts)

    print(f"    Keeping {len(to_keep)} owner leads, removing {len(to_remove)} non-owner/duplicates")

    removed = 0
    for lead in to_remove:
        if dry_run:
            print(f"    [DRY-RUN] Would remove: {lead['email']} ({lead['title'] or 'no title'})")
        else:
            if delete_lead(api_key, campaign_id, lead["email"]):
                removed += 1
                print(f"    Removed: {lead['email']} ({lead['title'] or 'no title'})")
            else:
                print(f"    Failed to remove: {lead['email']}")
            time.sleep(0.3)

    return {
        "campaign": campaign_name,
        "total": len(leads),
        "kept": len(to_keep),
        "removed": removed if not dry_run else len(to_remove),
    }


def delete_campaign(api_key: str, campaign_id: str) -> bool:
    """Delete a campaign. Must use DELETE without Content-Type header."""
    url = f"{BASE_URL}/campaigns/{campaign_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.delete(url, headers=headers, timeout=30)
        return resp.status_code in (200, 204)
    except Exception:
        return False


def activate_campaign(api_key: str, campaign_id: str) -> bool:
    """Activate a campaign in Instantly (move from DRAFT to active)."""
    # Strategy 1: dedicated activate endpoint
    result = api_request("POST", f"/campaigns/{campaign_id}/activate", api_key)
    if "error" not in result:
        print(f"  Campaign {campaign_id} activated.")
        return True

    # Strategy 2: campaigns/activate bulk endpoint
    result = api_request("POST", "/campaigns/activate", api_key, {"id": campaign_id})
    if "error" not in result:
        print(f"  Campaign {campaign_id} activated.")
        return True

    print(f"  Warning: Could not auto-activate campaign {campaign_id}: {result.get('error', '')[:100]}")
    print(f"  → Manually activate in Instantly.ai dashboard")
    return False


def create_campaign(api_key: str, name: str, sending_accounts: list = None,
                    campaign_options: dict = None) -> str:
    """Create a new campaign with optimized settings for cold email deliverability.

    Optimizations:
    - Two send windows: morning (7-9 AM) + afternoon (1-3 PM) — peak open times
    - Mon-Fri only, no weekends
    - All sending accounts rotated for volume + deliverability
    - Conservative daily limits per account (30/day default)
    - Link tracking OFF (hurts deliverability), open tracking ON
    - 90-day campaign duration
    """
    opts = campaign_options or {}
    timezone = opts.get("timezone", DEFAULT_TIMEZONE)
    daily_limit = opts.get("daily_limit_per_account", DEFAULT_DAILY_LIMIT_PER_ACCOUNT)
    duration_days = opts.get("campaign_duration_days", 90)

    # Send windows — split into two blocks for natural spacing
    morning_start = opts.get("morning_start", "07:00")
    morning_end = opts.get("morning_end", "09:00")
    afternoon_start = opts.get("afternoon_start", "13:00")
    afternoon_end = opts.get("afternoon_end", "15:00")

    start_date = datetime.now().strftime("%Y-%m-%d")
    end_date = (datetime.now() + timedelta(days=duration_days)).strftime("%Y-%m-%d")

    weekdays = {
        "0": False,  # Sunday
        "1": True,   # Monday
        "2": True,   # Tuesday
        "3": True,   # Wednesday
        "4": True,   # Thursday
        "5": True,   # Friday
        "6": False,  # Saturday
    }

    payload = {
        "name": name,
        "campaign_schedule": {
            "start_date": start_date,
            "end_date": end_date,
            "schedules": [
                {
                    "name": "Morning Window (7-9 AM)",
                    "timing": {"from": morning_start, "to": morning_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
                {
                    "name": "Afternoon Window (1-3 PM)",
                    "timing": {"from": afternoon_start, "to": afternoon_end},
                    "timezone": timezone,
                    "days": weekdays,
                },
            ],
        },
        # Use custom variables so each lead gets a fully unique email
        "sequences": [
            {
                "steps": [
                    {
                        "type": "email",
                        "delay": 0,
                        "variants": [
                            {
                                "subject": "{{custom_subject}}",
                                "body": "{{custom_body}}",
                            }
                        ],
                    }
                ]
            }
        ],
    }

    # Attach ALL sending accounts for rotation (spreads volume, protects domains)
    if sending_accounts:
        payload["sending_accounts"] = sending_accounts
        print(f"  Rotating across {len(sending_accounts)} sending accounts")

    # Campaign-level settings (daily limit, tracking)
    campaign_settings = {}
    if daily_limit:
        campaign_settings["daily_limit"] = daily_limit
    if not opts.get("link_tracking", DEFAULT_LINK_TRACKING):
        campaign_settings["link_tracking"] = False
    if opts.get("open_tracking", DEFAULT_OPEN_TRACKING):
        campaign_settings["open_tracking"] = True
    if campaign_settings:
        payload["campaign_settings"] = campaign_settings

    result = api_request("POST", "/campaigns", api_key, payload)
    if "error" in result:
        print(f"  Failed to create campaign '{name}': {result['error']}")
        return ""

    campaign_id = result.get("id", "")
    if campaign_id:
        print(f"  Created campaign: {name} (ID: {campaign_id})")
        print(f"    Schedule: {morning_start}-{morning_end} + {afternoon_start}-{afternoon_end} Mon-Fri ({timezone})")
        print(f"    Daily limit/account: {daily_limit} | Duration: {duration_days} days")
    return campaign_id


def read_pipeline_csv(filepath: str) -> list[dict]:
    """Read a pipeline output CSV and normalize column names."""
    rows = []
    with open(filepath, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def csv_to_leads(rows: list[dict]) -> list[dict]:
    """Convert pipeline CSV rows to Instantly lead format with custom variables."""
    leads = []
    for row in rows:
        # Extract contact info — handle different column name conventions
        email = (
            row.get("contact_email", "")
            or row.get("email", "")
            or row.get("prospect_email", "")
        )
        first_name = ""
        last_name = ""
        contact_name = (
            row.get("contact_name", "")
            or row.get("prospect_contact", "")
            or ""
        )
        if contact_name:
            parts = contact_name.strip().split(" ", 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ""

        company = (
            row.get("company_name", "")
            or row.get("prospect_company", "")
            or ""
        )
        domain = row.get("domain", "")
        subject = row.get("subject", "")
        body = row.get("body", "")
        title = row.get("contact_title", "")
        personalization = row.get("personalization_hook", "")

        # Build the lead object
        lead = {
            "first_name": first_name,
            "last_name": last_name,
            "company_name": company,
            "website": domain if domain and not domain.startswith("http") else domain,
            "custom_variables": {
                "custom_subject": subject,
                "custom_body": body,
                "contact_title": title,
                "personalization_hook": personalization,
                "domain": domain,
                "full_name": contact_name,
            },
        }

        # Set email — must be a real personal email, never a generic/company address
        if email and _is_personal_email(email):
            lead["email"] = email
        else:
            # No real personal email — skip this lead entirely
            # Generic addresses (contact@, info@, admin@, hello@) are not uploaded
            continue

        leads.append(lead)

    return leads


def upload_leads(api_key: str, campaign_id: str, leads: list[dict]) -> int:
    """Upload leads one at a time to a campaign (Instantly V2 API format)."""
    total_uploaded = 0

    for i, lead in enumerate(leads):
        payload = {
            "campaign": campaign_id,
            "email": lead.get("email", ""),
            "first_name": lead.get("first_name", ""),
            "last_name": lead.get("last_name", ""),
            "company_name": lead.get("company_name", ""),
            "website": lead.get("website", ""),
            "personalization": lead.get("custom_variables", {}).get("personalization_hook", ""),
            "custom_variables": lead.get("custom_variables", {}),
        }

        result = api_request("POST", "/leads", api_key, payload)
        if "error" in result:
            print(f"  Error uploading lead {i + 1} ({lead.get('email', '?')}): {result['error'][:100]}")
        else:
            total_uploaded += 1

        # Rate limit every 5 leads
        if (i + 1) % 5 == 0:
            time.sleep(RATE_LIMIT_DELAY)
            if (i + 1) % 20 == 0:
                print(f"  Uploaded {total_uploaded}/{i + 1} leads...")

    return total_uploaded


def process_csv(api_key: str, csv_path: str, dry_run: bool = False,
                sending_accounts: list = None, campaign_options: dict = None,
                auto_activate: bool = False, update_existing: bool = False,
                existing_campaigns: dict = None, processed_leads: set = None) -> dict:
    """Process a single CSV: create campaign + upload leads."""
    filename = os.path.basename(csv_path)
    campaign_name = CAMPAIGN_NAMES.get(filename, f"Realside AI — {filename.replace('.csv', '').replace('_', ' ').title()}")

    print(f"\n{'='*60}")
    print(f"Processing: {filename}")
    print(f"Campaign:   {campaign_name}")
    print(f"{'='*60}")

    # Read CSV
    rows = read_pipeline_csv(csv_path)
    if not rows:
        print("  No rows found, skipping.")
        return {"name": campaign_name, "status": "skipped", "reason": "empty CSV"}

    # Convert to leads
    leads = csv_to_leads(rows)
    needs_email = sum(1 for l in leads if l.get("custom_variables", {}).get("needs_real_email") == "true")

    # Deduplicate: 1 lead per company, always pick the highest-ranking contact (owner/CEO first)
    if processed_leads:
        processed_emails = processed_leads.get("emails", set()) if isinstance(processed_leads, dict) else processed_leads
        processed_domains = processed_leads.get("domains", set()) if isinstance(processed_leads, dict) else set()
    else:
        processed_emails = set()
        processed_domains = set()

    before = len(leads)

    # Group leads by domain, pick the best contact per domain
    domain_best = {}  # domain -> best lead
    no_domain_leads = []
    for lead in leads:
        email = lead.get("email", "").lower()
        domain = _extract_domain(lead.get("website", "") or lead.get("email", ""))

        # Skip already-uploaded emails
        if email and email in processed_emails:
            continue
        # Skip already-uploaded domains
        if domain and domain in processed_domains:
            continue

        if not domain:
            no_domain_leads.append(lead)
            continue

        # Rank by title: owner/CEO wins
        title = (lead.get("custom_variables", {}).get("contact_title", "") or "").lower()
        rank = _title_rank(title)

        if domain not in domain_best or rank < domain_best[domain][0]:
            domain_best[domain] = (rank, lead)

    leads = [best[1] for best in domain_best.values()] + no_domain_leads
    skipped = before - len(leads)
    if skipped:
        print(f"  Skipped {skipped} duplicate leads (1 per company, owner/CEO priority)")

    # Filter: owner titles only
    before_owner = len(leads)
    leads = [l for l in leads if _is_owner_title(
        l.get("custom_variables", {}).get("contact_title", "") or ""
    ) or not l.get("custom_variables", {}).get("contact_title")]
    owner_skipped = before_owner - len(leads)
    if owner_skipped:
        print(f"  Skipped {owner_skipped} non-owner leads (owners only)")

    # Filter: employee count range (from config or campaign_options)
    emp_min = (campaign_options or {}).get("employee_min", 0)
    emp_max = (campaign_options or {}).get("employee_max", 0)
    if emp_min or emp_max:
        before_emp = len(leads)
        filtered = []
        for l in leads:
            emp_count = l.get("custom_variables", {}).get("employee_count", "")
            if emp_count:
                try:
                    count = int(str(emp_count).replace(",", "").strip())
                    if emp_min and count < emp_min:
                        continue
                    if emp_max and count > emp_max:
                        continue
                except (ValueError, TypeError):
                    pass  # Can't parse, let it through
            filtered.append(l)
        leads = filtered
        emp_skipped = before_emp - len(leads)
        if emp_skipped:
            print(f"  Skipped {emp_skipped} leads outside employee range ({emp_min}-{emp_max})")

    print(f"  Leads: {len(leads)} new to upload")
    if needs_email:
        print(f"  Warning: {needs_email} leads have placeholder emails (need enrichment)")

    if not leads:
        return {"name": campaign_name, "status": "skipped", "reason": "all leads already uploaded",
                "leads_uploaded": 0, "leads_total": 0, "new_emails": set(), "new_domains": set()}

    if dry_run:
        print("  [DRY-RUN] Would upload leads to campaign")
        for i, lead in enumerate(leads[:3]):
            print(f"    Lead {i+1}: {lead.get('first_name', '?')} {lead.get('last_name', '')} "
                  f"@ {lead.get('company_name', '?')} ({lead.get('email', 'no email')})")
            subj = lead.get('custom_variables', {}).get('custom_subject', '')
            if subj:
                print(f"      Subject: {subj[:70]}")
        if len(leads) > 3:
            print(f"    ... and {len(leads) - 3} more")
        return {"name": campaign_name, "status": "dry-run", "leads": len(leads), "new_emails": set(), "new_domains": set()}

    # Get or create campaign — ALWAYS check for existing campaign first to prevent duplicates
    # Fetch existing campaigns if not already provided
    if existing_campaigns is None:
        existing_campaigns = get_campaigns_by_name(api_key)

    campaign_id = existing_campaigns.get(campaign_name, "")
    if campaign_id:
        print(f"  Adding to existing campaign: {campaign_name} (ID: {campaign_id})")
    else:
        campaign_id = create_campaign(api_key, campaign_name, sending_accounts, campaign_options)
        if not campaign_id:
            return {"name": campaign_name, "status": "failed", "reason": "campaign creation failed",
                    "new_emails": set(), "new_domains": set()}

    # Upload leads
    uploaded = upload_leads(api_key, campaign_id, leads)
    print(f"  Total uploaded: {uploaded}/{len(leads)}")

    # Track newly uploaded emails + domains for dedup
    new_emails = {l.get("email", "").lower() for l in leads if l.get("email")}
    new_domains = {_extract_domain(l.get("website", "") or l.get("email", ""))
                   for l in leads if l.get("website") or l.get("email")}

    # Auto-activate if requested
    activated = False
    if auto_activate and uploaded > 0:
        print(f"  Auto-activating campaign...")
        activated = activate_campaign(api_key, campaign_id)

    return {
        "name": campaign_name,
        "campaign_id": campaign_id,
        "status": "success",
        "leads_uploaded": uploaded,
        "leads_total": len(leads),
        "needs_email_enrichment": needs_email,
        "activated": activated,
        "new_emails": new_emails,
        "new_domains": new_domains,
    }


def main():
    parser = argparse.ArgumentParser(description="Upload pipeline emails to Instantly.ai")
    parser.add_argument("--api-key", required=True, help="Instantly API key (Bearer token)")
    parser.add_argument("--csvs", nargs="*", help="Specific CSV files to upload (default: all in output/)")
    parser.add_argument("--output-dir", default="output", help="Pipeline output directory")
    parser.add_argument("--sending-account", default=None, help="Email account to send from")
    parser.add_argument("--dry-run", action="store_true", help="Preview without creating campaigns")
    parser.add_argument("--auto-activate", action="store_true",
                        help="Automatically activate campaigns after upload (skip DRAFT mode)")
    parser.add_argument("--update-existing", action="store_true",
                        help="Add leads to existing campaigns instead of creating new ones")
    parser.add_argument("--campaign-options", default=None,
                        help="JSON string of campaign options (timezone, daily_limit_per_account, etc.)")
    parser.add_argument("--list-campaigns", action="store_true", help="List existing campaigns")
    parser.add_argument("--list-accounts", action="store_true", help="List connected email accounts")
    parser.add_argument("--cleanup", action="store_true",
                        help="Remove non-owner and duplicate leads from all campaigns")
    args = parser.parse_args()

    if args.cleanup:
        print("Cleaning up campaigns: removing non-owner and duplicate leads")
        print("=" * 60)
        campaigns = get_campaigns_by_name(args.api_key)
        if not campaigns:
            print("No campaigns found.")
            return
        results = []
        for name, cid in campaigns.items():
            result = cleanup_campaign(args.api_key, cid, name, dry_run=args.dry_run)
            results.append(result)
        print(f"\n{'='*60}")
        print("CLEANUP SUMMARY")
        print(f"{'='*60}")
        for r in results:
            print(f"  {r['campaign']}: {r['kept']} kept, {r['removed']} removed (of {r['total']})")
        return

    if args.list_campaigns:
        print("Existing campaigns:")
        list_campaigns(args.api_key)
        return

    if args.list_accounts:
        print("Connected email accounts:")
        accounts = list_accounts(args.api_key)
        for a in accounts:
            email = a.get("email", "?")
            status = a.get("status", "unknown")
            print(f"  [{status}] {email}")
        return

    # Determine which CSVs to upload
    if args.csvs:
        csv_files = args.csvs
    else:
        output_dir = args.output_dir
        csv_files = []
        for f in sorted(os.listdir(output_dir)):
            if f.endswith(".csv") and not f.startswith("_") and f in CAMPAIGN_NAMES:
                csv_files.append(os.path.join(output_dir, f))

    if not csv_files:
        print("No CSV files found to upload.")
        print(f"Expected files in {args.output_dir}/: {', '.join(CAMPAIGN_NAMES.keys())}")
        sys.exit(1)

    print(f"Instantly.ai Campaign Uploader")
    print(f"{'='*60}")
    print(f"Files to process: {len(csv_files)}")
    if args.dry_run:
        print("Mode: DRY-RUN (no changes will be made)")
    print()

    # Check API connectivity
    print("Checking API access...")
    accounts = list_accounts(args.api_key)
    if not accounts:
        print("Warning: Could not list accounts. Check your API key and permissions.")
    else:
        print(f"  Found {len(accounts)} connected account(s)")
        for a in accounts:
            print(f"    - {a.get('email', '?')}")

    # Collect ALL sending accounts for rotation (maximizes volume + deliverability)
    if args.sending_account:
        sending_accounts = [args.sending_account]
    elif accounts:
        sending_accounts = [a.get("email", "") for a in accounts if a.get("email")]
        print(f"  Rotating across ALL {len(sending_accounts)} connected accounts")
    else:
        sending_accounts = []

    # Campaign options (can be overridden via --campaign-options JSON)
    campaign_options = {
        "timezone": DEFAULT_TIMEZONE,
        "daily_limit_per_account": DEFAULT_DAILY_LIMIT_PER_ACCOUNT,
        "campaign_duration_days": 90,
        "morning_start": "07:00",
        "morning_end": "09:00",
        "afternoon_start": "13:00",
        "afternoon_end": "15:00",
        "open_tracking": DEFAULT_OPEN_TRACKING,
        "link_tracking": DEFAULT_LINK_TRACKING,
    }
    if args.campaign_options:
        try:
            overrides = json.loads(args.campaign_options)
            campaign_options.update(overrides)
            print(f"  Campaign options overridden: {list(overrides.keys())}")
        except json.JSONDecodeError:
            print(f"  Warning: Could not parse --campaign-options JSON, using defaults")

    # Load dedup tracker and pre-fetch existing campaigns (prevents ALL duplicate campaign creation)
    processed_leads = load_processed_leads() if not args.dry_run else {"emails": set(), "domains": set()}
    print("  Fetching existing campaigns (to prevent duplicates)...")
    existing_campaigns = get_campaigns_by_name(args.api_key) if not args.dry_run else {}
    if existing_campaigns:
        print(f"  Found {len(existing_campaigns)} existing campaigns — will update, not duplicate")

    # Process each CSV
    results = []
    all_new_emails = set()
    for csv_path in csv_files:
        if not os.path.exists(csv_path):
            print(f"\n  Skipping {csv_path} (file not found)")
            continue
        result = process_csv(
            args.api_key, csv_path, args.dry_run, sending_accounts,
            campaign_options, auto_activate=args.auto_activate,
            update_existing=args.update_existing,
            existing_campaigns=existing_campaigns,
            processed_leads=processed_leads,
        )
        results.append(result)
        # Accumulate newly uploaded emails for dedup persistence
        all_new_emails.update(result.get("new_emails", set()))

    # Persist dedup tracker (emails + domains)
    all_new_domains = set()
    for r in results:
        all_new_emails.update(r.get("new_emails", set()))
        all_new_domains.update(r.get("new_domains", set()))

    if (all_new_emails or all_new_domains) and not args.dry_run:
        tracker = processed_leads if isinstance(processed_leads, dict) else {"emails": processed_leads, "domains": set()}
        tracker["emails"].update(all_new_emails)
        tracker["domains"].update(all_new_domains)
        save_processed_leads(tracker)
        print(f"\n  Dedup tracker updated: {len(tracker['emails'])} emails, {len(tracker['domains'])} domains tracked")

    # Summary
    print(f"\n{'='*60}")
    print("UPLOAD SUMMARY")
    print(f"{'='*60}")
    for r in results:
        status_icon = "✓" if r["status"] == "success" else "○" if r["status"] == "dry-run" else "✗"
        print(f"  [{status_icon}] {r['name']}: {r['status']}")
        if r.get("leads_uploaded"):
            print(f"      {r['leads_uploaded']}/{r['leads_total']} leads uploaded")
        if r.get("needs_email_enrichment", 0) > 0:
            print(f"      ⚠ {r['needs_email_enrichment']} leads need real email addresses")
        if r.get("campaign_id"):
            activated_str = " [ACTIVATED]" if r.get("activated") else " [DRAFT]"
            print(f"      Campaign ID: {r['campaign_id']}{activated_str}")

    if args.auto_activate:
        print(f"\n✓ Auto-activate was ON — campaigns are live.")
    else:
        print(f"\n⚠ IMPORTANT: Campaigns are created in DRAFT mode.")
        print(f"  → Log in to Instantly.ai to review and activate each campaign.")
    print(f"  → Leads with placeholder emails (contact@domain.com) need real addresses.")
    print()


if __name__ == "__main__":
    main()
