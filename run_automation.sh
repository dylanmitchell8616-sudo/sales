#!/usr/bin/env bash
# =============================================================================
# Realside AI — Full Automation Stack Launcher
# =============================================================================
# Single command to start the entire automated pipeline:
#   - Pipeline refresh daemon  (discovers leads, generates emails, updates campaigns daily)
#   - Reply autopilot daemon   (classifies + responds to all replies every 60s)
#   - News trigger daemon      (monitors for buying signals every 4 hours)
#
# Usage:
#   ./run_automation.sh                  # Start full stack (background)
#   ./run_automation.sh --foreground     # Start full stack (foreground, logs to console)
#   ./run_automation.sh --dry-run        # Preview pipeline without executing
#   ./run_automation.sh --once           # Single pipeline pass only
#   ./run_automation.sh --stop           # Stop all running daemons
#   ./run_automation.sh --status         # Show what's running
#
# Setup (one-time):
#   chmod +x run_automation.sh
#
# Auto-start on reboot (add to crontab):
#   @reboot /home/user/sales/run_automation.sh >> /home/user/sales/logs/automation_boot.log 2>&1
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="${SCRIPT_DIR}/output/automation_daemon.pid"
LOG_DIR="${SCRIPT_DIR}/logs"
OUTPUT_DIR="${SCRIPT_DIR}/output"
CONFIG="${SCRIPT_DIR}/config.json"
PYTHON="${PYTHON:-python3}"

mkdir -p "$LOG_DIR" "$OUTPUT_DIR"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'

log() { echo -e "${BLUE}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn(){ echo -e "${YELLOW}[WARN]${NC} $*"; }
err() { echo -e "${RED}[ERROR]${NC} $*"; }

# --stop
if [ "${1:-}" = "--stop" ]; then
    log "Stopping automation stack..."
    stopped=0
    for pidfile in "$PID_FILE" "${OUTPUT_DIR}/reply_autopilot.lock"; do
        if [ -f "$pidfile" ]; then
            pid=$(cat "$pidfile" 2>/dev/null || echo "")
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                kill "$pid" && ok "Stopped PID $pid" && stopped=$((stopped+1))
            fi
            rm -f "$pidfile"
        fi
    done
    # Also kill any python processes running these scripts
    pkill -f "automation_daemon.py" 2>/dev/null && stopped=$((stopped+1)) || true
    pkill -f "reply_autopilot.py" 2>/dev/null && stopped=$((stopped+1)) || true
    pkill -f "news_trigger_daemon.py" 2>/dev/null && stopped=$((stopped+1)) || true
    [ $stopped -gt 0 ] && ok "Stopped $stopped process(es)." || warn "No running daemons found."
    exit 0
fi

# --status
if [ "${1:-}" = "--status" ]; then
    log "Automation stack status:"
    echo ""
    # Check master daemon
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
        if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
            ok "  automation_daemon  → RUNNING (PID $pid)"
        else
            warn "  automation_daemon  → DEAD (stale PID file)"
        fi
    else
        warn "  automation_daemon  → NOT RUNNING"
    fi
    # Check sub-daemons
    if pgrep -f "reply_autopilot.py" > /dev/null 2>&1; then
        pid=$(pgrep -f "reply_autopilot.py" | head -1)
        ok "  reply_autopilot    → RUNNING (PID $pid)"
    else
        warn "  reply_autopilot    → NOT RUNNING"
    fi
    if pgrep -f "news_trigger_daemon.py" > /dev/null 2>&1; then
        pid=$(pgrep -f "news_trigger_daemon.py" | head -1)
        ok "  news_trigger_daemon → RUNNING (PID $pid)"
    else
        warn "  news_trigger_daemon → NOT RUNNING"
    fi
    echo ""
    # Show recent log
    log "Recent activity (last 10 lines):"
    [ -f "${OUTPUT_DIR}/automation_daemon.log" ] && tail -10 "${OUTPUT_DIR}/automation_daemon.log" || echo "  (no log yet)"
    exit 0
fi

# --once
if [ "${1:-}" = "--once" ]; then
    log "Running single pipeline pass..."
    cd "$SCRIPT_DIR"
    $PYTHON automation_daemon.py --config "$CONFIG" --once
    exit $?
fi

# --dry-run
if [ "${1:-}" = "--dry-run" ]; then
    log "DRY RUN — pipeline preview only..."
    cd "$SCRIPT_DIR"
    $PYTHON automation_daemon.py --config "$CONFIG" --once --dry-run
    exit $?
fi

# Check for already running daemon
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE" 2>/dev/null || echo "")
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
        warn "Automation daemon already running (PID $pid)."
        warn "Use './run_automation.sh --stop' to stop it first."
        exit 1
    fi
    rm -f "$PID_FILE"
fi

echo ""
echo -e "${BLUE}============================================================${NC}"
echo -e "${BLUE}  REALSIDE AI — FULL AUTOMATION STACK${NC}"
echo -e "${BLUE}============================================================${NC}"
echo ""
echo "  Starting 3 parallel daemons:"
echo "  Pipeline refresh   → Daily at 6 AM (discover + generate + upload)"
echo "  Reply autopilot    → Every 60 seconds (classify + respond + tag)"
echo "  News trigger       → Every 4 hours (monitor + generate + queue)"
echo ""
echo "  Logs:"
echo "    ${OUTPUT_DIR}/automation_daemon.log"
echo "    ${OUTPUT_DIR}/reply_autopilot.log"
echo "    ${OUTPUT_DIR}/news_daemon.log"
echo ""

cd "$SCRIPT_DIR"

# --foreground
if [ "${1:-}" = "--foreground" ]; then
    log "Starting in foreground mode (Ctrl+C to stop)..."
    $PYTHON automation_daemon.py --config "$CONFIG"
    exit $?
fi

# Background mode — launch and detach
TODAY=$(date +%Y-%m-%d)
DAEMON_LOG="${LOG_DIR}/automation_${TODAY}.log"

nohup $PYTHON automation_daemon.py --config "$CONFIG" >> "$DAEMON_LOG" 2>&1 &
DAEMON_PID=$!

# Wait briefly to confirm it started
sleep 2
if kill -0 "$DAEMON_PID" 2>/dev/null; then
    ok "Full automation stack started (PID $DAEMON_PID)"
    echo ""
    echo "  To monitor:  tail -f ${OUTPUT_DIR}/automation_daemon.log"
    echo "  To stop:     ./run_automation.sh --stop"
    echo "  To check:    ./run_automation.sh --status"
    echo ""
else
    err "Daemon failed to start. Check: $DAEMON_LOG"
    exit 1
fi
