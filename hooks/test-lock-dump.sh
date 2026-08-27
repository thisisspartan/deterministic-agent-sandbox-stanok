#!/usr/bin/env bash
# test-lock-dump.sh — P2-probe hook: ДАМП полного PreToolUse-инпута (без вердикта).
# Запускается на копии ТОЛЬКО для подтверждения значений .agent_type (main Write vs
# tester Write). Не участвует в боевом контуре.
# REPO_ROOT выводится из расположения скрипта — хук переносимый.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
DUMP_DIR="$REPO_ROOT/.stanok-logs/dump"
mkdir -p "$DUMP_DIR"
cat >> "$DUMP_DIR/ptu-inputs.jsonl"
exit 0
