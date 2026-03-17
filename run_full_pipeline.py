#!/usr/bin/env python3
"""
Full Sales Pipeline — Master Script
=====================================
Single command to run the entire sales pipeline end-to-end:
  0. Auto-discover leads matching ICP (Google search → local businesses)
  1. Run the sales pipeline (ICP scoring, outreach generation, follow-ups)
  2. Check email enrichment status
  3. Upload campaigns to Instantly.ai

Usage:
    python run_full_pipeline.py                       # Run everything (fully automated)
    python run_full_pipeline.py --dry-run             # Preview without executing
    python run_full_pipeline.py --skip-discovery      # Skip lead discovery, use existing targets
    python run_full_pipeline.py --skip-pipeline       # Skip pipeline, just upload to Instantly
    python run_full_pipeline.py --skip-upload         # Run pipeline, skip Instantly upload
    python run_full_pipeline.py --phase 1             # Only run pipeline Phase 1 (ICP)
    python run_full_pipeline.py --config other.json   # Use alternate config
"""

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DIVIDER = "=" * 65
THIN_DIVIDER = "-" * 65


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    """Load and validate config.json."""
    if not os.path.exists(path):
        print(f"[ERROR] Config file not found: {path}")
        sys.exit(1)
    with open(path) as f:
        cfg = json.load(f)

    required = ["anthropic_api_key", "instantly_api_key", "sender_email"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"[ERROR] Missing required config keys: {', '.join(missing)}")
        sys.exit(1)

    return cfg


def count_csv_rows(path: str) -> int:
    """Count data rows in a CSV (excludes header)."""
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        reader = csv.reader(f)
        next(reader, None)
        return sum(1 for _ in reader)


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def print_phase(number: int, title: str):
    print(f"\n{DIVIDER}")
    print(f"  PHASE {number}: {title}")
    print(DIVIDER)


def print_status(msg: str, level: str = "info"):
    prefix = {
        "info":    "[INFO]   ",
        "ok":      "[OK]     ",
        "warn":    "[WARN]   ",
        "error":   "[ERROR]  ",
        "skip":    "[SKIP]   ",
        "dry-run": "[DRY-RUN]",
    }.get(level, "[INFO]   ")
    print(f"  {prefix} {msg}")


def run_subprocess(cmd: list[str], env: dict = None, timeout: int = 1200) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# Phase 0: Auto-discover leads (lead_sourcer.py)
# ---------------------------------------------------------------------------

def discover_leads(cfg: dict, dry_run: bool = False) -> bool:
    """Run lead_sourcer.py to auto-discover companies matching the ICP."""
    print_phase(0, "Lead Discovery (Auto-Source Prospects)")

    script = str(BASE_DIR / "lead_sourcer.py")
    if not os.path.exists(script):
        print_status("lead_sourcer.py not found — skipping auto-discovery", "skip")
        print_status("Using existing targets.csv instead", "info")
        return True

    targets_csv = str(BASE_DIR / cfg.get("targets_csv", "targets.csv"))
    limit = cfg.get("icp_limit", 50)

    cmd = [sys.executable, script, "--output", targets_csv, "--limit", str(limit)]
    if dry_run:
        cmd.append("--dry-run")

    print_status(f"Searching for businesses matching ICP...")
    start = time.time()

    returncode, stdout, stderr = run_subprocess(cmd, timeout=600)
    elapsed = round(time.time() - start, 1)

    if stdout:
        for line in stdout.strip().split("\n")[-15:]:
            print(f"    | {line}")

    if returncode == 0:
        rows = count_csv_rows(targets_csv) if os.path.exists(targets_csv) else 0
        print_status(f"Discovered {rows} prospects in {elapsed}s", "ok")
        return True
    else:
        print_status(f"Lead discovery failed after {elapsed}s, using existing targets", "warn")
        if stderr:
            for line in stderr.strip().split("\n")[-5:]:
                print(f"    | [stderr] {line}")
        return True  # Don't block pipeline if discovery fails


# ---------------------------------------------------------------------------
# Phase 1: Run the sales pipeline
# ---------------------------------------------------------------------------

def run_pipeline(cfg: dict, config_path: str, dry_run: bool = False,
                 phase: int = None) -> bool:
    """Run run_pipeline.py as a subprocess."""
    print_phase(1, "Sales Pipeline (ICP + Outreach + Follow-ups)")

    script = str(BASE_DIR / "run_pipeline.py")
    if not os.path.exists(script):
        print_status(f"Pipeline script not found: {script}", "error")
        return False

    cmd = [sys.executable, script, "--config", config_path]
    if dry_run:
        cmd.append("--dry-run")
    if phase:
        cmd.extend(["--phase", str(phase)])

    print_status(f"Running: {' '.join(cmd)}")
    start = time.time()

    env = {**os.environ, "ANTHROPIC_API_KEY": cfg["anthropic_api_key"]}
    returncode, stdout, stderr = run_subprocess(cmd, env=env)
    elapsed = round(time.time() - start, 1)

    # Stream the output
    if stdout:
        for line in stdout.strip().split("\n"):
            print(f"    | {line}")
    if stderr and returncode != 0:
        for line in stderr.strip().split("\n")[-10:]:
            print(f"    | [stderr] {line}")

    if returncode == 0:
        print_status(f"Pipeline completed in {elapsed}s", "ok")
        return True
    else:
        print_status(f"Pipeline failed (exit code {returncode}) after {elapsed}s", "error")
        return False


# ---------------------------------------------------------------------------
# Phase 2: Email enrichment (manual step / Clay placeholder)
# ---------------------------------------------------------------------------

def run_zoominfo_enrichment(cfg: dict, dry_run: bool = False) -> bool:
    """Run zoominfo_enricher.py if a ZoomInfo API key is configured."""
    zi_key = cfg.get("zoominfo_api_key", "")
    zi_user = cfg.get("zoominfo_username", "")
    if not zi_key and not zi_user:
        return False  # No ZoomInfo credentials — skip

    script = str(BASE_DIR / "zoominfo_enricher.py")
    if not os.path.exists(script):
        print_status("zoominfo_enricher.py not found", "warn")
        return False

    output_dir = str(BASE_DIR / cfg.get("output_dir", "output"))
    cmd = [sys.executable, script, "--output-dir", output_dir]
    if zi_key:
        cmd.extend(["--api-key", zi_key])
    if dry_run:
        cmd.append("--dry-run")

    print_status("Running ZoomInfo contact enrichment...")
    start = time.time()
    returncode, stdout, stderr = run_subprocess(cmd, timeout=600)
    elapsed = round(time.time() - start, 1)

    if stdout:
        for line in stdout.strip().split("\n")[-20:]:
            print(f"    | {line}")

    if returncode == 0:
        print_status(f"ZoomInfo enrichment completed in {elapsed}s", "ok")
        return True
    else:
        print_status(f"ZoomInfo enrichment failed after {elapsed}s", "warn")
        if stderr:
            for line in stderr.strip().split("\n")[-5:]:
                print(f"    | [stderr] {line}")
        return False


def enrich_contacts(cfg: dict, dry_run: bool = False) -> dict:
    """
    Contact enrichment phase.

    Runs ZoomInfo enrichment automatically if credentials are in config.
    Otherwise logs which CSVs need manual enrichment.
    """
    print_phase(2, "Contact Email Enrichment")

    # Try ZoomInfo auto-enrichment first
    zi_ran = run_zoominfo_enrichment(cfg, dry_run=dry_run)
    if zi_ran:
        print()

    output_dir = str(BASE_DIR / cfg.get("output_dir", "output"))
    if not os.path.isdir(output_dir):
        print_status("No output directory found. Run the pipeline first.", "warn")
        return {"total_leads": 0, "needs_enrichment": 0}

    total_leads = 0
    needs_enrichment = 0
    csv_stats = []

    campaign_csvs = [
        "icp_prospects.csv",
        "prospect_emails.csv",
        "case_study_emails.csv",
        "news_triggered_emails.csv",
        "displacement_emails.csv",
        "social_outreach_emails.csv",
        "job_signal_emails.csv",
        "event_outreach_emails.csv",
    ]

    for filename in campaign_csvs:
        filepath = os.path.join(output_dir, filename)
        if not os.path.exists(filepath):
            continue

        rows = count_csv_rows(filepath)
        if rows == 0:
            continue

        # Check how many leads lack real emails
        missing_email = 0
        with open(filepath, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                email = (
                    row.get("contact_email", "")
                    or row.get("email", "")
                    or row.get("prospect_email", "")
                )
                if not email or email.startswith("contact@"):
                    missing_email += 1

        total_leads += rows
        needs_enrichment += missing_email
        csv_stats.append({
            "file": filename,
            "total": rows,
            "missing_email": missing_email,
        })

        status = "ok" if missing_email == 0 else "warn"
        msg = f"{filename}: {rows} leads"
        if missing_email > 0:
            msg += f" ({missing_email} need email enrichment)"
        print_status(msg, status)

    if needs_enrichment > 0:
        print()
        print_status(
            f"{needs_enrichment}/{total_leads} leads need real email addresses.",
            "warn"
        )
        print_status(
            "Enrich via Clay (clay.com), Apollo, or Hunter.io before uploading.",
            "warn"
        )
        print_status(
            "Leads with placeholder emails (contact@domain.com) will still be "
            "uploaded but won't be deliverable.",
            "warn"
        )
    elif total_leads > 0:
        print_status(f"All {total_leads} leads have email addresses.", "ok")
    else:
        print_status("No leads found to enrich. Run the pipeline first.", "skip")

    return {
        "total_leads": total_leads,
        "needs_enrichment": needs_enrichment,
        "csv_stats": csv_stats,
    }


# ---------------------------------------------------------------------------
# Phase 3: Upload to Instantly
# ---------------------------------------------------------------------------

def upload_to_instantly(cfg: dict, dry_run: bool = False) -> bool:
    """Run instantly_uploader.py to create campaigns and upload leads."""
    print_phase(3, "Upload to Instantly.ai")

    script = str(BASE_DIR / "instantly_uploader.py")
    if not os.path.exists(script):
        print_status(f"Uploader script not found: {script}", "error")
        return False

    api_key = cfg.get("instantly_api_key", "")
    if not api_key:
        print_status("No instantly_api_key in config.", "error")
        return False

    output_dir = str(BASE_DIR / cfg.get("output_dir", "output"))
    sending_account = cfg.get("sender_email", "")

    cmd = [
        sys.executable, script,
        "--api-key", api_key,
        "--output-dir", output_dir,
    ]
    if sending_account:
        cmd.extend(["--sending-account", sending_account])
    if dry_run:
        cmd.append("--dry-run")

    print_status(f"Running Instantly uploader (dry_run={dry_run})")
    start = time.time()

    returncode, stdout, stderr = run_subprocess(cmd, timeout=300)
    elapsed = round(time.time() - start, 1)

    if stdout:
        for line in stdout.strip().split("\n"):
            print(f"    | {line}")
    if stderr and returncode != 0:
        for line in stderr.strip().split("\n")[-10:]:
            print(f"    | [stderr] {line}")

    if returncode == 0:
        print_status(f"Instantly upload completed in {elapsed}s", "ok")
        return True
    else:
        print_status(f"Instantly upload failed (exit code {returncode}) after {elapsed}s", "error")
        return False


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def print_summary(results: dict):
    """Print a final summary of everything that happened."""
    print(f"\n{DIVIDER}")
    print("  FULL PIPELINE SUMMARY")
    print(DIVIDER)

    # Discovery
    discovery_status = results.get("discovery")
    if discovery_status is None:
        print_status("Discovery:  SKIPPED", "skip")
    elif discovery_status:
        print_status("Discovery:  COMPLETED", "ok")
    else:
        print_status("Discovery:  FAILED (used existing targets)", "warn")

    # Pipeline
    pipeline_status = results.get("pipeline")
    if pipeline_status is None:
        print_status("Pipeline:   SKIPPED (--skip-pipeline)", "skip")
    elif pipeline_status:
        print_status("Pipeline:   COMPLETED", "ok")
    else:
        print_status("Pipeline:   FAILED", "error")

    # Enrichment
    enrichment = results.get("enrichment", {})
    total = enrichment.get("total_leads", 0)
    needs = enrichment.get("needs_enrichment", 0)
    if total > 0:
        if needs > 0:
            print_status(
                f"Enrichment: {total} leads found, {needs} need real emails",
                "warn"
            )
        else:
            print_status(f"Enrichment: {total} leads, all have emails", "ok")
    else:
        print_status("Enrichment: No leads to enrich", "skip")

    # Upload
    upload_status = results.get("upload")
    if upload_status is None:
        print_status("Upload:     SKIPPED (--skip-upload)", "skip")
    elif upload_status:
        print_status("Upload:     COMPLETED", "ok")
    else:
        print_status("Upload:     FAILED", "error")

    # Output files
    output_dir = results.get("output_dir", "")
    if output_dir and os.path.isdir(output_dir):
        csv_files = [f for f in os.listdir(output_dir)
                     if f.endswith(".csv") and not f.startswith("_")]
        total_rows = sum(
            count_csv_rows(os.path.join(output_dir, f)) for f in csv_files
        )
        print()
        print_status(f"Output directory: {output_dir}")
        print_status(f"CSV files: {len(csv_files)}")
        print_status(f"Total leads/emails across all CSVs: {total_rows}")
        print_status(f"Pipeline log: {os.path.join(output_dir, 'pipeline.log')}")

    print(f"\n{DIVIDER}")

    # Next steps
    any_failed = (
        (pipeline_status is not None and not pipeline_status) or
        (upload_status is not None and not upload_status)
    )
    if any_failed:
        print("  NEXT STEPS:")
        print("    1. Check logs in the output directory for failure details")
        print("    2. Fix issues and re-run with appropriate --skip flags")
    elif needs > 0:
        print("  NEXT STEPS:")
        print("    1. Add zoominfo_api_key to config.json for auto-enrichment")
        print("       Or enrich manually via Clay, Apollo, or Hunter.io")
        print("    2. Re-run with: python run_full_pipeline.py --skip-pipeline")
    elif upload_status:
        print("  NEXT STEPS:")
        print("    1. Log in to Instantly.ai to review draft campaigns")
        print("    2. Verify email content and activate campaigns")
    print(DIVIDER)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Full Sales Pipeline — Master Script",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python run_full_pipeline.py                    Run the full pipeline end-to-end
  python run_full_pipeline.py --dry-run          Preview everything without executing
  python run_full_pipeline.py --skip-pipeline    Just enrich + upload existing CSVs
  python run_full_pipeline.py --skip-upload      Run pipeline without uploading to Instantly
  python run_full_pipeline.py --phase 1          Only run Phase 1 (ICP building)
        """,
    )
    parser.add_argument(
        "--config", default="config.json",
        help="Path to config JSON (default: config.json)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview all steps without executing anything"
    )
    parser.add_argument(
        "--skip-pipeline", action="store_true",
        help="Skip the pipeline phase; only enrich and upload existing CSVs"
    )
    parser.add_argument(
        "--skip-discovery", action="store_true",
        help="Skip lead discovery; use existing targets.csv"
    )
    parser.add_argument(
        "--skip-upload", action="store_true",
        help="Run the pipeline but skip uploading to Instantly"
    )
    parser.add_argument(
        "--phase", type=int, choices=[1, 2, 3],
        help="Run only a specific pipeline phase (passed to run_pipeline.py)"
    )
    args = parser.parse_args()

    # Resolve config path
    config_path = str(BASE_DIR / args.config) if not os.path.isabs(args.config) else args.config

    print(DIVIDER)
    print("  REALSIDE AI — FULL SALES PIPELINE")
    print(f"  Started: {timestamp()}")
    print(DIVIDER)

    if args.dry_run:
        print_status("DRY-RUN MODE: No changes will be made", "dry-run")

    # Load config
    cfg = load_config(config_path)
    print_status(f"Config loaded from {config_path}")
    print_status(f"Sender: {cfg.get('sender_name', '')} <{cfg.get('sender_email', '')}>")
    print_status(f"Output: {cfg.get('output_dir', 'output')}/")

    output_dir = str(BASE_DIR / cfg.get("output_dir", "output"))
    results = {"output_dir": output_dir}
    overall_start = time.time()

    # ------------------------------------------------------------------
    # PHASE 0: Auto-discover leads
    # ------------------------------------------------------------------
    if args.skip_pipeline or args.skip_discovery:
        if not args.skip_pipeline:
            print_phase(0, "Lead Discovery (SKIPPED)")
            print_status("Using existing targets.csv", "skip")
        results["discovery"] = None
    else:
        discovery_ok = discover_leads(cfg, dry_run=args.dry_run)
        results["discovery"] = discovery_ok

    # ------------------------------------------------------------------
    # PHASE 1: Run the pipeline
    # ------------------------------------------------------------------
    if args.skip_pipeline:
        print_phase(1, "Sales Pipeline (SKIPPED)")
        print_status("Skipped via --skip-pipeline flag", "skip")
        results["pipeline"] = None
    else:
        pipeline_ok = run_pipeline(
            cfg, config_path, dry_run=args.dry_run, phase=args.phase
        )
        results["pipeline"] = pipeline_ok
        if not pipeline_ok and not args.dry_run:
            print_status(
                "Pipeline failed. Continuing to enrichment check anyway...",
                "warn"
            )

    # ------------------------------------------------------------------
    # PHASE 2: Enrichment check
    # ------------------------------------------------------------------
    enrichment = enrich_contacts(cfg, dry_run=args.dry_run)
    results["enrichment"] = enrichment

    # ------------------------------------------------------------------
    # PHASE 3: Upload to Instantly
    # ------------------------------------------------------------------
    if args.skip_upload:
        print_phase(3, "Upload to Instantly.ai (SKIPPED)")
        print_status("Skipped via --skip-upload flag", "skip")
        results["upload"] = None
    else:
        upload_ok = upload_to_instantly(cfg, dry_run=args.dry_run)
        results["upload"] = upload_ok

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    elapsed = round(time.time() - overall_start, 1)
    print_summary(results)
    print(f"  Total time: {elapsed}s")
    print(f"  Finished: {timestamp()}")
    print(DIVIDER)


if __name__ == "__main__":
    main()
