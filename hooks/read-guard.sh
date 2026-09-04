#!/usr/bin/env bash
# read-guard.sh — PreToolUse hook (Read|Grep|Glob) for the claude machine.
# Forbids reads OUTSIDE the working zones (src/, tests/, docs/, tickets/) inside the repo
# and reads OUTSIDE the repo altogether. Mechanical barrier: works in any permission
# mode (including bypassPermissions), where can_use_tool is not called.
# Protocol (as in path-guard.sh): stdin = call JSON; stdout = hookSpecificOutput
# with permissionDecision ("deny" overrides bypass). No output = allow.
#
# REPO_ROOT is derived from the script location (<repo>/hooks/read-guard.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"read-guard: %s"}}' "$1"
  exit 0
}

INPUT="$(cat)"
FP="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    ti=d.get('tool_input',{})
    print(ti.get('file_path') or ti.get('path') or '')
except Exception:
    print('')
")"

# No file_path/path (e.g. Glob without path) — the gate does NOT let it through.
[ -n "$FP" ] || deny "no path in input"

# Relative path -> absolute via REPO_ROOT (do not rely on CWD).
case "$FP" in
  /*) ;;
  *) FP="$REPO_ROOT/$FP" ;;
esac

# realpath -m: normalization + symlink resolution (P-symlink protection).
ABS="$(realpath -m "$FP")"

case "$ABS" in
  "$REPO_ROOT"/*) ;;   # inside the repo — continue
  *) deny "outside repo: $ABS" ;;
esac

case "$ABS" in
  "$REPO_ROOT/src/"*|"$REPO_ROOT/tests/"*|"$REPO_ROOT/docs/"*|"$REPO_ROOT/tickets/"*) ;;
  *) deny "protected path: $ABS" ;;
esac

printf '{"systemMessage":"read-guard: allow %s"}' "${ABS#"$REPO_ROOT"/}"
exit 0
