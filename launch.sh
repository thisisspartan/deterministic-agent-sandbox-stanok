#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
STANOK_ROOT="$DIR"
export STANOK_REPO="${STANOK_REPO:-$STANOK_ROOT}"
cd "$STANOK_ROOT"

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
if [ "$cmd" = "status" ] || [ "$cmd" = "stop" ]; then
    exec "$PY" "$STANOK_PY" "$@"
fi

if [ "$cmd" = "run" ]; then
    shift
fi

if [ "$#" -lt 2 ]; then
    echo "Usage: $0 [run] <ticket> <label> [--background] [--local-retries N] [--direct]" >&2
    echo "              $0 status <label>" >&2
    echo "              $0 stop <label>" >&2
    exit 1
fi

TICKET="$1"
shift

BACKGROUND=0
DIRECT=0
RETRIES=""
EXTRA_ARGS=()
LABEL=""

# `--` separator: everything after it goes to Python as-is (label + extra-args),
# bash stops scanning its own flags.
if [ "${1:-}" = "--" ]; then
    shift
    LABEL="${1:-}"
    shift
    EXTRA_ARGS=("$@")
else
    LABEL="${1:-}"
    shift
    while [ "$#" -gt 0 ]; do
        case "$1" in
            --)
                shift
                EXTRA_ARGS=("$@")
                break
                ;;
            --background)
                BACKGROUND=1
                shift
                ;;
            --direct)
                DIRECT=1
                shift
                ;;
            --local-retries)
                shift
                if [ "$#" -gt 0 ]; then
                    RETRIES="$1"
                    shift
                fi
                ;;
            *)
                EXTRA_ARGS+=("$1")
                shift
                ;;
        esac
    done
fi

# Python flags go BEFORE `--`: after the separator argparse treats everything as positional.
PY_FLAGS=()
if [ "$DIRECT" -eq 1 ]; then
    PY_FLAGS+=(--direct)
fi
if [ -n "$RETRIES" ]; then
    PY_FLAGS+=(--local-retries "$RETRIES")
fi

# SEC-01: .git is mounted read-only inside the container — no git writes are
# possible there. FAIL-CLOSED (rc=22): the tree must be clean BEFORE launch;
# the supervisor commits machine artifacts / operator state before each run.
# Never reset/clean here — that would silently destroy uncommitted work.
# Single source of truth: stanok.py `check-dirty` (exits 22 when dirty).
if ! "$PY" "$STANOK_PY" check-dirty; then
    echo "ERROR: dirty tree in $STANOK_ROOT (rc=22) — commit or clean before launch" >&2
    exit 22
fi

if [ "$BACKGROUND" -eq 1 ]; then
    LAUNCH_LOG="$LOG_DIR/${LABEL}.launch.log"
    EVIDENCE_DIR="$STANOK_ROOT/evidence/${LABEL}"
    MARKER_PATH="$EVIDENCE_DIR/.running"

    mkdir -p "$EVIDENCE_DIR"

    if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
        nohup "$SANDBOX" "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}" >> "$LAUNCH_LOG" 2>&1 &
    else
        nohup "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}" >> "$LAUNCH_LOG" 2>&1 &
    fi
    BG_PID=$!

    START_TS=$(date +%s)
    echo "$START_TS $BG_PID" > "$MARKER_PATH"

    echo "Machine launched in the background (PID $BG_PID). Log: $LAUNCH_LOG"
    exit 0
fi

# Synchronous mode
if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
    exec "$SANDBOX" "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}"
else
    exec "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}"
fi
