#!/usr/bin/env bash
# agent-gate.sh — PreToolUse hook (Task|Agent). Hard gate on subagent spawning.
# Allows ONLY subagent_type in {reviewer, tester}; any other Agent -> deny.
# stdout with no output = allow. The log line is evidence of the hook firing on Agent.
# REPO_ROOT is derived from the script location — the hook is portable.
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
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"agent-gate: reviewer/tester only"}}'
    ;;
esac
exit 0
