#!/usr/bin/env bash
# test-lock.sh — PreToolUse hook (Write|Edit). Role separation coder/tester.
#
# If the target is tests/*.test.js AND .stanok-locks/<mod>.lock already exists AND the caller
# is NOT the tester subagent (discriminator — .agent_type in the PreToolUse base-context) -> deny
# (fail-closed). The lock is set by verifier.sh on the FIRST real run of the test.
#
# The point: the main agent (coder) must not rewrite the test "to make it pass" (Goodhart);
# only the tester subagent may edit a locked test (also a local model —
# "weakening" it is closed off by the verifier gate).
#
# Discriminator P2-confirmed: main = 'mainThreadAgentType' (or empty), tester = 'tester'.
# REPO_ROOT is derived from the script location — the hook is portable.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
LOCK_DIR="$REPO_ROOT/.stanok-locks"
LOG_DIR="$REPO_ROOT/.stanok-logs"
LOG="$LOG_DIR/test-lock.log"

INPUT="$(cat)"
FP="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('file_path',''))
except Exception:
    print('')
")"
AT="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('agent_type','') or '')
except Exception:
    print('')
")"
AID="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    d=json.load(sys.stdin)
    print(d.get('agent_id','') or '')
except Exception:
    print('')
")"

[ -n "$FP" ] || exit 0   # broken input — no verdict (fail-closed is not our case, path-guard gates it)

case "$FP" in
  /*) ;;
  *) FP="$REPO_ROOT/$FP" ;;
esac
ABS="$(realpath -m "$FP")"

case "$ABS" in
  "$REPO_ROOT/tests/"*.test.js) ;;
  *) exit 0 ;;   # not a test — the gate is not our concern
esac

MOD="$(basename "$ABS" .test.js)"

# The lock exists AND the caller is NOT the tester (grep 'tester' in agent_type) -> deny.
if [ -f "$LOCK_DIR/$MOD.lock" ] && ! printf '%s' "$AT" | grep -q "tester"; then
  mkdir -p "$LOG_DIR"
  echo "$(date +%T) DENY mod=$MOD agent_type='$AT' agent_id='$AID' path=$ABS" >> "$LOG"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"test-lock: test %s is locked, only the tester may edit it (agent_type=%s)"}}' "$MOD" "$AT"
else
  printf '{"systemMessage":"test-lock: allow %s (agent_type=%s)"}' "$MOD" "$AT"
fi
exit 0
