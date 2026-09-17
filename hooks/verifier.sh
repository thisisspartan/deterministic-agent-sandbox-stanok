#!/usr/bin/env bash
# verifier.sh — PostToolUse hook (Write|Edit).
#
# The "spec cannot be weakened" invariant is enforced by the runner's tests/
# manifest (contract_lock): stanok.py snapshots tests/ before the session and
# after each turn; a pre-existing test file that is modified or deleted is a
# contract_lock violation in summary.json. This hook no longer freezes files.
#
# Its remaining job: when a written test runs RED (the spec is written and
# failing), report it to the model so it goes straight to the implementation.
#
# The verdict itself comes from the project's declared runner (D3):
# scripts/run.sh is the single canonical test invocation.
#
# REPO_ROOT is derived from the script location (<repo>/hooks/verifier.sh).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

INPUT=$(cat)
FP=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FP" ] && exit 0

if [[ "$FP" != /* ]]; then FP="$REPO_ROOT/$FP"; fi
ABS="$(realpath -m "$FP")"

# Only writes under tests/ are our concern; everything else is silent.
case "$ABS" in
  "$REPO_ROOT/tests/"*) ;;
  *) exit 0 ;;
esac
[ -f "$ABS" ] || exit 0

RUN_SH="$REPO_ROOT/scripts/run.sh"
[ -f "$RUN_SH" ] || exit 0

REL="${ABS#"$REPO_ROOT"/}"

emit() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$r}}'
}
tail_block() {
  printf '%s' "$1" | tail -25
}

# Run the test through the project entrypoint (outer timeout > run.sh's own, so
# run.sh's rc=124 is the deterministic verdict on a hung test).
OUT="$(cd "$REPO_ROOT" && timeout 75 bash "$RUN_SH" test "$REL" 2>&1)"
RC=$?

# rc=2: the runner refused the path (not a test in its terms) -> not our concern.
[ "$RC" -eq 2 ] && exit 0

# GREEN -> the implementation already exists; nothing to freeze, stay silent.
[ "$RC" -eq 0 ] && exit 0

# RED (including rc=124 timeout): the spec is written and failing -> report it.
emit "VERIFY: RED CONFIRMED ($REL rc=$RC). Implement src/ to make it GREEN.
$(tail_block "$OUT")"
exit 0
