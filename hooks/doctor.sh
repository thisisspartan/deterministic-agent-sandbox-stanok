#!/usr/bin/env bash
# doctor.sh — структурные инварианты claude-станка (аналог grok doctor).
# Вызывается из claude-stanok.sh ДО exec claude (P3: SessionStart exit!=0 НЕ абортит -p).
# Печатает "N ok, M fail"; exit 0 ТОЛЬКО если все проверки прошли.
# REPO_ROOT выводится из расположения скрипта — хук переносимый.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
OK=0; FAIL=0

chk() { # chk <name> <cmd...>
  local name="$1"; shift
  if "$@" >/dev/null 2>&1; then
    OK=$((OK+1)); echo "ok   $name"
  else
    FAIL=$((FAIL+1)); echo "FAIL $name"
  fi
}

chk "settings.stanok.json exists"     test -f "$REPO_ROOT/.claude/settings.stanok.json"
chk "settings.stanok.json valid JSON" python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$REPO_ROOT/.claude/settings.stanok.json"
chk "PreToolUse hook present"         grep -q '"PreToolUse"' "$REPO_ROOT/.claude/settings.stanok.json"
chk "path-guard.sh executable"        test -x "$REPO_ROOT/hooks/path-guard.sh"
chk "commit-msg executable"           test -x "$REPO_ROOT/hooks/commit-msg"
chk "commit-msg .git symlink"         test -L "$REPO_ROOT/.git/hooks/commit-msg"   # FINDING-5: сломанный symlink снимает TASK-ID гейт
chk "CLAUDE.md exists"                test -f "$REPO_ROOT/CLAUDE.md"
chk "write-path src/tests/docs"       test -d "$REPO_ROOT/src" -a -d "$REPO_ROOT/tests" -a -d "$REPO_ROOT/docs"
chk "git repo initialized"            test -d "$REPO_ROOT/.git"

# --- ПАТЧ 5: инвариант тишины cloud --------------------------------------------
# Единственный артефакт cloud_review() — cloud-review-*.jsonl в evidence. Без явного
# --cloud (DOCTOR_EXPECT_NO_CLOUD=1, выставляет лаунчер) за окно WINDOW_H таких файлов
# быть НЕ должно. Ложный вызов облака (утечка кред/конфига) => FAIL => прогон абортится.
EVIDENCE="${STANOK_EVIDENCE:-$REPO_ROOT/evidence}"
WINDOW_H="${DOCTOR_CLOUD_WINDOW_H:-24}"

if [ "${DOCTOR_EXPECT_NO_CLOUD:-0}" = "1" ]; then
  CLOUD_ARTIFACTS="$(find "$EVIDENCE" -maxdepth 1 -name 'cloud-review-*.jsonl' \
    -mmin "-$((WINDOW_H*60))" 2>/dev/null | sort)"
  if [ -z "$CLOUD_ARTIFACTS" ]; then
    OK=$((OK+1)); echo "ok   cloud-silence (нет cloud-review-*.jsonl за ${WINDOW_H}ч)"
  else
    FAIL=$((FAIL+1)); echo "FAIL cloud-silence: cloud-review-*.jsonl найден при DOCTOR_EXPECT_NO_CLOUD=1:"
    printf '%s\n' "$CLOUD_ARTIFACTS" | sed 's/^/     /'
  fi
else
  echo "skip cloud-silence (DOCTOR_EXPECT_NO_CLOUD unset — облако легитимно разрешено)"
fi

echo "--- doctor: $OK ok, $FAIL fail ---"
[ "$FAIL" -eq 0 ]
