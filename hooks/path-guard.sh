#!/usr/bin/env bash
# path-guard.sh — PreToolUse hook (Write|Edit) для claude-станка.
# Запрещает запись ВНЕ allowed-write-path (src/, tests/, docs/) внутри репо.
# Протокол (VERIFIED P2/P-hooks-untrusted): stdin = JSON вызова;
# stdout = hookSpecificOutput с permissionDecision ("deny" перекрывает acceptEdits).
# Без вывода = allow.
#
# REPO_ROOT выводится из расположения скрипта (<repo>/hooks/path-guard.sh) —
# хук переносимый: скопировал репо — работает.
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

# FINDING-4: нет file_path / битый JSON — гейт НЕ пропускает.
[ -n "$FP" ] || deny "no file_path / malformed input"

# FINDING-3: относительный путь -> абсолютный через REPO_ROOT (не полагаемся на CWD).
case "$FP" in
  /*) ;;
  *) FP="$REPO_ROOT/$FP" ;;
esac

# realpath -m: нормализация + разворачивание symlink (защита P-symlink).
ABS="$(realpath -m "$FP")"

case "$ABS" in
  "$REPO_ROOT"/*) ;;   # внутри репо — дальше
  *) deny "outside repo: $ABS" ;;
esac

case "$ABS" in
  "$REPO_ROOT/src/"*|"$REPO_ROOT/tests/"*|"$REPO_ROOT/docs/"*) ;;
  *) deny "protected path: $ABS" ;;
esac

printf '{"systemMessage":"path-guard: allow %s"}' "${ABS#"$REPO_ROOT"/}"
exit 0
