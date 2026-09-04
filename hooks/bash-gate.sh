#!/usr/bin/env bash
# bash-gate.sh — PreToolUse hook (Bash) for the claude machine.
# The model gets Bash in exactly one form: `bash scripts/run.sh ...`
# (sandbox: fixed subcommands test/smoke/list, see scripts/run.sh).
# Everything else — deny. Direct shell, operators, other binaries — forbidden.
# Protocol as in path-guard.sh: stdin = call JSON; deny = permissionDecision.
set -euo pipefail

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"bash-gate: %s"}}' "$1"
  exit 0
}

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('command',''))
except Exception:
    print('')
")"

[ -n "$CMD" ] || deny "no command / malformed input"

# Shell operators and substitutions — deny immediately (no pipes, no redirects, no $(...)).
case "$CMD" in
  *"|"*|*";"*|*"&"*|*'$('*|*'`'*|*">"*|*"<"*|*$'\n'*) deny "shell operators/substitution not allowed" ;;
esac

# Exactly one form is allowed: [bash ](./)scripts/run.sh <args>
if [[ "$CMD" =~ ^[[:space:]]*(bash[[:space:]]+)?(\./)?scripts/run\.sh[[:space:]]+.*$ ]]; then
  exit 0   # allow — run.sh itself validates the rest
else
  deny "only 'bash scripts/run.sh <test|smoke|list> ...' is allowed"
fi
