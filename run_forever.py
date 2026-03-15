#!/usr/bin/env python3
"""
Process manager that keeps all automation scripts running 24/7.

Manages subprocess lifecycles with automatic restart on crash,
PID-file-based singleton enforcement, and structured logging.

Usage:
    python run_forever.py          # foreground
    nohup python run_forever.py &  # background, survives terminal close
"""

import os
import sys
import time
import signal
import subprocess
import atexit
from pathlib import Path
from datetime import datetime

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / ".run"
PID_FILE = RUN_DIR / "manager.pid"
LOG_FILE = LOG_DIR / "process_manager.log"

PROCESSES = [
    {
        "name": "reply_monitor",
        "cmd": [sys.executable, str(BASE_DIR / "reply_monitor.py")],
        "restart_delay": 5,
    },
    {
        "name": "lead_watcher",
        "cmd": [sys.executable, str(BASE_DIR / "lead_watcher.py")],
        "restart_delay": 5,
    },
]

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def log(msg: str, *, to_terminal: bool = True) -> None:
    """Append a timestamped line to the log file and optionally print it."""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")
    if to_terminal:
        print(line, flush=True)

# ---------------------------------------------------------------------------
# PID file helpers
# ---------------------------------------------------------------------------

def read_pid() -> int | None:
    """Return the PID stored on disk, or None."""
    try:
        return int(PID_FILE.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


def pid_alive(pid: int) -> bool:
    """Check whether a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def enforce_singleton() -> None:
    """Exit immediately if another instance is already running."""
    existing = read_pid()
    if existing is not None and pid_alive(existing):
        print(f"Process manager already running (PID {existing}). Exiting.")
        sys.exit(1)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()))


def remove_pid_file() -> None:
    """Clean up the PID file on exit."""
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

# ---------------------------------------------------------------------------
# Child process tracking
# ---------------------------------------------------------------------------

class ManagedProcess:
    """Wraps a subprocess with metadata for restart logic."""

    def __init__(self, spec: dict):
        self.name: str = spec["name"]
        self.cmd: list[str] = spec["cmd"]
        self.restart_delay: int = spec.get("restart_delay", 5)
        self.proc: subprocess.Popen | None = None
        self.starts: int = 0
        self.last_start: float = 0.0

    def start(self) -> None:
        log(f"Starting [{self.name}]: {' '.join(self.cmd)}")
        self.proc = subprocess.Popen(
            self.cmd,
            cwd=str(BASE_DIR),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.starts += 1
        self.last_start = time.time()
        log(f"[{self.name}] started (PID {self.proc.pid}, start #{self.starts})")

    def poll(self) -> int | None:
        if self.proc is None:
            return -1
        return self.proc.poll()

    def stop(self) -> None:
        if self.proc is None:
            return
        pid = self.proc.pid
        log(f"Stopping [{self.name}] (PID {pid})")
        try:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                log(f"[{self.name}] did not exit in 10s, sending SIGKILL")
                self.proc.kill()
                self.proc.wait(timeout=5)
        except Exception as exc:
            log(f"[{self.name}] error during stop: {exc}")
        log(f"[{self.name}] stopped")
        self.proc = None

    @property
    def status(self) -> str:
        if self.proc is None:
            return "stopped"
        rc = self.proc.poll()
        if rc is None:
            return f"running (PID {self.proc.pid})"
        return f"exited (code {rc})"

# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    _shutdown = True


def main() -> None:
    global _shutdown

    # Ensure dirs exist
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    RUN_DIR.mkdir(parents=True, exist_ok=True)

    enforce_singleton()
    atexit.register(remove_pid_file)

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    log("=" * 60)
    log("Process manager starting")
    log(f"PID: {os.getpid()}")
    log(f"Managed processes: {[p['name'] for p in PROCESSES]}")
    log("=" * 60)

    children = [ManagedProcess(spec) for spec in PROCESSES]

    # Initial start
    for child in children:
        try:
            child.start()
        except Exception as exc:
            log(f"[{child.name}] failed to start: {exc}")

    # Supervisor loop
    while not _shutdown:
        for child in children:
            rc = child.poll()
            if rc is not None:
                # Process has exited (or was never started)
                if child.proc is not None:
                    log(f"[{child.name}] crashed (exit code {rc}), "
                        f"restarting in {child.restart_delay}s")
                    child.proc = None

                    # Wait the restart delay, but stay responsive to shutdown
                    deadline = time.time() + child.restart_delay
                    while time.time() < deadline and not _shutdown:
                        time.sleep(0.5)

                    if _shutdown:
                        break

                try:
                    child.start()
                except Exception as exc:
                    log(f"[{child.name}] failed to restart: {exc}")

        if _shutdown:
            break

        time.sleep(1)

    # Graceful shutdown
    log("-" * 60)
    log("Shutdown signal received — stopping all processes")
    for child in children:
        child.stop()
    log("All processes stopped. Manager exiting.")
    log("-" * 60)


if __name__ == "__main__":
    main()
