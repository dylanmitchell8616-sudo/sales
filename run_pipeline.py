#!/usr/bin/env python3
"""
Sales Outreach Pipeline Orchestrator
=====================================
Runs all 10 sales scripts in the correct order, fully hands-off.

Usage:
    python run_pipeline.py                    # Run full pipeline
    python run_pipeline.py --dry-run          # Preview what would run
    python run_pipeline.py --phase 1          # Run only Phase 1 (ICP building)
    python run_pipeline.py --phase 2          # Run only Phase 2 (outreach generation)
    python run_pipeline.py --phase 3          # Run only Phase 3 (follow-ups)
    python run_pipeline.py --config my.json   # Use a custom config file
"""

import argparse
import csv
import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_config(path: str) -> dict:
    with open(path) as f:
        return json.load(f)


def setup_logging(output_dir: str) -> logging.Logger:
    os.makedirs(output_dir, exist_ok=True)
    log_path = os.path.join(output_dir, "pipeline.log")

    logger = logging.getLogger("pipeline")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_path, mode="a")
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter("[%(asctime)s] %(levelname)-8s %(message)s",
                            datefmt="%Y-%m-%d %H:%M:%S")
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)
    return logger


def count_csv_rows(path: str) -> int:
    """Count data rows in a CSV (excludes header)."""
    if not os.path.exists(path):
        return 0
    with open(path) as f:
        reader = csv.reader(f)
        next(reader, None)  # skip header
        return sum(1 for _ in reader)


def run_script(name: str, cmd: list[str], env: dict, output_dir: str) -> dict:
    """Run a single script and capture results."""
    log_file = os.path.join(output_dir, f"{name}.log")
    start = time.time()
    try:
        result = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=600
        )
        elapsed = round(time.time() - start, 1)
        with open(log_file, "w") as f:
            f.write(f"=== STDOUT ===\n{result.stdout}\n")
            f.write(f"=== STDERR ===\n{result.stderr}\n")

        return {
            "name": name,
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "elapsed": elapsed,
            "error": result.stderr.strip() if result.returncode != 0 else None,
        }
    except subprocess.TimeoutExpired:
        return {
            "name": name,
            "success": False,
            "returncode": -1,
            "elapsed": round(time.time() - start, 1),
            "error": "Timed out after 600s",
        }
    except Exception as e:
        return {
            "name": name,
            "success": False,
            "returncode": -1,
            "elapsed": round(time.time() - start, 1),
            "error": str(e),
        }


# ---------------------------------------------------------------------------
# Phase definitions
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent


def phase1_tasks(cfg: dict, out: str) -> list[tuple[str, list[str], str]]:
    """ICP list building. Returns list of (name, cmd, output_file)."""
    tasks = []
    if cfg.get("icp_description"):
        icp_out = os.path.join(out, "icp_prospects.csv")
        cmd = [
            sys.executable, str(BASE_DIR / "icp_list_builder.py"),
            "--source", cfg.get("icp_source", "manual"),
            "--icp-description", cfg["icp_description"],
            "--output", icp_out,
            "--limit", str(cfg.get("icp_limit", 50)),
        ]
        if cfg.get("icp_source") == "manual" and cfg.get("targets_csv"):
            cmd.extend(["--input", str(BASE_DIR / cfg["targets_csv"])])
        if cfg.get("icp_batch"):
            cmd.extend(["--batch", cfg["icp_batch"]])
        tasks.append(("icp_list_builder", cmd, icp_out))
    return tasks


def phase2_tasks(cfg: dict, out: str, targets: str) -> list[tuple[str, list[str], str]]:
    """Parallel outreach generation. Returns list of (name, cmd, output_file)."""
    tasks = []
    common = [
        "--sender-email", cfg.get("sender_email", ""),
        "--sender-name", cfg.get("sender_name", ""),
        "--product", cfg.get("product_description", "our product"),
    ]

    # 1. Prospect researcher (always runs if targets exist)
    if targets:
        pr_out = os.path.join(out, "prospect_emails.csv")
        tasks.append(("prospect_researcher", [
            sys.executable, str(BASE_DIR / "prospect_researcher.py"),
            "--input", targets, "--output", pr_out, *common,
        ], pr_out))

    # 2. News trigger (always runs if targets exist)
    if targets:
        nt_out = os.path.join(out, "news_triggered_emails.csv")
        tasks.append(("news_trigger", [
            sys.executable, str(BASE_DIR / "news_trigger.py"),
            "--input", targets, "--output", nt_out,
            "--days-back", str(cfg.get("days_back_news", 7)),
            *common,
        ], nt_out))

    # 3. Job signal monitor (needs keywords)
    if cfg.get("job_keywords") and targets:
        js_out = os.path.join(out, "job_signal_emails.csv")
        tasks.append(("job_signal_monitor", [
            sys.executable, str(BASE_DIR / "job_signal_monitor.py"),
            "--input", targets, "--output", js_out,
            "--keywords", cfg["job_keywords"], *common,
        ], js_out))

    # 4. Social listener (needs topics or runs without)
    if targets:
        sl_out = os.path.join(out, "social_outreach_emails.csv")
        cmd = [
            sys.executable, str(BASE_DIR / "social_listener.py"),
            "--input", targets, "--output", sl_out,
            "--days-back", str(cfg.get("days_back_social", 14)),
            *common,
        ]
        if cfg.get("watch_topics"):
            cmd.extend(["--topics", cfg["watch_topics"]])
        tasks.append(("social_listener", cmd, sl_out))

    # 5. Competitor review miner (needs competitors)
    if cfg.get("competitors"):
        cr_out = os.path.join(out, "displacement_emails.csv")
        cmd = [
            sys.executable, str(BASE_DIR / "competitor_review_miner.py"),
            "--competitors", cfg["competitors"],
            "--output", cr_out, *common,
        ]
        if targets:
            cmd.extend(["--targets", targets])
        tasks.append(("competitor_review_miner", cmd, cr_out))

    # 6. Case study matcher (needs case studies path)
    if cfg.get("case_studies_path") and targets:
        cs_out = os.path.join(out, "case_study_emails.csv")
        tasks.append(("case_study_matcher", [
            sys.executable, str(BASE_DIR / "case_study_matcher.py"),
            "--case-studies", str(BASE_DIR / cfg["case_studies_path"]),
            "--targets", targets, "--output", cs_out, *common,
        ], cs_out))

    # 7. Event outreach (needs event URL)
    if cfg.get("event_url") and cfg.get("event_name"):
        eo_out = os.path.join(out, "event_outreach_emails.csv")
        cmd = [
            sys.executable, str(BASE_DIR / "event_outreach.py"),
            "--event-url", cfg["event_url"],
            "--event-name", cfg["event_name"],
            "--mode", cfg.get("event_mode", "pre-event"),
            "--output", eo_out, *common,
        ]
        if targets:
            cmd.extend(["--targets", targets])
        tasks.append(("event_outreach", cmd, eo_out))

    return tasks


def phase3_tasks(cfg: dict, out: str) -> list[tuple[str, list[str], str]]:
    """Follow-up generation on prospect_researcher output."""
    tasks = []
    pr_out = os.path.join(out, "prospect_emails.csv")
    if os.path.exists(pr_out) and count_csv_rows(pr_out) > 0:
        fu_out = os.path.join(out, "followup_sequences.csv")
        tasks.append(("followup_generator", [
            sys.executable, str(BASE_DIR / "followup_generator.py"),
            "--input", pr_out, "--output", fu_out,
            "--sender-email", cfg.get("sender_email", ""),
            "--sender-name", cfg.get("sender_name", ""),
            "--days-between", str(cfg.get("days_between_followups", 3)),
        ], fu_out))
    return tasks


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Sales Outreach Pipeline Orchestrator")
    parser.add_argument("--config", default="config.json", help="Path to config JSON")
    parser.add_argument("--dry-run", action="store_true", help="Show what would run without executing")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3], help="Run only a specific phase")
    args = parser.parse_args()

    # Load config
    config_path = str(BASE_DIR / args.config) if not os.path.isabs(args.config) else args.config
    cfg = load_config(config_path)

    out = str(BASE_DIR / cfg.get("output_dir", "output"))
    os.makedirs(out, exist_ok=True)

    logger = setup_logging(out)
    logger.info("=" * 60)
    logger.info("SALES PIPELINE STARTED  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)

    # Validate API key
    api_key = cfg.get("anthropic_api_key", "")
    if not api_key or api_key == "YOUR_API_KEY_HERE":
        logger.error("Set 'anthropic_api_key' in %s before running.", config_path)
        sys.exit(1)

    env = {**os.environ, "ANTHROPIC_API_KEY": api_key}

    # Determine targets file
    targets = ""
    if cfg.get("targets_csv"):
        t = str(BASE_DIR / cfg["targets_csv"]) if not os.path.isabs(cfg["targets_csv"]) else cfg["targets_csv"]
        if os.path.exists(t):
            targets = t

    results = []
    phases_to_run = [args.phase] if args.phase else [1, 2, 3]

    # ------------------------------------------------------------------
    # PHASE 1 — ICP List Building
    # ------------------------------------------------------------------
    if 1 in phases_to_run:
        p1 = phase1_tasks(cfg, out)
        if p1:
            logger.info("--- PHASE 1: ICP List Building ---")
            for name, cmd, output_file in p1:
                if args.dry_run:
                    logger.info("[DRY-RUN] Would run: %s → %s", name, output_file)
                else:
                    logger.info("Running %s ...", name)
                    r = run_script(name, cmd, env, out)
                    r["output_file"] = output_file
                    results.append(r)
                    if r["success"]:
                        logger.info("  ✓ %s completed in %ss (%d rows)",
                                    name, r["elapsed"], count_csv_rows(output_file))
                        # Use ICP output as targets for Phase 2
                        if count_csv_rows(output_file) > 0:
                            targets = output_file
                    else:
                        logger.warning("  ✗ %s failed: %s", name, r["error"])
        else:
            logger.info("--- PHASE 1: Skipped (no icp_description set) ---")

    # ------------------------------------------------------------------
    # PHASE 2 — Parallel Outreach Generation
    # ------------------------------------------------------------------
    if 2 in phases_to_run:
        # If Phase 1 produced ICP output, use it
        icp_out = os.path.join(out, "icp_prospects.csv")
        if os.path.exists(icp_out) and count_csv_rows(icp_out) > 0:
            targets = icp_out

        p2 = phase2_tasks(cfg, out, targets)
        if p2:
            logger.info("--- PHASE 2: Outreach Generation (%d scripts in parallel) ---", len(p2))
            if args.dry_run:
                for name, cmd, output_file in p2:
                    logger.info("[DRY-RUN] Would run: %s → %s", name, output_file)
            else:
                with ProcessPoolExecutor(max_workers=min(len(p2), 4)) as pool:
                    futures = {}
                    for name, cmd, output_file in p2:
                        logger.info("  Launching %s ...", name)
                        f = pool.submit(run_script, name, cmd, env, out)
                        futures[f] = (name, output_file)

                    for f in as_completed(futures):
                        name, output_file = futures[f]
                        r = f.result()
                        r["output_file"] = output_file
                        results.append(r)
                        if r["success"]:
                            logger.info("  ✓ %s completed in %ss (%d rows)",
                                        name, r["elapsed"], count_csv_rows(output_file))
                        else:
                            logger.warning("  ✗ %s failed: %s", name, r["error"])
        else:
            logger.info("--- PHASE 2: Skipped (no targets CSV found) ---")

    # ------------------------------------------------------------------
    # PHASE 3 — Follow-up Sequences
    # ------------------------------------------------------------------
    if 3 in phases_to_run:
        p3 = phase3_tasks(cfg, out)
        if p3:
            logger.info("--- PHASE 3: Follow-up Generation ---")
            for name, cmd, output_file in p3:
                if args.dry_run:
                    logger.info("[DRY-RUN] Would run: %s → %s", name, output_file)
                else:
                    logger.info("Running %s ...", name)
                    r = run_script(name, cmd, env, out)
                    r["output_file"] = output_file
                    results.append(r)
                    if r["success"]:
                        logger.info("  ✓ %s completed in %ss (%d rows)",
                                    name, r["elapsed"], count_csv_rows(output_file))
                    else:
                        logger.warning("  ✗ %s failed: %s", name, r["error"])
        else:
            logger.info("--- PHASE 3: Skipped (no prospect emails to follow up on) ---")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    if args.dry_run:
        logger.info("\n[DRY-RUN] No scripts were executed.")
    else:
        logger.info("")
        logger.info("=" * 60)
        logger.info("PIPELINE SUMMARY")
        logger.info("=" * 60)
        total_emails = 0
        for r in results:
            status = "OK" if r["success"] else "FAIL"
            rows = count_csv_rows(r.get("output_file", ""))
            total_emails += rows
            output_name = os.path.basename(r.get("output_file", ""))
            logger.info("  [%s] %-25s  %4d emails  (%ss)  → %s",
                        status, r["name"], rows, r["elapsed"], output_name)
            if not r["success"]:
                logger.info("         Error: %s", r["error"])

        logger.info("-" * 60)
        logger.info("  Total emails generated: %d", total_emails)
        logger.info("  Output directory: %s", out)
        logger.info("  Full log: %s", os.path.join(out, "pipeline.log"))

        failed = [r for r in results if not r["success"]]
        if failed:
            logger.info("")
            logger.info("  ⚠ %d script(s) failed. Check individual logs in %s/", len(failed), out)

    logger.info("=" * 60)
    logger.info("PIPELINE FINISHED  %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
