#!/usr/bin/env bash
# Reply Autopilot Runner
# Runs reply_autopilot.py as a background daemon
# Usage: ./run_reply_autopilot.sh [--foreground] [--interval SECONDS]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
LOCK_FILE="${SCRIPT_DIR}/output/reply_autopilot.lock"
CONFIG="${SCRIPT_DIR}/config.json"
FOREGROUND=false
INTERVAL=300

mkdir -p "$LOG_DIR"
mkdir -p "${SCRIPT_DIR}/output"

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --foreground) FOREGROUND=true; shift ;;
        --interval)   INTERVAL="$2"; shift 2 ;;
        *)            echo "Unknown option: $1"; exit 1 ;;
    esac
done

# Graceful shutdown
cleanup() { rm -f "$LOCK_FILE"; }
trap cleanup EXIT
trap 'echo "[$(date)] Received shutdown signal, exiting."; exit 0' SIGINT SIGTERM

# Prevent multiple instances
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "[$(date)] Reply autopilot already running (PID $pid), skipping."
        exit 0
    fi
    echo "[$(date)] Stale lock file found, removing."
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"

# Source virtual environment if it exists
if [ -f "${SCRIPT_DIR}/venv/bin/activate" ]; then
    source "${SCRIPT_DIR}/venv/bin/activate"
fi

# Read API key from config.json
export API_KEY=$(python3 -c "import json; print(json.load(open('${CONFIG}'))['api_key'])" 2>/dev/null || echo "")

run_autopilot() {
    local today=$(date +%Y-%m-%d)
    local log_file="${LOG_DIR}/reply_autopilot_${today}.log"

    echo "============================================================"
    echo "[$(date)] Starting reply autopilot (interval: ${INTERVAL}s)"
    echo "============================================================"

    cd "$SCRIPT_DIR"

    python3 reply_autopilot.py --config "$CONFIG" 2>&1 | tee -a "$log_file"
    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        echo "[$(date)] Reply autopilot cycle completed successfully."
    else
        echo "[$(date)] Reply autopilot cycle failed with exit code $exit_code."
    fi

    # Clean up logs older than 30 days
    find "$LOG_DIR" -name "reply_autopilot_*.log" -mtime +30 -delete 2>/dev/null || true

    echo "[$(date)] Log saved to: $log_file"
    echo ""
}

if [ "$FOREGROUND" = true ]; then
    # Foreground mode: loop with interval
    echo "[$(date)] Running in foreground mode (interval: ${INTERVAL}s)"
    while true; do
        run_autopilot
        echo "[$(date)] Sleeping ${INTERVAL}s until next cycle..."
        sleep "$INTERVAL"
    done
else
    # Background daemon mode
    echo "[$(date)] Starting reply autopilot daemon (PID $$)"
    while true; do
        run_autopilot
        sleep "$INTERVAL"
    done &
    DAEMON_PID=$!
    # Update lock file with the backgrounded PID
    echo "$DAEMON_PID" > "$LOCK_FILE"
    echo "[$(date)] Reply autopilot daemon started (PID $DAEMON_PID)"
    echo "[$(date)] Logs: ${LOG_DIR}/reply_autopilot_$(date +%Y-%m-%d).log"
    # Detach trap so lock file persists after this script exits
    trap - EXIT
fi
