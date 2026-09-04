#!/usr/bin/env bash
# path-guard.sh — PreToolUse hook (Write|Edit) for the claude machine.
# Forbids writes OUTSIDE the allowed-write-path (src/, tests/, docs/) inside the repo.
# Protocol (VERIFIED P2/P-hooks-untrusted): stdin = call JSON;
# stdout = hookSpecificOutput with permissionDecision ("deny" overrides acceptEdits).
# No output = allow.
#
# REPO_ROOT is derived from the script location (<repo>/hooks/path-guard.sh) —
# the hook is portable: copy the repo — it works.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"path-guard: %s"}}' "$1"
  exit 0
}

INPUT="$(cat)"
FP="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('tool_input',{}).get('file_path',''))
except Exception:
    print('')
")"

# FINDING-4: no file_path / broken JSON — the gate does NOT let it through.
[ -n "$FP" ] || deny "no file_path / malformed input"

# FINDING-3: relative path -> absolute via REPO_ROOT (do not rely on CWD).
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
  "$REPO_ROOT/src/"*|"$REPO_ROOT/tests/"*|"$REPO_ROOT/docs/"*) ;;
  *) deny "protected path: $ABS" ;;
esac

printf '{"systemMessage":"path-guard: allow %s"}' "${ABS#"$REPO_ROOT"/}"
exit 0
