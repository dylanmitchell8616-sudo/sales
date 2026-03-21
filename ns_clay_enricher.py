#!/usr/bin/env python3
"""
Nova Scotia Leads — Clay MCP Enricher
========================================
Enriches NS leads with owner/CEO/founder contact info using Clay MCP tools.

Since Clay is an MCP tool (only callable from within Claude), this script
supports two modes:

1. PREPARE mode (default):
   Reads ns_leads_all.csv, identifies leads needing enrichment, and writes
   a batch manifest (output/ns_clay_batch.json) with the Clay calls needed.
   Then use Claude to process the batch with: --process-batch

2. PROCESS mode (--process-batch):
   Reads the batch manifest + a results file (output/ns_clay_results.json)
   written by the Clay MCP orchestration, merges enrichment data back into
   the CSV, and writes output/ns_leads_enriched.csv.

3. INTERACTIVE mode (--interactive):
   Prints one lead at a time so you can copy/paste Clay MCP calls in Claude
   and manually enter results. Good for small batches.

Usage:
    python ns_clay_enricher.py                      # Prepare batch manifest
    python ns_clay_enricher.py --process-batch      # Merge results into CSV
    python ns_clay_enricher.py --interactive         # One-by-one mode
    python ns_clay_enricher.py --dry-run             # Preview without writing
    python ns_clay_enricher.py --stats               # Show current enrichment stats

The recommended workflow with Claude:
    1. Run: python ns_clay_enricher.py
    2. Ask Claude to process output/ns_clay_batch.json using Clay MCP tools
    3. Claude writes results to output/ns_clay_results.json
    4. Run: python ns_clay_enricher.py --process-batch
"""

import argparse
import csv
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "output"
INPUT_CSV = OUTPUT_DIR / "ns_leads_all.csv"
OUTPUT_CSV = OUTPUT_DIR / "ns_leads_enriched.csv"
BATCH_FILE = OUTPUT_DIR / "ns_clay_batch.json"
RESULTS_FILE = OUTPUT_DIR / "ns_clay_results.json"
LOG_FILE = OUTPUT_DIR / "ns_clay_enricher.log"

# Owner-level titles we want (priority order)
TARGET_TITLES = [
    "owner", "founder", "ceo", "president", "principal",
    "managing partner", "co-founder", "co-owner", "managing director",
    "director", "general manager",
]

# Input CSV fields from NS scraper
INPUT_FIELDS = [
    "company_name", "email", "phone", "website", "domain", "address",
    "city", "province", "rating", "reviews", "category", "niche",
    "niche_label", "services", "google_maps_url",
]

# New columns we add
ENRICHMENT_FIELDS = [
    "owner_first_name", "owner_last_name", "owner_email", "owner_title",
]

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def add_file_logging():
    """Add file handler after we know output dir exists."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(LOG_FILE, mode="a", encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)


def read_input_csv() -> list[dict]:
    """Read the NS leads CSV."""
    if not INPUT_CSV.exists():
        logger.error(f"Input CSV not found: {INPUT_CSV}")
        logger.info("Run the NS scraper first to generate ns_leads_all.csv")
        sys.exit(1)

    rows = []
    with open(INPUT_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    logger.info(f"Read {len(rows)} leads from {INPUT_CSV}")
    return rows


def needs_enrichment(row: dict) -> bool:
    """Check if a lead needs Clay enrichment."""
    # Skip if already has an owner email
    owner_email = row.get("owner_email", "").strip()
    if owner_email and "@" in owner_email:
        return False

    # Must have a domain or website to look up
    domain = row.get("domain", "").strip()
    website = row.get("website", "").strip()
    if not domain and not website:
        return False

    return True


def get_domain(row: dict) -> str:
    """Extract clean domain from a lead row."""
    domain = row.get("domain", "").strip()
    if domain:
        return domain

    website = row.get("website", "").strip()
    if website:
        # Strip protocol and path
        d = website.replace("https://", "").replace("http://", "")
        d = d.split("/")[0].strip()
        return d

    return ""


def pick_best_contact(contacts: list[dict]) -> dict | None:
    """
    Pick the best owner-level contact from a list of Clay results.
    Returns the contact dict or None.
    """
    if not contacts:
        return None

    scored = []
    for c in contacts:
        score = 0
        title_lower = (c.get("title", "") or c.get("job_title", "") or "").lower()
        email = c.get("email", "") or ""

        # Must have an email
        if not email or "@" not in email:
            continue

        # Reject generic emails
        local = email.split("@")[0].lower()
        generic = {
            "contact", "info", "admin", "hello", "support", "sales",
            "team", "office", "general", "mail", "reception", "frontdesk",
            "noreply", "no-reply", "billing", "hr",
        }
        if local in generic:
            continue

        # Score by title match (owner-level preferred)
        for i, target in enumerate(TARGET_TITLES):
            if target in title_lower:
                score += (len(TARGET_TITLES) - i) * 10
                break

        # No title match at all = low priority but still usable
        if score == 0:
            score = 1

        scored.append((score, c))

    if not scored:
        return None

    scored.sort(key=lambda x: -x[0])
    return scored[0][1]


def prepare_batch(rows: list[dict], dry_run: bool = False) -> dict:
    """
    Prepare a batch manifest of Clay MCP calls needed.
    Returns the batch manifest dict.
    """
    batch = {
        "created_at": datetime.now().isoformat(),
        "total_leads": len(rows),
        "leads_to_enrich": [],
        "skipped_already_enriched": 0,
        "skipped_no_domain": 0,
    }

    for i, row in enumerate(rows):
        if not needs_enrichment(row):
            if row.get("owner_email", "").strip():
                batch["skipped_already_enriched"] += 1
            else:
                batch["skipped_no_domain"] += 1
            continue

        domain = get_domain(row)
        if not domain:
            batch["skipped_no_domain"] += 1
            continue

        batch["leads_to_enrich"].append({
            "index": i,
            "company_name": row.get("company_name", ""),
            "domain": domain,
            "city": row.get("city", ""),
            "category": row.get("category", ""),
            "clay_call": {
                "tool": "mcp__Clay__find-and-enrich-contacts-at-company",
                "params": {
                    "companyIdentifier": domain,
                    "contactFilters": {
                        "job_title_keywords": [
                            "Owner", "Founder", "CEO", "President",
                            "Principal", "Managing Partner",
                        ],
                    },
                    "dataPoints": {
                        "contactDataPoints": [
                            {"type": "Email"},
                        ],
                    },
                },
            },
        })

    logger.info(
        f"Batch prepared: {len(batch['leads_to_enrich'])} leads to enrich, "
        f"{batch['skipped_already_enriched']} already enriched, "
        f"{batch['skipped_no_domain']} skipped (no domain)"
    )

    if not dry_run:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        with open(BATCH_FILE, "w", encoding="utf-8") as f:
            json.dump(batch, f, indent=2)
        logger.info(f"Batch manifest written to {BATCH_FILE}")

    return batch


def process_batch(rows: list[dict]) -> list[dict]:
    """
    Read Clay results and merge them into the lead rows.
    Expects output/ns_clay_results.json with format:
    {
        "results": [
            {
                "index": 0,
                "domain": "example.com",
                "contacts": [
                    {
                        "first_name": "John",
                        "last_name": "Doe",
                        "email": "john@example.com",
                        "title": "Owner"
                    }
                ],
                "status": "found" | "no_match" | "error"
            },
            ...
        ]
    }
    """
    if not RESULTS_FILE.exists():
        logger.error(f"Results file not found: {RESULTS_FILE}")
        logger.info(
            "First run Clay MCP enrichment and save results to "
            f"{RESULTS_FILE}"
        )
        sys.exit(1)

    with open(RESULTS_FILE, encoding="utf-8") as f:
        results_data = json.load(f)

    results = results_data.get("results", [])
    logger.info(f"Loaded {len(results)} Clay results from {RESULTS_FILE}")

    stats = {
        "enriched": 0,
        "no_match": 0,
        "errors": 0,
        "already_had": 0,
    }

    # Build index lookup
    results_by_index = {}
    for r in results:
        idx = r.get("index")
        if idx is not None:
            results_by_index[idx] = r

    # Also support lookup by domain
    results_by_domain = {}
    for r in results:
        domain = r.get("domain", "").lower()
        if domain:
            results_by_domain[domain] = r

    for i, row in enumerate(rows):
        # Skip if already enriched
        if row.get("owner_email", "").strip() and "@" in row.get("owner_email", ""):
            stats["already_had"] += 1
            continue

        # Find matching result by index or domain
        result = results_by_index.get(i)
        if not result:
            domain = get_domain(row).lower()
            result = results_by_domain.get(domain)

        if not result:
            continue

        status = result.get("status", "")
        if status == "error":
            stats["errors"] += 1
            continue

        contacts = result.get("contacts", [])
        best = pick_best_contact(contacts)

        if best:
            row["owner_first_name"] = best.get("first_name", "") or best.get("firstName", "")
            row["owner_last_name"] = best.get("last_name", "") or best.get("lastName", "")
            row["owner_email"] = best.get("email", "")
            row["owner_title"] = (
                best.get("title", "")
                or best.get("job_title", "")
                or best.get("jobTitle", "")
            )
            stats["enriched"] += 1
            logger.info(
                f"  Enriched: {row.get('company_name', '')} -> "
                f"{row['owner_first_name']} {row['owner_last_name']} "
                f"<{row['owner_email']}> ({row['owner_title']})"
            )
        else:
            stats["no_match"] += 1

    return rows, stats


def write_enriched_csv(rows: list[dict]):
    """Write the enriched CSV with all original + new columns."""
    if not rows:
        logger.warning("No rows to write")
        return

    # Determine fieldnames: original fields + enrichment fields
    all_fields = list(rows[0].keys())
    for field in ENRICHMENT_FIELDS:
        if field not in all_fields:
            all_fields.append(field)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=all_fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            # Ensure enrichment fields exist
            for field in ENRICHMENT_FIELDS:
                if field not in row:
                    row[field] = ""
            writer.writerow(row)

    logger.info(f"Enriched CSV written to {OUTPUT_CSV} ({len(rows)} rows)")


def print_interactive_instructions(rows: list[dict]):
    """
    Print Clay MCP calls one at a time for manual execution in Claude.
    """
    to_enrich = []
    for i, row in enumerate(rows):
        if needs_enrichment(row):
            domain = get_domain(row)
            if domain:
                to_enrich.append((i, row, domain))

    if not to_enrich:
        logger.info("All leads already enriched or no domains available.")
        return

    print(f"\n{'=' * 70}")
    print(f"  Clay MCP Enrichment — Interactive Mode")
    print(f"  {len(to_enrich)} leads to enrich")
    print(f"{'=' * 70}\n")
    print("  For each lead below, run the Clay MCP tool call in Claude,")
    print("  then save results to output/ns_clay_results.json and run:")
    print("    python ns_clay_enricher.py --process-batch\n")

    for idx, (i, row, domain) in enumerate(to_enrich):
        company = row.get("company_name", "Unknown")
        city = row.get("city", "")
        print(f"\n--- Lead {idx + 1}/{len(to_enrich)}: {company} ({city}) ---")
        print(f"Domain: {domain}")
        print(f"\nClay MCP call:")
        print(f'  Tool: mcp__Clay__find-and-enrich-contacts-at-company')
        print(f'  companyIdentifier: "{domain}"')
        print(f'  contactFilters:')
        print(f'    job_title_keywords: ["Owner", "Founder", "CEO", "President"]')
        print(f'  dataPoints:')
        print(f'    contactDataPoints: [{{"type": "Email"}}]')
        print()


def show_stats(rows: list[dict]):
    """Show current enrichment status."""
    total = len(rows)
    has_owner = sum(
        1 for r in rows
        if r.get("owner_email", "").strip() and "@" in r.get("owner_email", "")
    )
    has_domain = sum(1 for r in rows if get_domain(r))
    needs = sum(1 for r in rows if needs_enrichment(r))

    print(f"\n{'=' * 60}")
    print(f"  NS Leads Enrichment Status")
    print(f"{'=' * 60}")
    print(f"  Total leads:           {total}")
    print(f"  Have domain/website:   {has_domain}")
    print(f"  Already have owner:    {has_owner}")
    print(f"  Need enrichment:       {needs}")
    print(f"{'=' * 60}")

    if OUTPUT_CSV.exists():
        enriched_rows = []
        with open(OUTPUT_CSV, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                enriched_rows.append(row)

        enriched_count = sum(
            1 for r in enriched_rows
            if r.get("owner_email", "").strip() and "@" in r.get("owner_email", "")
        )
        print(f"\n  Enriched CSV exists: {OUTPUT_CSV}")
        print(f"  Enriched with owner: {enriched_count}/{len(enriched_rows)}")
        print(f"{'=' * 60}")


def run_clay_enrichment(rows: list[dict], dry_run: bool = False):
    """
    Main enrichment flow that can be called programmatically by Claude.

    This function is designed to be imported and called by Claude's code
    execution, where Claude has access to Clay MCP tools.

    Returns a list of result dicts ready to be saved to ns_clay_results.json.
    """
    results = []

    for i, row in enumerate(rows):
        if not needs_enrichment(row):
            continue

        domain = get_domain(row)
        if not domain:
            continue

        result = {
            "index": i,
            "domain": domain,
            "company_name": row.get("company_name", ""),
            "contacts": [],
            "status": "pending",
        }

        if dry_run:
            logger.info(f"  [DRY RUN] Would enrich: {domain} ({row.get('company_name', '')})")
            result["status"] = "dry_run"
        else:
            # This is a placeholder -- actual Clay MCP calls happen externally
            result["status"] = "pending"

        results.append(result)

    return results


def main():
    global INPUT_CSV, OUTPUT_CSV

    parser = argparse.ArgumentParser(
        description="Nova Scotia Leads — Clay MCP Enricher"
    )
    parser.add_argument(
        "--process-batch", action="store_true",
        help="Process Clay results and merge into enriched CSV"
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Print Clay MCP calls one at a time for manual execution"
    )
    parser.add_argument(
        "--stats", action="store_true",
        help="Show current enrichment statistics"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without writing files"
    )
    parser.add_argument(
        "--input-csv", default=None,
        help="Override input CSV path (default: output/ns_leads_all.csv)"
    )
    parser.add_argument(
        "--output-csv", default=None,
        help="Override output CSV path (default: output/ns_leads_enriched.csv)"
    )
    args = parser.parse_args()

    add_file_logging()

    # Allow overriding paths
    if args.input_csv:
        INPUT_CSV = Path(args.input_csv)
    if args.output_csv:
        OUTPUT_CSV = Path(args.output_csv)

    print("=" * 60)
    print("  NS Leads Clay MCP Enricher — Realside AI")
    print("=" * 60)
    print(f"  Input:  {INPUT_CSV}")
    print(f"  Output: {OUTPUT_CSV}")
    if args.dry_run:
        print("  Mode:   DRY RUN")
    print("=" * 60)

    # Read input CSV
    rows = read_input_csv()

    if args.stats:
        show_stats(rows)
        return

    if args.interactive:
        print_interactive_instructions(rows)
        return

    if args.process_batch:
        # Merge Clay results into leads
        enriched_rows, stats = process_batch(rows)

        if not args.dry_run:
            write_enriched_csv(enriched_rows)

        # Print summary
        print(f"\n{'=' * 60}")
        print(f"  ENRICHMENT SUMMARY")
        print(f"{'=' * 60}")
        print(f"  Total leads:         {len(rows)}")
        print(f"  Already had owner:   {stats['already_had']}")
        print(f"  Enriched this run:   {stats['enriched']}")
        print(f"  No match:            {stats['no_match']}")
        print(f"  Errors:              {stats['errors']}")
        print(f"{'=' * 60}")
        return

    # Default: prepare batch manifest
    batch = prepare_batch(rows, dry_run=args.dry_run)

    # Print summary and next steps
    n = len(batch["leads_to_enrich"])
    print(f"\n  Batch manifest ready: {n} leads to enrich")

    if n > 0 and not args.dry_run:
        print(f"\n  Next steps:")
        print(f"  1. Ask Claude to process {BATCH_FILE}")
        print(f"     using Clay MCP tools (find-and-enrich-contacts-at-company)")
        print(f"  2. Claude will save results to {RESULTS_FILE}")
        print(f"  3. Run: python ns_clay_enricher.py --process-batch")
        print(f"     to merge results into {OUTPUT_CSV}")
        print()
        print(f"  Or for small batches, use: python ns_clay_enricher.py --interactive")

    # Also show a preview of the first few leads
    if n > 0:
        print(f"\n  Preview (first 5 leads):")
        for entry in batch["leads_to_enrich"][:5]:
            print(
                f"    {entry['company_name']} | {entry['domain']} | "
                f"{entry['city']} | {entry['category']}"
            )
        if n > 5:
            print(f"    ... and {n - 5} more")

    print()


if __name__ == "__main__":
    main()
