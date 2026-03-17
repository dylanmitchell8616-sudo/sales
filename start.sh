#!/usr/bin/env bash
#
# Start the process manager in the background and tail its log.
# Safe to run multiple times — will not spawn duplicates.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.run/manager.pid"
LOG_FILE="$SCRIPT_DIR/logs/process_manager.log"

mkdir -p "$SCRIPT_DIR/logs" "$SCRIPT_DIR/.run"

# --- Check if already running ------------------------------------------------
if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$(cat "$PID_FILE" 2>/dev/null || true)
    if [ -n "$EXISTING_PID" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Process manager is already running (PID $EXISTING_PID)."
        echo "Tailing log — press Ctrl+C to stop tailing (processes keep running)."
        echo ""
        tail -f "$LOG_FILE"
        exit 0
    fi
fi

# --- Start the manager --------------------------------------------------------
echo "Starting process manager..."
touch "$LOG_FILE"
nohup python3 "$SCRIPT_DIR/run_forever.py" >> "$LOG_FILE" 2>&1 &
MANAGER_PID=$!

# Give it a moment to write the PID file and start children
sleep 1

if kill -0 "$MANAGER_PID" 2>/dev/null; then
    echo "Process manager started (PID $MANAGER_PID)."
    echo "Log: $LOG_FILE"
    echo ""
    echo "Tailing log — press Ctrl+C to stop tailing (processes keep running)."
    echo "To stop everything: ./stop.sh"
    echo ""
    tail -f "$LOG_FILE"
else
    echo "ERROR: Process manager failed to start. Check $LOG_FILE"
    exit 1
fi
