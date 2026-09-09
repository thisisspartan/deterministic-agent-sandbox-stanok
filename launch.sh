#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$DIR"
export STANOK_REPO="${STANOK_REPO:-$PROJECT_ROOT}"
cd "$PROJECT_ROOT"

PY="${STANOK_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: python не найден: $PY" >&2
    echo "  Разверни окружение: $DIR/setup.sh  (создаёт .venv с claude-agent-sdk)" >&2
    exit 99
fi

STANOK_PY="$DIR/launcher/stanok.py"
SANDBOX="$DIR/sandbox-run.sh"
LOG_DIR="${STANOK_LOG_DIR:-/tmp/stanok-logs}"
mkdir -p "$LOG_DIR"

# Передаем найденный claude, если он есть на хосте
if command -v claude &>/dev/null; then
    export STANOK_CLAUDE_BIN="$(command -v claude)"
fi

cmd="${1:-}"

# Команды статуса, остановки и логов
if [ "$cmd" = "status" ] || [ "$cmd" = "stop" ] || [ "$cmd" = "watch" ]; then
    exec "$PY" "$STANOK_PY" "$@"
fi

if [ "$cmd" = "run" ]; then
    shift
fi

if [ "$#" -lt 2 ]; then
    echo "Использование: $0 [run] <ticket> <label> [--background] [--local-retries N] [--direct] [-- extra...]" >&2
    echo "              $0 status <label>" >&2
    echo "              $0 stop <label>" >&2
    echo "              $0 watch <label> [--follow]" >&2
    exit 1
fi

TICKET="$1"
shift

BACKGROUND=0
DIRECT=0
RETRIES=""
EXTRA_ARGS=()
LABEL=""

# Сепаратор `--`: всё после него уходит в Python как есть (label + extra-args),
# bash больше не сканирует свои флаги.
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

# Флаги Python идут ДО `--`: после сепаратора argparse считает всё позиционным.
PY_FLAGS=()
if [ "$DIRECT" -eq 1 ]; then
    PY_FLAGS+=(--direct)
fi
if [ -n "$RETRIES" ]; then
    PY_FLAGS+=(--local-retries "$RETRIES")
fi

if [ "$BACKGROUND" -eq 1 ]; then
    LAUNCH_LOG="$LOG_DIR/${LABEL}.launch.log"
    EVIDENCE_DIR="$PROJECT_ROOT/evidence/${LABEL}"
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

    echo "Станок запущен в фоне (PID $BG_PID). Лог: $LAUNCH_LOG"
    exit 0
fi

# Синхронный режим
if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
    exec "$SANDBOX" "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}"
else
    exec "$PY" "$STANOK_PY" run "$TICKET" "${PY_FLAGS[@]}" -- "$LABEL" "${EXTRA_ARGS[@]}"
fi
