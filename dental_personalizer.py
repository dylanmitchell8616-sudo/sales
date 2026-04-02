#!/usr/bin/env python3
"""
Dental Campaign Hyper-Personalizer
====================================
Takes the dental leads CSV and generates deeply personalized emails using
Claude + LinkedIn/website data. Each email references something specific
about the dentist or their practice.

Usage:
    python dental_personalizer.py --input output/leads_raw.csv --limit 50
    python dental_personalizer.py --input output/leads_raw.csv --batch-size 10
    python dental_personalizer.py --input output/leads_raw.csv --all

Output: output/dental_personalized_emails.csv (Instantly-ready format)
"""

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from anthropic import Anthropic

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"


def load_config():
    with open(BASE_DIR / "config.json") as f:
        return json.load(f)


def load_leads(path, limit=None):
    """Load leads from Instantly export CSV."""
    leads = []
    with open(path) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            if limit and i >= limit:
                break
            # Skip leads without email
            if not row.get("Email"):
                continue
            leads.append({
                "email": row["Email"].strip(),
                "first_name": row.get("First Name", "").strip(),
                "last_name": row.get("Last Name", "").strip(),
                "job_title": row.get("jobTitle", "").strip(),
                "linkedin": row.get("linkedIn", "").strip(),
                "website": row.get("website", "").strip(),
                "company": row.get("companyName", "").strip(),
                "location": row.get("location", "").strip(),
                "campaign": row.get("Campaign Name", "").strip(),
            })
    return leads


def scrape_website_snippet(url, timeout=8):
    """Grab a quick snippet from the practice website for personalization."""
    if not url or url in ("", "Not Found"):
        return ""
    try:
        if not url.startswith("http"):
            url = "https://" + url
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
        })
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            html = resp.read().decode("utf-8", errors="ignore")[:15000]

        # Extract useful text
        # Remove scripts and styles
        html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
        html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL)
        # Get text
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:2000]
    except Exception:
        return ""


def scrape_websites_parallel(leads, max_workers=10):
    """Scrape all unique websites in parallel."""
    unique_sites = {}
    for lead in leads:
        site = lead.get("website", "")
        if site and site not in unique_sites and site != "Not Found":
            unique_sites[site] = None

    if not unique_sites:
        return {}

    print(f"  Scraping {len(unique_sites)} unique practice websites...")

    def _scrape(url):
        return url, scrape_website_snippet(url)

    results = {}
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_scrape, url): url for url in unique_sites}
        for future in as_completed(futures):
            url, snippet = future.result()
            results[url] = snippet

    found = sum(1 for v in results.values() if v)
    print(f"  Got content from {found}/{len(unique_sites)} sites")
    return results


def generate_personalized_email(client, lead, site_snippet, config):
    """Generate a hyper-personalized email for one lead using Claude."""

    # Build context from what we know
    context_parts = []
    if lead["job_title"]:
        context_parts.append(f"Title: {lead['job_title']}")
    if lead["company"]:
        context_parts.append(f"Practice: {lead['company']}")
    if lead["location"]:
        context_parts.append(f"Location: {lead['location']}")
    if lead["linkedin"]:
        context_parts.append(f"LinkedIn: {lead['linkedin']}")
    if site_snippet:
        context_parts.append(f"Website content snippet: {site_snippet[:1000]}")

    context = "\n".join(context_parts) if context_parts else "No additional context available."

    prompt = f"""Write a personalized cold email to Dr. {lead['first_name']} {lead['last_name']}.

KNOWN INFO ABOUT THIS PERSON:
{context}

TEMPLATE STRUCTURE (keep this flow but make each line feel personal):
- Open with something specific about THEIR practice (from website or title)
- Mention you tried calling their office (or that patients calling their office might face the same issue)
- Stat: clinics lose 20-40% of new patient calls to voicemail
- What we do: custom AI receptionist that answers every call 24/7, books appointments, confirms insurance, sends follow-up texts
- CTA: ask what days work for a call (never include a calendly or scheduling link)

RULES:
- Subject line: short, personal, lowercase style. Reference their practice name or specialty if known.
- Under 90 words in the body
- Must feel like a real person wrote it, not a template
- If you know their specialty from the website (cosmetic, pediatric, implants, orthodontics, etc.), reference it
- If you see services/specialties on their website, mention ONE specifically
- No dashes (--), no emojis
- Never say "I hope this email finds you well" or any generic opener
- Sign off as just "Dylan"
- If their title says Owner/Dentist at a DSO (Affordable Dentures, Aspen Dental, PDS), acknowledge they're part of a larger network but personalize to their location

Return ONLY valid JSON: {{"subject": "...", "body": "..."}}
No markdown wrapping."""

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}]
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def process_batch(leads, site_snippets, config, start_idx=0):
    """Process a batch of leads and return personalized emails."""
    client = Anthropic(api_key=config["anthropic_api_key"])
    results = []

    for i, lead in enumerate(leads):
        idx = start_idx + i + 1
        name = f"{lead['first_name']} {lead['last_name']}"
        print(f"  [{idx}] {name} at {lead['company'] or 'Unknown Practice'}...", end=" ", flush=True)

        snippet = site_snippets.get(lead.get("website", ""), "")

        try:
            email_data = generate_personalized_email(client, lead, snippet, config)
            results.append({
                "email": lead["email"],
                "first_name": lead["first_name"],
                "last_name": lead["last_name"],
                "company_name": lead["company"],
                "job_title": lead["job_title"],
                "website": lead["website"],
                "linkedin": lead["linkedin"],
                "location": lead["location"],
                "subject": email_data["subject"],
                "body": email_data["body"],
                "personalized": True
            })
            print("done")
        except Exception as e:
            print(f"ERROR: {e}")
            # Fallback to template
            results.append({
                "email": lead["email"],
                "first_name": lead["first_name"],
                "last_name": lead["last_name"],
                "company_name": lead["company"],
                "job_title": lead["job_title"],
                "website": lead["website"],
                "linkedin": lead["linkedin"],
                "location": lead["location"],
                "subject": f"quick question about {lead['company'] or 'your practice'}",
                "body": (
                    f"Hi Dr. {lead['last_name']},\n\n"
                    f"I tried calling {lead['company'] or 'your office'} and couldn't get through, "
                    f"which is actually why I'm reaching out.\n\n"
                    f"Most clinics lose 20-40% of new patient calls to voicemail. "
                    f"Those patients just call the next office on Google.\n\n"
                    f"My team builds custom AI receptionists for practices like "
                    f"{lead['company'] or 'yours'} that answer every call 24/7, "
                    f"book appointments, confirm insurance, and send follow-up texts.\n\n"
                    f"Which days work for you this week to walk through the demo we made for you?\n\n"
                    f"Dylan"
                ),
                "personalized": False
            })

    return results


def write_instantly_csv(results, output_path):
    """Write results in Instantly-ready CSV format."""
    fieldnames = [
        "email", "first_name", "last_name", "company_name",
        "subject", "body", "website", "linkedin",
        "job_title", "location", "personalized"
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: r.get(k, "") for k in fieldnames})


def main():
    parser = argparse.ArgumentParser(description="Dental campaign hyper-personalizer")
    parser.add_argument("--input", default="output/leads_raw.csv", help="Input leads CSV")
    parser.add_argument("--output", default="output/dental_personalized_emails.csv", help="Output CSV")
    parser.add_argument("--limit", type=int, help="Limit number of leads to process")
    parser.add_argument("--offset", type=int, default=0, help="Skip first N leads")
    parser.add_argument("--batch-size", type=int, default=50, help="Process in batches of N")
    parser.add_argument("--all", action="store_true", help="Process all leads")
    parser.add_argument("--no-scrape", action="store_true", help="Skip website scraping")
    parser.add_argument("--append", action="store_true", help="Append to existing output file")
    args = parser.parse_args()

    config = load_config()
    leads = load_leads(args.input, limit=args.limit if not args.all else None)

    if args.offset:
        leads = leads[args.offset:]

    print(f"\n{'='*60}")
    print(f"  DENTAL CAMPAIGN PERSONALIZER")
    print(f"  {len(leads)} leads to process")
    print(f"{'='*60}\n")

    # Scrape websites
    if not args.no_scrape:
        site_snippets = scrape_websites_parallel(leads)
    else:
        site_snippets = {}
        print("  Skipping website scraping")

    # Process in batches
    all_results = []

    # Load existing results if appending
    if args.append and os.path.exists(args.output):
        with open(args.output) as f:
            reader = csv.DictReader(f)
            all_results = list(reader)
        processed_emails = {r["email"] for r in all_results}
        leads = [l for l in leads if l["email"] not in processed_emails]
        print(f"  {len(all_results)} already processed, {len(leads)} remaining\n")

    batch_size = args.batch_size
    for batch_start in range(0, len(leads), batch_size):
        batch = leads[batch_start:batch_start + batch_size]
        batch_num = batch_start // batch_size + 1
        total_batches = (len(leads) + batch_size - 1) // batch_size

        print(f"\n--- Batch {batch_num}/{total_batches} ({len(batch)} leads) ---")

        results = process_batch(batch, site_snippets, config, start_idx=batch_start + args.offset)
        all_results.extend(results)

        # Save after each batch (incremental)
        os.makedirs(os.path.dirname(args.output) if os.path.dirname(args.output) else "output", exist_ok=True)
        write_instantly_csv(all_results, args.output)
        print(f"  Saved {len(all_results)} total emails to {args.output}")

    # Summary
    personalized = sum(1 for r in all_results if r.get("personalized") in (True, "True"))
    print(f"\n{'='*60}")
    print(f"  COMPLETE: {len(all_results)} emails generated")
    print(f"  Personalized: {personalized} | Fallback template: {len(all_results) - personalized}")
    print(f"  Output: {args.output}")
    print(f"\n  Upload to Instantly:")
    print(f"    python instantly_uploader.py --input {args.output} --campaign 'Dental AI Receptionist'")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
