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

# --- Инварианты Runner (launcher/stanok.py; регресс-защита, фидбек «старших братьев») ---
# Все проверки идут через STANOK_PY=системный python3: SDK/telegram импортируются
# лениво, гейты — чистый stdlib, поэтому инварианты работают и без развёрнутого .venv.
# 1) label-guard: label, начинающийся с '--', -> rc=15 ДО flags/ROLE-LEAK/lock
#    (защита от evidence/--background при забытом label). argparse скушает '--background'
#    как флаг сам (rc=2), поэтому проверяем достижимый путь: явный '--'.
# 2) fail-fast: мёртвый сервер -> rc=20 по пути ticket->dirty-tree->lock->pre-flight.
#    На грязном дереве срабатывает dirty-tree (rc=22) ДО pre-flight — это валидный
#    отказ (skip), а не регресс теста.
# 2b) dirty-tree: незакоммиченный файл -> rc=22 (reset --hard + clean -fdq затёр бы
#    операторскую работу; станок отказывается стартовать, TUI коммитит сначала).
# 3) ROLE-LEAK: родительский CLAUDE.md выше репо -> rc=24 ДО lock/mkdir (fail-closed,
#    эквивалент старого rc=25: Runner сам Python, «пропавший python3» больше невозможен).
LAUNCH="$REPO_ROOT/launch.sh"

# 1) label-guard (rc=15): label, начинающийся с '--', -> rc=15 ДО ticket-resolution.
# Тикет СУЩЕСТВУЕТ (mktemp), чтобы при отсутствии label-guard не замаскировался rc=13.
TMPT_LG="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nзаглушка\n' > "$TMPT_LG"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT_LG" -- --background >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner label-guard: label '--background' должен дать rc=15"
else
  RC=$?
  case "$RC" in
    15) OK=$((OK+1)); echo "ok   runner label-guard ('--background' -> rc=15)";;
    *)  FAIL=$((FAIL+1)); echo "FAIL runner label-guard: ожидали rc=15, получили rc=$RC";;
  esac
fi
rm -f "$TMPT_LG"

# 2) fail-fast на мёртвом сервере (rc=20)
TMPT="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nзаглушка\n' > "$TMPT"
DR="doctor-dead-$$-${RANDOM}"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT" "$DR" >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner fail-fast: мёртвый сервер должен дать rc=20, а прогон прошёл"
else
  RC=$?
  case "$RC" in
    20) OK=$((OK+1)); echo "ok   runner fail-fast (мёртвый сервер -> rc=20)";;
    21) echo "skip runner fail-fast (идёт прогон станка — lock занят)";;
    22) echo "skip runner fail-fast (грязное дерево — dirty-tree rc=22 до pre-flight)";;
    *)  FAIL=$((FAIL+1)); echo "FAIL runner fail-fast: ожидали rc=20, получили rc=$RC";;
  esac
fi
rm -rf "$REPO_ROOT/evidence/$DR" "/tmp/stanok-logs/$DR" "$TMPT"

# 2b) dirty-tree: незакоммиченный файл в репо -> rc=22 (fail-closed до pre-flight)
DIRTY="$REPO_ROOT/.doctor-dirty-marker"
printf 'marker\n' > "$DIRTY"
TMPT3="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nзаглушка\n' > "$TMPT3"
if STANOK_PY="$(command -v python3)" STANOK_SERVER_URL=http://127.0.0.1:59999 \
     "$LAUNCH" run "$TMPT3" doctor-dirty-$$ >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner dirty-tree: грязное дерево должно дать rc=22, а прогон прошёл"
else
  RC=$?
  if [ "$RC" -eq 22 ]; then
    OK=$((OK+1)); echo "ok   runner dirty-tree (незакоммиченный файл -> rc=22)"
  else
    FAIL=$((FAIL+1)); echo "FAIL runner dirty-tree: ожидали rc=22, получили rc=$RC"
  fi
fi
rm -rf "$DIRTY" "$REPO_ROOT/evidence/doctor-dirty-$$" "/tmp/stanok-logs/doctor-dirty-$$" "$TMPT3"

# 3) ROLE-LEAK: CLAUDE.md выше репо -> rc=24 (fail-closed, без побочных эффектов)
TMPROOT="$(mktemp -d /tmp/doctor-roleleak-XXXXXX)"
mkdir -p "$TMPROOT/repo"
touch "$TMPROOT/CLAUDE.md"                       # «родительский» CLAUDE.md = утечка роли
TMPT2="$(mktemp /tmp/doctor-ticket-XXXXXX.md)"; printf '# doctor\n\nзаглушка\n' > "$TMPT2"
if STANOK_PY="$(command -v python3)" STANOK_REPO="$TMPROOT/repo" \
     "$LAUNCH" run "$TMPT2" doctor-roleleak-$$ >/dev/null 2>&1; then
  FAIL=$((FAIL+1)); echo "FAIL runner role-leak: родительский CLAUDE.md должен дать rc=24, а прогон прошёл"
else
  RC=$?
  if [ "$RC" -eq 24 ]; then
    OK=$((OK+1)); echo "ok   runner role-leak (родительский CLAUDE.md -> rc=24, до побочных эффектов)"
  else
    FAIL=$((FAIL+1)); echo "FAIL runner role-leak: ожидали rc=24, получили rc=$RC"
  fi
fi
rm -rf "$TMPROOT" "$TMPT2"

echo "--- doctor: $OK ok, $FAIL fail ---"
[ "$FAIL" -eq 0 ]
