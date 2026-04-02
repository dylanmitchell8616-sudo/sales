#!/usr/bin/env python3
"""
Realside AI — Master Automation Daemon
=======================================
Fully automates the entire pipeline end-to-end, continuously:

  1. Discovers new leads matching dental/med spa ICP on schedule
  2. Runs all 8 outreach generation scripts on new leads only
  3. Uploads new emails to existing Instantly campaigns (no duplicates)
  4. Keeps all campaigns continuously refreshed with fresh leads
  5. Manages reply autopilot and news trigger daemon as subprocesses

All three daemons run in parallel:
  - Pipeline refresh: daily at 6 AM (discover → generate → upload)
  - Reply autopilot: every 60 seconds (classify → respond → tag)
  - News trigger daemon: every 4 hours (detect → generate → queue)

Usage:
    python automation_daemon.py                  # Start full automation stack
    python automation_daemon.py --dry-run        # Preview without executing
    python automation_daemon.py --once           # Single pipeline pass + exit
    python automation_daemon.py --pipeline-only  # Only run pipeline refresh
    python automation_daemon.py --interval 3600  # Pipeline refresh every hour

Stop with Ctrl+C or: kill $(cat output/automation_daemon.pid)
"""

import argparse
import json
import logging
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG = str(BASE_DIR / "config.json")
LOG_PATH = str(BASE_DIR / "output/automation_daemon.log")
PID_PATH = str(BASE_DIR / "output/automation_daemon.pid")

# Default pipeline refresh: daily at 6 AM Central
DEFAULT_PIPELINE_INTERVAL = 24 * 60 * 60  # 24 hours

_shutdown = False
_subprocesses = {}


def _handle_signal(signum, frame):
    global _shutdown
    logging.info("Shutdown signal received — stopping all daemons...")
    _shutdown = True
    for name, proc in _subprocesses.items():
        if proc and proc.poll() is None:
            logging.info("Terminating %s (PID %d)...", name, proc.pid)
            proc.terminate()


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


def setup_logging():
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(LOG_PATH, encoding="utf-8")
    fh.setFormatter(fmt)
    fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(fh)
    root.addHandler(ch)


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# Subprocess management
# ---------------------------------------------------------------------------

def start_subprocess(name: str, cmd: list, log_file: str) -> subprocess.Popen:
    """Start a subprocess, redirect output to a log file."""
    os.makedirs(os.path.dirname(log_file), exist_ok=True)
    log_fh = open(log_file, "a", encoding="utf-8")
    log_fh.write(f"\n{'='*60}\n[{timestamp()}] Starting {name}\n{'='*60}\n")
    log_fh.flush()
    proc = subprocess.Popen(
        cmd,
        stdout=log_fh,
        stderr=subprocess.STDOUT,
        cwd=str(BASE_DIR),
    )
    logging.info("Started %s (PID %d) → %s", name, proc.pid, log_file)
    return proc


def ensure_subprocess_running(name: str, cmd: list, log_file: str) -> subprocess.Popen:
    """Restart subprocess if it has died."""
    global _subprocesses
    proc = _subprocesses.get(name)
    if proc is None or proc.poll() is not None:
        exit_code = proc.poll() if proc else None
        if exit_code is not None:
            logging.warning("%s exited with code %d — restarting...", name, exit_code)
        proc = start_subprocess(name, cmd, log_file)
        _subprocesses[name] = proc
    return proc


# ---------------------------------------------------------------------------
# Pipeline refresh
# ---------------------------------------------------------------------------

def run_pipeline_refresh(cfg: dict, dry_run: bool = False) -> bool:
    """
    Full pipeline refresh cycle:
      1. Auto-discover new leads (lead_sourcer.py)
      2. Run all outreach generation scripts (run_pipeline.py)
      3. Upload new leads to existing campaigns (instantly_uploader.py --update-existing)
    """
    api_key = cfg.get("instantly_api_key", "")
    output_dir = str(BASE_DIR / cfg.get("output_dir", "output"))
    today = datetime.now().strftime("%Y-%m-%d")
    log_file = str(BASE_DIR / f"output/pipeline_refresh_{today}.log")

    logging.info("=" * 60)
    logging.info("PIPELINE REFRESH STARTING — %s", timestamp())
    logging.info("=" * 60)

    # Step 1: Discover new leads
    logging.info("Step 1/3: Discovering new leads...")
    lead_sourcer = str(BASE_DIR / "lead_sourcer.py")
    targets_csv = str(BASE_DIR / cfg.get("targets_csv", "targets.csv"))
    limit = cfg.get("icp_limit", 50)

    if os.path.exists(lead_sourcer):
        cmd = [sys.executable, lead_sourcer, "--output", targets_csv, "--limit", str(limit)]
        if dry_run:
            cmd.append("--dry-run")
        rc, out, err = _run_cmd(cmd, timeout=600)
        if rc == 0:
            logging.info("Lead discovery complete.")
        else:
            logging.warning("Lead discovery failed (using existing targets): %s", err[:200])
    else:
        logging.info("lead_sourcer.py not found — using existing targets.csv")

    if _shutdown:
        return False

    # Step 2: Run full outreach pipeline on new leads
    logging.info("Step 2/3: Generating outreach emails...")
    pipeline_script = str(BASE_DIR / "run_pipeline.py")
    config_path = str(BASE_DIR / "config.json")
    env = {**os.environ, "ANTHROPIC_API_KEY": cfg.get("anthropic_api_key", "")}

    cmd = [sys.executable, pipeline_script, "--config", config_path]
    if dry_run:
        cmd.append("--dry-run")

    rc, out, err = _run_cmd(cmd, env=env, timeout=1800)
    if out:
        for line in out.strip().split("\n")[-20:]:
            logging.debug("  pipeline | %s", line)
    if rc == 0:
        logging.info("Pipeline generation complete.")
    else:
        logging.error("Pipeline generation failed (exit %d): %s", rc, err[:200])
        if not dry_run:
            return False

    if _shutdown:
        return False

    # Step 3: Upload new leads to existing campaigns (dedup enabled)
    logging.info("Step 3/3: Uploading new leads to Instantly campaigns...")
    uploader = str(BASE_DIR / "instantly_uploader.py")

    cmd = [
        sys.executable, uploader,
        "--api-key", api_key,
        "--output-dir", output_dir,
        "--update-existing",   # add to existing campaigns, not create new ones
        "--auto-activate",     # campaigns go live immediately
    ]
    if dry_run:
        cmd.append("--dry-run")

    rc, out, err = _run_cmd(cmd, timeout=300)
    if out:
        for line in out.strip().split("\n"):
            logging.info("  uploader | %s", line)
    if rc == 0:
        logging.info("Campaign update complete.")
        return True
    else:
        logging.error("Campaign upload failed (exit %d): %s", rc, err[:200])
        return False


def _run_cmd(cmd: list, env: dict = None, timeout: int = 600) -> tuple:
    """Run a command, return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env or os.environ,
            cwd=str(BASE_DIR),
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"Timed out after {timeout}s"
    except Exception as e:
        return -1, "", str(e)


# ---------------------------------------------------------------------------
# Main daemon loop
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Realside AI — Master Automation Daemon",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--config", default=DEFAULT_CONFIG)
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview all steps without executing")
    parser.add_argument("--once", action="store_true",
                        help="Run one pipeline pass then exit")
    parser.add_argument("--pipeline-only", action="store_true",
                        help="Only run pipeline refresh (no reply/news daemons)")
    parser.add_argument("--interval", type=int, default=DEFAULT_PIPELINE_INTERVAL,
                        help="Pipeline refresh interval in seconds (default: 86400 = 24h)")
    parser.add_argument("--reply-interval", type=int, default=60,
                        help="Reply autopilot poll interval in seconds (default: 60)")
    parser.add_argument("--news-interval", type=int, default=14400,
                        help="News trigger check interval in seconds (default: 14400 = 4h)")
    parser.add_argument("--open-interval", type=int, default=14400,
                        help="Open tracker check interval in seconds (default: 14400 = 4h)")
    args = parser.parse_args()

    setup_logging()
    os.makedirs(str(BASE_DIR / "output"), exist_ok=True)

    # Write PID file
    with open(PID_PATH, "w") as f:
        f.write(str(os.getpid()))

    logging.info("=" * 60)
    logging.info("REALSIDE AI — MASTER AUTOMATION DAEMON")
    logging.info("Started: %s | PID: %d", timestamp(), os.getpid())
    logging.info("=" * 60)

    if not os.path.exists(args.config):
        logging.error("Config not found: %s", args.config)
        sys.exit(1)

    cfg = load_config(args.config)
    logging.info("Config loaded. Sender: %s <%s>",
                 cfg.get("sender_name", ""), cfg.get("sender_email", ""))
    logging.info("Pipeline interval: %ds | Reply interval: %ds | News interval: %ds | Open tracker: %ds",
                 args.interval, args.reply_interval, args.news_interval, args.open_interval)

    if args.dry_run:
        logging.info("DRY-RUN MODE: pipeline will preview but not execute")

    # ------------------------------------------------------------------
    # Single-pass mode
    # ------------------------------------------------------------------
    if args.once:
        logging.info("Single-pass mode.")
        run_pipeline_refresh(cfg, dry_run=args.dry_run)
        logging.info("Single pass complete. Exiting.")
        try:
            os.remove(PID_PATH)
        except Exception:
            pass
        return

    # ------------------------------------------------------------------
    # Daemon mode: start sub-daemons + pipeline loop
    # ------------------------------------------------------------------
    if not args.pipeline_only and not args.dry_run:
        # Start reply autopilot daemon
        reply_cmd = [
            sys.executable, str(BASE_DIR / "reply_autopilot.py"),
            "--config", args.config,
            "--interval", str(args.reply_interval),
        ]
        ensure_subprocess_running(
            "reply_autopilot",
            reply_cmd,
            str(BASE_DIR / "output/reply_autopilot.log"),
        )

        # Start news trigger daemon
        news_cmd = [
            sys.executable, str(BASE_DIR / "news_trigger_daemon.py"),
            "--config", args.config,
            "--interval", str(args.news_interval),
        ]
        ensure_subprocess_running(
            "news_trigger_daemon",
            news_cmd,
            str(BASE_DIR / "output/news_daemon.log"),
        )

        # Start open tracker daemon
        open_cmd = [
            sys.executable, str(BASE_DIR / "open_tracker_daemon.py"),
            "--config", args.config,
            "--interval", str(args.open_interval),
        ]
        ensure_subprocess_running(
            "open_tracker_daemon",
            open_cmd,
            str(BASE_DIR / "output/open_tracker.log"),
        )

        logging.info("Sub-daemons started: reply_autopilot + news_trigger_daemon + open_tracker_daemon")

    # Initial pipeline run immediately on start
    logging.info("Running initial pipeline refresh...")
    run_pipeline_refresh(cfg, dry_run=args.dry_run)

    if _shutdown:
        logging.info("Shutdown requested after initial run.")
        try:
            os.remove(PID_PATH)
        except Exception:
            pass
        return

    logging.info("Entering main loop. Pipeline refreshes every %ds (%s).",
                 args.interval,
                 f"{args.interval // 3600}h" if args.interval >= 3600 else f"{args.interval // 60}m")
    logging.info("Stop with: Ctrl+C or kill %d", os.getpid())

    last_pipeline_run = time.time()
    cycle = 0

    while not _shutdown:
        cycle += 1
        now = time.time()

        # Restart any sub-daemons that have died
        if not args.pipeline_only and not args.dry_run:
            for name, proc in list(_subprocesses.items()):
                if proc and proc.poll() is not None:
                    logging.warning("%s (PID %d) died — restarting...", name, proc.pid)
                    if name == "reply_autopilot":
                        ensure_subprocess_running(
                            name,
                            [sys.executable, str(BASE_DIR / "reply_autopilot.py"),
                             "--config", args.config, "--interval", str(args.reply_interval)],
                            str(BASE_DIR / "output/reply_autopilot.log"),
                        )
                    elif name == "news_trigger_daemon":
                        ensure_subprocess_running(
                            name,
                            [sys.executable, str(BASE_DIR / "news_trigger_daemon.py"),
                             "--config", args.config, "--interval", str(args.news_interval)],
                            str(BASE_DIR / "output/news_daemon.log"),
                        )
                    elif name == "open_tracker_daemon":
                        ensure_subprocess_running(
                            name,
                            [sys.executable, str(BASE_DIR / "open_tracker_daemon.py"),
                             "--config", args.config, "--interval", str(args.open_interval)],
                            str(BASE_DIR / "output/open_tracker.log"),
                        )

        # Check if pipeline refresh is due
        if now - last_pipeline_run >= args.interval:
            logging.info("--- Pipeline refresh cycle %d ---", cycle)
            try:
                run_pipeline_refresh(cfg, dry_run=args.dry_run)
            except Exception as e:
                logging.error("Pipeline refresh cycle %d failed: %s", cycle, e, exc_info=True)
            last_pipeline_run = time.time()

        # Sleep in small increments for responsive shutdown
        time.sleep(min(30, args.interval))

    # Cleanup
    logging.info("Shutting down all sub-daemons...")
    for name, proc in _subprocesses.items():
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            logging.info("%s stopped.", name)

    try:
        os.remove(PID_PATH)
    except Exception:
        pass

    logging.info("Master automation daemon stopped. Goodbye.")


if __name__ == "__main__":
    main()
