#!/usr/bin/env bash
# agent-gate.sh — PreToolUse hook (Task|Agent). Жёсткий гейт спавна субагентов.
# Разрешает ТОЛЬКО subagent_type в {reviewer, tester}; любой другой Agent -> deny.
# stdout без вывода = allow. Лог-строка — свидетельство срабатывания hook на Agent.
# REPO_ROOT выводится из расположения скрипта — хук переносимый.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOG_DIR="$REPO_ROOT/.stanok-logs"
LOG="$LOG_DIR/agent-gate.log"

ST="$(cat | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('subagent_type',''))
except Exception:
    print('')
")"

mkdir -p "$LOG_DIR"
echo "$(date +%T) hook-fired subagent_type='$ST'" >> "$LOG"

case "$ST" in
  reviewer|tester)
    printf '{"systemMessage":"agent-gate: allow %s"}' "$ST"
    ;;
  *)
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"agent-gate: только reviewer/tester"}}'
    ;;
esac
exit 0
