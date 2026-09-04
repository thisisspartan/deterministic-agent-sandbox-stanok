#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$DIR"
export STANOK_REPO="$PROJECT_ROOT"
cd "$PROJECT_ROOT"

PY="${STANOK_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: python not found: $PY" >&2
    echo "  Set up the environment: $DIR/setup.sh  (creates .venv with claude-agent-sdk)" >&2
    exit 99
fi

STANOK_PY="$DIR/launcher/stanok.py"
SANDBOX="$DIR/sandbox-run.sh"
LOG_DIR="${STANOK_LOG_DIR:-/tmp/stanok-logs}"
mkdir -p "$LOG_DIR"

# Pass the found claude, if it exists on the host
if command -v claude &>/dev/null; then
    export STANOK_CLAUDE_BIN="$(command -v claude)"
fi

cmd="${1:-}"

# Status, stop, and log commands
if [ "$cmd" = "status" ] || [ "$cmd" = "stop" ] || [ "$cmd" = "watch" ]; then
    exec "$PY" "$STANOK_PY" "$@"
fi

if [ "$cmd" = "run" ]; then
    shift
fi

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 [run] <ticket> <label> [--background] [--local-retries N] [--direct]" >&2
    echo "              $0 status <label>" >&2
    echo "              $0 stop <label>" >&2
    echo "              $0 watch <label> [--follow]" >&2
    exit 1
fi

TICKET="$1"
LABEL="$2"
shift 2

BACKGROUND=0
EXTRA_ARGS=()

while [ "$#" -gt 0 ]; do
    case "$1" in
        --background)
            BACKGROUND=1
            shift
            ;;
        *)
            EXTRA_ARGS+=("$1")
            shift
            ;;
    esac
done

if [ "$BACKGROUND" -eq 1 ]; then
    LAUNCH_LOG="$LOG_DIR/${LABEL}.launch.log"
    EVIDENCE_DIR="$PROJECT_ROOT/evidence/${LABEL}"
    MARKER_PATH="$EVIDENCE_DIR/.running"

    mkdir -p "$EVIDENCE_DIR"

    if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
        nohup "$SANDBOX" "$PY" "$STANOK_PY" run "$TICKET" "$LABEL" "${EXTRA_ARGS[@]}" >> "$LAUNCH_LOG" 2>&1 &
    else
        nohup "$PY" "$STANOK_PY" run "$TICKET" "$LABEL" "${EXTRA_ARGS[@]}" >> "$LAUNCH_LOG" 2>&1 &
    fi
    BG_PID=$!

    START_TS=$(date +%s)
    echo "$START_TS $BG_PID" > "$MARKER_PATH"

    echo "Machine launched in the background (PID $BG_PID). Log: $LAUNCH_LOG"
    exit 0
fi

# Synchronous mode
if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
    exec "$SANDBOX" "$PY" "$STANOK_PY" run "$TICKET" "$LABEL" "${EXTRA_ARGS[@]}"
else
    exec "$PY" "$STANOK_PY" run "$TICKET" "$LABEL" "${EXTRA_ARGS[@]}"
fi
