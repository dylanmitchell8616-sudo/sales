#!/usr/bin/env bash
#
# Stop the process manager and all its children cleanly.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.run/manager.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found — process manager is not running."
    exit 0
fi

PID=$(cat "$PID_FILE" 2>/dev/null || true)

if [ -z "$PID" ]; then
    echo "PID file is empty. Cleaning up."
    rm -f "$PID_FILE"
    exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
    echo "Process manager (PID $PID) is not running. Cleaning up stale PID file."
    rm -f "$PID_FILE"
    exit 0
fi

echo "Sending SIGTERM to process manager (PID $PID)..."
kill "$PID"

# Wait for graceful shutdown (up to 30 seconds)
for i in $(seq 1 30); do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "Process manager stopped."
        rm -f "$PID_FILE"
        exit 0
    fi
    sleep 1
done

echo "Manager did not exit in 30s — sending SIGKILL."
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "Process manager killed."
