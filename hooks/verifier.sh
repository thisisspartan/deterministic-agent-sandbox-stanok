#!/usr/bin/env bash
# verifier.sh — GENERIC PostToolUse verifier for the stanok (deterministic, property-based).
#
# Convention (task repo layout):  src/<mod>.js  <->  tests/<mod>.test.js
#
# Rule — on Write|Edit of a file under src/ or tests/:
#   * if the matching test file exists  -> run `node tests/<mod>.test.js` from REPO_ROOT;
#       rc=0 => VERIFY: PASS, else VERIFY: FAIL (reason = first fail line).
#   * if no matching test exists yet    -> NO verdict (a non-existent test cannot be run).
#   * files outside src/ and tests/     -> NO verdict.
# A NO-verdict exit is silent: nothing is appended to the model context, nothing denied.
#
# REPO_ROOT is DERIVED from the script's own location (<repo>/hooks/verifier.sh), so this
# SAME script works for ANY task repo — no module name, seed or directory is hardcoded.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"

INPUT=$(cat)
FP=$(printf '%s' "$INPUT" | jq -r '.tool_input.file_path // empty')
[ -z "$FP" ] && exit 0

# Relative file_path is anchored to REPO_ROOT (CWD-independence, like path-guard).
if [[ "$FP" != /* ]]; then FP="$REPO_ROOT/$FP"; fi
ABS="$(realpath -m "$FP")"

# Only src/*.js and tests/*.test.js are verification targets; everything else: silent.
MOD=""
case "$ABS" in
  "$REPO_ROOT/src/"*.js)           MOD="$(basename "$ABS" .js)" ;;
  "$REPO_ROOT/tests/"*.test.js)    MOD="$(basename "$ABS" .test.js)" ;;
  *) exit 0 ;;
esac
[ -z "$MOD" ] && exit 0

TEST="$REPO_ROOT/tests/$MOD.test.js"
[ -f "$TEST" ] || exit 0   # no matching test yet -> cannot verify -> silent

# C1 test-lock: при ПЕРВОМ реальном прогоне теста (test существует) — ставим лок
# .stanok-locks/<mod>.lock. Лок создаёт hook (shell-код в CLI-процессе), а НЕ модель
# через tool-call -> PreToolUse path-guard (гейт модельных Write/Edit) его не видит.
# mkdir -p — защита от отсутствующей директории на первом локе.
mkdir -p "$REPO_ROOT/.stanok-locks"
touch "$REPO_ROOT/.stanok-locks/$MOD.lock"

OUT="$(cd "$REPO_ROOT" && node "$TEST" 2>&1)"
RC=$?
if [ "$RC" -eq 0 ]; then
  REASON="node tests/$MOD.test.js rc=0 (all tests passed)"
  jq -n --arg r "VERIFY: PASS reason: $REASON" \
    '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$r}}'
else
  FIRST="$(printf '%s' "$OUT" | grep -iE 'fail|expected|assert|error|not ok' | head -1)"
  REASON="node tests/$MOD.test.js rc=$RC ${FIRST:-unknown failure}"
  jq -n --arg r "VERIFY: FAIL reason: $REASON" \
    '{hookSpecificOutput:{hookEventName:"PostToolUse",additionalContext:$r}}'
fi
