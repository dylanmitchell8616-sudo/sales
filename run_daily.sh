#!/usr/bin/env bash
# =============================================================================
# Realside AI — Daily Sales Pipeline Runner
# =============================================================================
# Runs the full pipeline once per day, logs output, and handles errors.
#
# SETUP (one-time):
#   chmod +x run_daily.sh
#   crontab -e
#   # Add this line to run at 6 AM Central every day:
#   0 6 * * * /home/user/sales/run_daily.sh >> /home/user/sales/logs/cron.log 2>&1
#
# Or to run continuously in the background:
#   nohup /home/user/sales/run_daily.sh --loop &
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
LOCK_FILE="${SCRIPT_DIR}/.pipeline.lock"
CONFIG="${SCRIPT_DIR}/config.json"

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
cleanup() { rm -f "$LOCK_FILE"; }
trap cleanup EXIT

if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        echo "[$(date)] Pipeline already running (PID $pid), skipping."
        exit 0
    fi
    echo "[$(date)] Stale lock file found, removing."
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"

run_pipeline() {
    local today=$(date +%Y-%m-%d)
    local log_file="${LOG_DIR}/pipeline_${today}.log"

    echo "============================================================"
    echo "[$(date)] Starting daily pipeline run"
    echo "============================================================"

    cd "$SCRIPT_DIR"

    # Run the full pipeline (lead generation + email creation + upload)
    python run_full_pipeline.py --config "$CONFIG" 2>&1 | tee -a "$log_file"
    local exit_code=${PIPESTATUS[0]}

    if [ $exit_code -eq 0 ]; then
        echo "[$(date)] Pipeline completed successfully."
    else
        echo "[$(date)] Pipeline failed with exit code $exit_code."
    fi

    # Process replies from Instantly (classify, respond, tag) — single pass
    echo "[$(date)] Running reply autopilot (single pass)..."
    python reply_autopilot.py --config "$CONFIG" --once 2>&1 | tee -a "$log_file"
    if [ ${PIPESTATUS[0]} -eq 0 ]; then
        echo "[$(date)] Reply autopilot completed."
    else
        echo "[$(date)] Reply autopilot encountered errors (non-fatal)."
    fi

    # Clean up logs older than 30 days
    find "$LOG_DIR" -name "pipeline_*.log" -mtime +30 -delete 2>/dev/null || true

    echo "[$(date)] Log saved to: $log_file"
    echo ""
}

# --loop mode: run once per day, sleep until next 6 AM
if [ "${1:-}" = "--loop" ]; then
    echo "[$(date)] Starting in continuous loop mode (runs daily at 6 AM Central)"
    while true; do
        # Calculate seconds until next 6 AM
        now=$(date +%s)
        next_6am=$(date -d "tomorrow 06:00" +%s 2>/dev/null || date -d "06:00" +%s)
        # If it's before 6 AM today, run at 6 AM today
        today_6am=$(date -d "today 06:00" +%s 2>/dev/null || echo "$now")
        if [ "$now" -lt "$today_6am" ]; then
            next_6am=$today_6am
        fi
        sleep_seconds=$((next_6am - now))

        if [ $sleep_seconds -gt 0 ]; then
            echo "[$(date)] Sleeping until next pipeline run. Reply autopilot runs every hour."
            # Run reply autopilot every hour while waiting for the next full pipeline run
            while [ $(date +%s) -lt $next_6am ]; do
                remaining=$((next_6am - $(date +%s)))
                if [ $remaining -le 0 ]; then break; fi
                sleep_time=$((remaining < 3600 ? remaining : 3600))
                sleep $sleep_time
                if [ $(date +%s) -lt $next_6am ]; then
                    echo "[$(date)] Running hourly reply autopilot pass..."
                    python reply_autopilot.py --config "$CONFIG" --once 2>&1 | tee -a "${LOG_DIR}/reply_autopilot_$(date +%Y-%m-%d).log" || true
                fi
            done
        fi

        run_pipeline
    done
else
    # Single run mode (for cron)
    run_pipeline
fi
