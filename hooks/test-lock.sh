#!/usr/bin/env bash
# test-lock.sh — PreToolUse hook (Write|Edit). Monolithic TDD: no role separation.
#
# If the target is tests/*.test.js AND .stanok-locks/<mod>.lock already exists -> deny
# (fail-closed). The lock is set by verifier.sh on the FIRST real run of the test
# (only for tests with real assertions — see the Goodhart guard in verifier.sh).
#
# The point: the agent must not rewrite a locked test "to make it pass" (Goodhart).
# Only the operator (outside the sandbox) may remove the lock.
# REPO_ROOT is derived from the script location — the hook is portable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOCK_DIR="$REPO_ROOT/.stanok-locks"
LOG_DIR="$REPO_ROOT/.stanok-logs"
LOG="$LOG_DIR/test-lock.log"

INPUT="$(cat)"
FP="$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // .tool_input.path // empty' 2>/dev/null || true)"

[ -n "$FP" ] || exit 0   # broken input — no verdict

case "$FP" in
  /*) ;;
  *) FP="$REPO_ROOT/$FP" ;;
esac
ABS="$(realpath -m "$FP")"

# SEC-01: the model must not write TDD state files directly — .stanok-locks is
# managed exclusively by verifier.sh (hook shell code, invisible to this gate).
case "$ABS" in
  "$REPO_ROOT/.stanok-locks/"*)
    mkdir -p "$LOG_DIR"
    echo "$(date +%T) DENY locks path=$ABS" >> "$LOG"
    printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"test-lock: the model cannot write to .stanok-locks (TDD state is managed by verifier.sh only)"}}\n'
    exit 0
    ;;
esac

case "$ABS" in
  "$REPO_ROOT/tests/"*.test.js) ;;
  *) exit 0 ;;   # not a test — the gate is not our concern
esac

# SEC-02: key = test path relative to REPO_ROOT with '/' -> '_' (no basename
# collisions across subdirectories: tests/fire/ui.test.js -> tests_fire_ui.test.js).
REL="${ABS#"$REPO_ROOT"/}"
KEY="${REL//\//_}"

# The lock exists -> deny (any caller; roles are gone).
if [ -f "$LOCK_DIR/$KEY.lock" ]; then
  mkdir -p "$LOG_DIR"
  echo "$(date +%T) DENY key=$KEY path=$ABS" >> "$LOG"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"test-lock: test %s is locked after the TDD red->green cycle"}}\n' "$KEY"
fi
exit 0
