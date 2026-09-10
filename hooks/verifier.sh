#!/usr/bin/env bash
# verifier.sh — PostToolUse verifier with the Red-Before-Green (TDD) state machine.
#
# Convention (task repo layout):  src/<mod>.js  <->  tests/<mod>.test.js
#
# State files in .stanok-locks/ (key = test path relative to REPO_ROOT, '/' -> '_'):
#   <key>.red   — the test was confirmed RED; stores sha256 of the test file at that moment.
#   <key>.lock  — the test went GREEN with an unchanged hash; the test is now frozen
#                 (PreToolUse test-lock.sh denies any further Write|Edit of it).
#
# Phases (on Write|Edit of src/*.js or tests/*.test.js, when the matching test exists):
#   A (no .red, no .lock):
#       green + NEW test file (absent from git HEAD)  -> VERIFY: FAIL (TAUTOLOGY)
#       green + existing test file                    -> lock (legit extension of a working suite)
#       red + SyntaxError                             -> VERIFY: FAIL (INVALID_RED)
#       red + timeout (rc=124)                        -> VERIFY: FAIL (TIMEOUT)
#       red + anything else                           -> write .red, VERIFY: RED CONFIRMED
#   B (.red exists, no .lock):
#       green + hash == .red                          -> mv .red .lock, VERIFY: PASS (TDD verified)
#       green + hash != .red                          -> rm .red, VERIFY: FAIL (TAMPERING)
#       red                                           -> VERIFY: FAIL
#   C (.lock exists):
#       hash != .lock                                 -> VERIFY: FAIL (TAMPERING)
#       green                                         -> VERIFY: PASS
#       red                                           -> VERIFY: FAIL
#
# The hook CANNOT undo a Write (PostToolUse) — it only reports the verdict into the
# model context. Hard enforcement is the final TDD gate in launcher/stanok.py
# (tdd_gate): every test touched this session must end with a .lock; any lingering
# .red fails the run (fail-closed).
#
# REPO_ROOT is DERIVED from the script's own location (<repo>/hooks/verifier.sh), so this
# SAME script works for ANY task repo — no module name, seed or directory is hardcoded.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

INPUT=$(cat)
FP=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FP" ] && exit 0

# Relative file_path is anchored to REPO_ROOT (CWD-independence).
if [[ "$FP" != /* ]]; then FP="$REPO_ROOT/$FP"; fi
ABS="$(realpath -m "$FP")"

# Only src/*.js and tests/*.test.js are verification targets; everything else: silent.
MOD=""
case "$ABS" in
  "$REPO_ROOT/src/"*.js)         MOD="$(basename "$ABS" .js)" ;;
  "$REPO_ROOT/tests/"*.test.js)  MOD="$(basename "$ABS" .test.js)" ;;
  *) exit 0 ;;
esac
[ -z "$MOD" ] && exit 0

TEST="$REPO_ROOT/tests/$MOD.test.js"
[ -f "$TEST" ] || exit 0   # no matching test yet -> cannot verify -> silent

LOCK_DIR="$REPO_ROOT/.stanok-locks"
mkdir -p "$LOCK_DIR"
REL="${TEST#"$REPO_ROOT"/}"
KEY="${REL//\//_}"
RED_F="$LOCK_DIR/$KEY.red"
LOCK_F="$LOCK_DIR/$KEY.lock"

hash_of() { sha256sum "$1" | awk '{print $1}'; }
stored_hash() {
    local file="$1"
    if [ -f "$file" ]; then
        awk '{print $1}' "$file" || {
            echo "[verifier] ERROR: unreadable or corrupted lock file: $file" >&2
            return 1
        }
    fi
}
emit() {
  jq -n --arg r "$1" '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$r}}'
}
fail_block() {
  # TAP output: first "not ok" block (test line + indented assertion lines);
  # non-TAP output: tail with the stack. Cap at 25 lines to keep the context small.
  if printf '%s' "$1" | grep -qE '^not ok '; then
    printf '%s' "$1" | awk '/^not ok /{f=1} f{print} f && /^$/{exit}' | head -25
  else
    printf '%s' "$1" | tail -25
  fi
}

# Run the test (bounded: a hung test must not hang the hook and the model turn).
OUT="$(cd "$REPO_ROOT" && timeout 60 node "$TEST" 2>&1)"
RC=$?

# Is the test file new (absent from git HEAD)?
IS_NEW=0
if ! (cd "$REPO_ROOT" && git ls-files --error-unmatch -- "$REL" >/dev/null 2>&1); then
  IS_NEW=1
fi

CUR_HASH="$(hash_of "$TEST")"

if [ -f "$LOCK_F" ]; then
  # ---- Phase C: locked (frozen after the TDD cycle) ----
  STORED="$(stored_hash "$LOCK_F")" || { emit "VERIFY: FAIL (LOCK-CORRUPT: cannot read $LOCK_F)"; exit 1; }
  if [ -n "$STORED" ] && [ "$STORED" != "$CUR_HASH" ]; then
    emit "VERIFY: FAIL (TAMPERING: test $REL changed after lock)"
    exit 1
  fi
  if [ "$RC" -eq 0 ]; then
    emit "VERIFY: PASS reason: node $REL rc=0 (locked test still green)"
    exit 0
  fi
  emit "VERIFY: FAIL reason: node $REL rc=$RC $(fail_block "$OUT")"
  exit 1
elif [ -f "$RED_F" ]; then
  # ---- Phase B: red confirmed, waiting for green ----
  if [ "$RC" -eq 0 ]; then
    STORED="$(stored_hash "$RED_F")" || { emit "VERIFY: FAIL (RED-CORRUPT: cannot read $RED_F)"; exit 1; }
    if [ -n "$STORED" ] && [ "$STORED" = "$CUR_HASH" ]; then
      mv "$RED_F" "$LOCK_F"
      emit "VERIFY: PASS (TDD verified: red->green, test file unchanged)"
      exit 0
    fi
    rm -f "$RED_F"
    emit "VERIFY: FAIL (TAMPERING: test $REL changed between RED and GREEN)"
    exit 1
  fi
  emit "VERIFY: FAIL reason: node $REL rc=$RC $(fail_block "$OUT") (still red — implement src/)"
  exit 1
else
  # ---- Phase A: fresh test, no state ----
  if [ "$RC" -eq 0 ]; then
    if [ "$IS_NEW" -eq 1 ]; then
      emit "VERIFY: FAIL (TAUTOLOGY: new test $REL passed without a RED phase — write a failing test first)"
      exit 1
    fi
    # Goodhart guard: never lock an empty or assertion-less test file.
    if [ ! -s "$TEST" ] || ! grep -qE 'assert|test\(' "$TEST"; then
      emit "VERIFY: FAIL (NO ASSERTIONS: test $REL is empty or has no assertions — cannot lock)"
      exit 1
    fi
    printf '%s  %s\n' "$CUR_HASH" "$REL" > "$LOCK_F"
    emit "VERIFY: PASS reason: node $REL rc=0 (existing suite extended, locked)"
    exit 0
  fi
  if [ "$RC" -eq 124 ]; then
    emit "VERIFY: FAIL (TIMEOUT: test $REL hung > 60s)"
    exit 1
  fi
  if printf '%s' "$OUT" | grep -q 'SyntaxError'; then
    emit "VERIFY: FAIL (INVALID_RED: SyntaxError in $REL — fix the test syntax)"
    exit 1
  fi
  printf '%s  %s\n' "$CUR_HASH" "$REL" > "$RED_F"
  emit "VERIFY: RED CONFIRMED ($REL). Implement src/ to make it GREEN. The test hash is now frozen."
  exit 0
fi
