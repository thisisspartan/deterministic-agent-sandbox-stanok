#!/usr/bin/env bash
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"

# Детерминированный cwd = корень проекта (родитель stanok/):
cd "$DIR/.."

PY="${STANOK_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: python не найден: $PY" >&2
    echo "  Разверни окружение: $DIR/setup.sh  (создаёт .venv с claude-agent-sdk)" >&2
    exit 99
fi

SANDBOX="$DIR/sandbox-run.sh"
if [ -x "$SANDBOX" ] && [ "${STANOK_NO_SANDBOX:-0}" != "1" ]; then
    exec "$SANDBOX" "$PY" "$DIR/launcher/stanok.py" "$@"
fi

exec "$PY" "$DIR/launcher/stanok.py" "$@"
