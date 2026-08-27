#!/usr/bin/env bash
# test-lock.sh — PreToolUse hook (Write|Edit). Роль-разделение coder/tester.
#
# Если цель — tests/*.test.js И .stanok-locks/<mod>.lock уже существует И вызывающий
# НЕ tester-субагент (дискриминатор — .agent_type в base-context PreToolUse) -> deny
# (fail-closed). Лок ставит verifier.sh на ПЕРВОМ реальном прогоне теста.
#
# Смысл: main-агент (coder) не должен переписывать тест «чтоб прошёл» (Goodhart);
# править залоченный тест может только tester-субагент (тоже локальная модель —
# его «ослабить» закрывает verifier-гейт).
#
# Дискриминатор P2-подтверждён: main = 'mainThreadAgentType' (или пусто), tester = 'tester'.
# REPO_ROOT выводится из расположения скрипта — хук переносимый.
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

[ -n "$FP" ] || exit 0   # битый инпут — без вердикта (fail-closed не наш случай, путь-guard гейтит)

case "$FP" in
  /*) ;;
  *) FP="$REPO_ROOT/$FP" ;;
esac
ABS="$(realpath -m "$FP")"

case "$ABS" in
  "$REPO_ROOT/tests/"*.test.js) ;;
  *) exit 0 ;;   # не тест — гейт не наша забота
esac

MOD="$(basename "$ABS" .test.js)"

# Лок есть И вызывающий НЕ tester (grep 'tester' в agent_type) -> deny.
if [ -f "$LOCK_DIR/$MOD.lock" ] && ! printf '%s' "$AT" | grep -q "tester"; then
  mkdir -p "$LOG_DIR"
  echo "$(date +%T) DENY mod=$MOD agent_type='$AT' agent_id='$AID' path=$ABS" >> "$LOG"
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"test-lock: тест %s залочен, править только tester (agent_type=%s)"}}' "$MOD" "$AT"
else
  printf '{"systemMessage":"test-lock: allow %s (agent_type=%s)"}' "$MOD" "$AT"
fi
exit 0
