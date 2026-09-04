#!/usr/bin/env bash
# bash-gate.sh — PreToolUse hook (Bash) для claude-станка.
# Модель получает Bash ТОЛЬКО в одной форме: `bash scripts/run.sh ...`
# (писочница: фиксированные подкоманды test/smoke/list, см. scripts/run.sh).
# Всё остальное — deny. Прямой shell, операторы, другие бинари — запрещены.
# Протокол как в path-guard.sh: stdin = JSON вызова; deny = permissionDecision.
set -euo pipefail

deny() {
  printf '{"hookSpecificOutput":{"hookEventName":"PreToolUse","permissionDecision":"deny","permissionDecisionReason":"bash-gate: %s"}}' "$1"
  exit 0
}

INPUT="$(cat)"
CMD="$(printf '%s' "$INPUT" | python3 -c "
import json,sys
try:
    print(json.load(sys.stdin).get('tool_input',{}).get('command',''))
except Exception:
    print('')
")"

[ -n "$CMD" ] || deny "no command / malformed input"

# Shell-операторы и подстановки — сразу deny (ни пайпов, ни редиректов, ни $(...)).
case "$CMD" in
  *"|"*|*";"*|*"&"*|*'$('*|*'`'*|*">"*|*"<"*|*$'\n'*) deny "shell operators/substitution not allowed" ;;
esac

# Разрешена ровно одна форма: [bash ](./)scripts/run.sh <args>
if [[ "$CMD" =~ ^[[:space:]]*(bash[[:space:]]+)?(\./)?scripts/run\.sh[[:space:]]+.*$ ]]; then
  exit 0   # allow — остальное валидирует сам run.sh
else
  deny "only 'bash scripts/run.sh <test|smoke|list> ...' is allowed"
fi
