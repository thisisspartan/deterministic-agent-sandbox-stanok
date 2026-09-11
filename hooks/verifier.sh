#!/usr/bin/env bash
# verifier.sh — PostToolUse hook (Write|Edit). OS-level TDD freeze (D2).
#
# Replaces the .stanok-locks hash state machine. The "spec cannot be weakened"
# invariant is now an OS fact, not a detection:
#   - When a written test runs RED (the spec is written and failing), the test
#     file is made read-only: chmod a-w. The model's next Write/Edit then fails
#     at the kernel (EACCES) and it cannot undo the mode — its only shell is
#     bash-gate -> scripts/run.sh, which cannot chmod.
#   - The file is frozen, NOT the tests/ directory: a ticket may declare several
#     test files, and a read-only directory would block creating the rest.
#
# The runner unfreezes the workspace (chmod u+w tests/) at the start of every
# run (prepare_workspace), so each run's phase 1 can write tests again.
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

# RED (including rc=124 timeout): the spec is written and failing -> freeze it.
chmod a-w "$ABS" 2>/dev/null || true
emit "VERIFY: RED CONFIRMED ($REL rc=$RC; test frozen read-only — the spec cannot be weakened). Implement src/ to make it GREEN.
$(tail_block "$OUT")"
exit 0
