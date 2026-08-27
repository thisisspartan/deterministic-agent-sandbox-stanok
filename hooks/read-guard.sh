#!/usr/bin/env bash
# read-guard.sh — PreToolUse hook (Read|Grep|Glob) для claude-станка.
# Запрещает чтение ВНЕ рабочих зон (src/, tests/, docs/, tickets/) внутри репо
# и чтение ВНЕ репо вообще. Механический барьер: работает в любом permission
# mode (включая bypassPermissions), где can_use_tool не вызывается.
# Протокол (как path-guard.sh): stdin = JSON вызова; stdout = hookSpecificOutput
# с permissionDecision ("deny" перекрывает bypass). Без вывода = allow.
#
# REPO_ROOT выводится из расположения скрипта (<repo>/hooks/read-guard.sh).
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

# Нет file_path/path (например Glob без path) — гейт НЕ пропускает.
[ -n "$FP" ] || deny "no path in input"

# Относительный путь -> абсолютный через REPO_ROOT (не полагаемся на CWD).
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
  "$REPO_ROOT/src/"*|"$REPO_ROOT/tests/"*|"$REPO_ROOT/docs/"*|"$REPO_ROOT/tickets/"*) ;;
  *) deny "protected path: $ABS" ;;
esac

printf '{"systemMessage":"read-guard: allow %s"}' "${ABS#"$REPO_ROOT"/}"
exit 0
