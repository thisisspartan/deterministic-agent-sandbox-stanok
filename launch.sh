#!/usr/bin/env bash
# Запуск станка darkcast изнутри репо.
#
# Что делает:
#   1. Pre-flight: проверяет, что локальный llama-server @ 8080 жив (fail-fast, rc=20).
#   2. Сбрасывает репо в чистое состояние.
#   3. Запускает stanok-sdk-probe.py в фоне (stdout -> launcher.stdout.log).
#   4. Живой форматтер: probe-события + хвост launcher.stdout.log (строки лаунчера видны сразу,
#      ошибки красным) + heartbeat каждые 30s + idle-watchdog (>90s тишины -> предупреждение).
#      Всё дублируется в launch.log (для tail -f из второго терминала).
#      ВАЖНО: live-артефакты (launch.log, probe-*.jsonl, evidence.jsonl) лежат
#      ВНЕ репо (/tmp/stanok-logs/), иначе модель находит их через Glob и читает
#      свой же транскрипт (self-ref loop; расследование — в корне проекта, зона супервайзера).
#      В репо в evidence/<label>/ остаются только summary.json + launcher.stdout.log.
#   5. Итоговый summary-блок: rc, elapsed, VERIFIER/PROBE-RESULT/REVIEW-VERDICT/C5/doctor,
#      пути к evidence.
#
# Режимы:
#   ./launch.sh <ticket> <label>                 — синхронно, вывод на экран + launch.log
#   ./launch.sh <ticket> <label> --background    — детач в фон, мгновенный возврат;
#                                                  наблюдение: ./launch.sh status <label>
#                                                  или tail -f /tmp/stanok-logs/<label>.launch.log
#   ./launch.sh <ticket> <label> --direct        — headless напрямую, без супервайзор-обёртки:
#                                                  путь тикета относительно РЕПО (stanok/), а не
#                                                  корня проекта; плюс жёсткая проверка ролевой
#                                                  изоляции (см. ROLE-LEAK ниже).
#   ./launch.sh status <label>                   — компактный JSON-статус прогона для поллинга
#                                                  (running/done/interrupted/missing + elapsed +
#                                                  последние события stdout). Не берёт lock —
#                                                  работает и во время идущего прогона.
#   ./launch.sh stop <label>                     — прервать идущий прогон (TERM по pid из
#                                                  .running): лаунчер убивается, summary НЕ
#                                                  создаётся; status после -> interrupted либо
#                                                  done rc!=0. Тот же принцип, что status: без
#                                                  lock/ROLE-LEAK.
#
# Локальные ретраи: лаунчер запускается с --local-retries ${STANOK_LOCAL_RETRIES:-1} —
# при FAIL модель получает в том же прогоне контекст упавшего теста и чинит точечно;
# только если не помогло — эскалация на уровень супервайзера. Облако НЕ зовётся (--no-cloud).
#
# Путь тикета нормализуется автоматически: сначала ищем относительно REPO, затем
# как передан (запуск из корня проекта: stanok/tickets/TASK-...md).
#
# Переносимость: REPO = директория этого скрипта. Внешние зависимости (venv, лаунчер,
# сервер) — константы вверху, переопределяются env.
set -u
set -o pipefail

# --- цвета (отключаются автоматически в не-TTY, ANSI оставляем как есть для launch.log) ---
C_RED=$'\033[31m'
C_GREEN=$'\033[32m'
C_YELLOW=$'\033[33m'
C_CYAN=$'\033[36m'
C_GRAY=$'\033[90m'
C_BOLD=$'\033[1m'
C_RESET=$'\033[0m'

# --- репо = директория этого скрипта (скелет переносимый) ---
DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="$DIR"

# ------------------------------------------------------------------------------
# Подкоманда status: компактный статус прогона для супервайзера.
#   ./launch.sh status <label>
# Dispatch — в САМОМ начале (до TICKET_ARG/LABEL/flags/нормализации/ROLE-LEAK),
# чтобы поллинг был дешёвым: никакого spawn python3 для ROLE-LEAK и обхода
# родительских каталогов при каждом вызове.
# Возвращает ОДНУ строку JSON: state = running|done|interrupted|missing,
# last_events (хвост launcher.stdout.log) + summary при done. Работает и во время
# прогона (НЕ берёт lock), чтобы поллинг не блокировался и не инжектил весь лог
# в контекст TUI.
# Статус — read-only stdlib-parse (json/os/sys/time), поэтому используем системный
# python3 (${STANOK_PY:-python3}), а НЕ venv: поллинг должен работать, даже если
# .venv ещё не развёрнут (setup.sh). ROLE-LEAK и так зависит от системного python3.
# ------------------------------------------------------------------------------
if [[ "${1:-}" == "status" ]]; then
    STATUS_LABEL="${2:?usage: launch.sh status <label>}"
    S_EVIDENCE="$REPO/evidence/$STATUS_LABEL"
    S_STDOUT="$S_EVIDENCE/launcher.stdout.log"
    S_MARKER="$S_EVIDENCE/.running"
    S_SUMMARY="$S_EVIDENCE/summary.json"
    "${STANOK_PY:-python3}" - "$S_EVIDENCE" "$S_STDOUT" "$S_MARKER" "$S_SUMMARY" "$STATUS_LABEL" <<'PYEOF'
import json, os, sys, time
evidence, stdout_log, marker, summary_path, label = sys.argv[1:6]
out = {"label": label}
if os.path.exists(marker):
    out["state"] = "running"
    try:
        start_s, pid = open(marker, encoding="utf-8").read().split()
        out["elapsed_s"] = int(time.time()) - int(start_s)
        out["pid"] = int(pid)
    except (ValueError, OSError):
        out["elapsed_s"] = None
elif os.path.exists(summary_path):
    try:
        with open(summary_path, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        s = {}
    out["state"] = "done"
    out["elapsed_s"] = s.get("elapsed_s")
    out["summary"] = {k: s.get(k) for k in
                      ("rc", "verifier", "probe_result", "review_verdict",
                       "cloud_calls", "c5", "errors")}
elif os.path.exists(stdout_log) and os.path.getsize(stdout_log) > 0:
    out["state"] = "interrupted"
    out["note"] = "нет summary.json — прогон прерван/убит (rc!=0 без вердикта)"
else:
    out["state"] = "missing"
    out["note"] = "нет evidence для этого label"
if os.path.exists(stdout_log):
    with open(stdout_log, encoding="utf-8", errors="replace") as f:
        lines = [ln.rstrip() for ln in f if ln.strip()]
    out["last_events"] = [ln[:160] for ln in lines[-5:]]
print(json.dumps(out, ensure_ascii=False))
PYEOF
    exit 0
fi

# ------------------------------------------------------------------------------
# Подкоманда stop: прервать запущенный прогон (TERM по pid из .running).
#   ./launch.sh stop <label>
# Тот же принцип, что status: в самом начале, без lock/ROLE-LEAK. TERM на процесс
# запуска (pid в .running) триггерит его trap cleanup EXIT INT TERM: лаунчер
# убивается, .running и SNAPSHOT чистятся. После stop status покажет interrupted
# (нет summary.json) либо done с rc!=0 — тикет НЕ помечается выполненным.
# ------------------------------------------------------------------------------
if [[ "${1:-}" == "stop" ]]; then
    STOP_LABEL="${2:?usage: launch.sh stop <label>}"
    S_MARKER="$REPO/evidence/$STOP_LABEL/.running"
    if [[ ! -f "$S_MARKER" ]]; then
        echo "STOP: прогон '$STOP_LABEL' не запущен (.running нет)" >&2
        exit 1
    fi
    read -r _start_s stop_pid < "$S_MARKER" || stop_pid=""
    if [[ -z "${stop_pid:-}" ]]; then
        echo "STOP: .running повреждён (нет pid) у '$STOP_LABEL'" >&2
        exit 1
    fi
    if kill -TERM "$stop_pid" 2>/dev/null; then
        echo "STOP: TERM отправлен pid $stop_pid ($STOP_LABEL) — прогон прерывается"
        echo "      после остановки: ./launch.sh status $STOP_LABEL -> interrupted или done rc!=0"
    else
        echo "STOP: процесс $stop_pid уже не запущен — убираю stale .running" >&2
        rm -f "$S_MARKER"
    fi
    exit 0
fi

TICKET_ARG="${1:?usage: launch.sh <ticket.md> <evidence-label> [--background|--direct]}"
LABEL="${2:?usage: launch.sh <ticket.md> <evidence-label> [--background|--direct]}"

# --- защита от типичной ошибки: launch.sh <ticket> --background (забыт label). ---
# LABEL подхватил бы флаг -> evidence/--background. Ловим явно.
if [[ "$LABEL" == --* ]]; then
    echo "${C_RED}${C_BOLD}ERROR: label не может начинаться с '--' — забыт позиционный аргумент <evidence-label>?${C_RESET}" >&2
    echo "${C_RED}  usage: launch.sh <ticket.md> <evidence-label> [--background|--direct]${C_RESET}" >&2
    exit 15
fi

# --- флаги режима (допустимы в любой позиции argv) ---
#   --background — детач в фон (через --core).
#   --direct     — headless напрямую, без супервайзор-обёртки: путь тикета
#                  относительно репо + жёсткая проверка ролевой изоляции.
BACKGROUND=0
CORE=0
DIRECT=0
for _a in "$@"; do
    [[ "$_a" == "--background" ]] && BACKGROUND=1
    [[ "$_a" == "--core" ]] && CORE=1
    [[ "$_a" == "--direct" ]] && DIRECT=1
done

# --- нормализация пути тикета: сначала относительно репо (--direct/изнутри),
#     затем как передан (запуск из корня проекта: stanok/tickets/...). ---
if [[ -f "$REPO/$TICKET_ARG" ]]; then
    TICKET="$REPO/$TICKET_ARG"
else
    TICKET="$TICKET_ARG"
fi

# --- fail-closed: python3 обязателен для ROLE-LEAK (иначе проверка молча отключается). ---
# Нет set -e: провал $(python3 ...) даёт ПУСТУЮ LEAK и [[ -n "$LEAK" ]] ложно — скрипт
# продолжает с отключённым ROLE-LEAK (fail-open), что хуже падения. Явная проверка —
# отказ (стандарт fail-closed, как test-lock / malware-scan).
if ! command -v python3 >/dev/null 2>&1; then
    echo "${C_RED}${C_BOLD}ERROR: python3 не найден — ROLE-LEAK проверка невозможна, отказ (fail-closed)${C_RESET}" >&2
    exit 25
fi

# --- Ролевая изоляция станка: выше репо не должно быть CLAUDE.md. ---
# Claude Code автозагружает CLAUDE.md из cwd И родительских каталогов. Если выше
# репо лежит CLAUDE.md с ролью «супервайзер L1», станок получает конфликт ролей
# и ведёт себя как супервайзор (darkcast: сессии ed9a2c06, 9f469cb9). Роль
# контроль-рума задаётся ЯВНО (--append-system-prompt-file), а не файлом
# с волшебным именем CLAUDE.md. Проверка — инвариант в обоих режимах.
LEAK="$(python3 - "$REPO" <<'PYEOF'
import os, sys
root = os.path.abspath(sys.argv[1])
d = os.path.dirname(root)
while d != os.path.dirname(d):
    if os.path.isfile(os.path.join(d, 'CLAUDE.md')):
        print(os.path.join(d, 'CLAUDE.md'))
        break
    d = os.path.dirname(d)
PYEOF
)"
if [[ -n "$LEAK" ]]; then
    echo "${C_RED}${C_BOLD}ROLE-LEAK: найден родительский CLAUDE.md: $LEAK${C_RESET}" >&2
    echo "${C_RED}  Claude Code автозагрузит его в станок -> станок подумает, что он супервайзор.${C_RESET}" >&2
    echo "${C_RED}  Переименуй/удали файл (роль контроль-рума задаётся через --append-system-prompt-file).${C_RESET}" >&2
    exit 24
fi

# --- внешние инструменты (self-contained: дефолты внутри репо, переопределяются env) ---
PY="${STANOK_PY:-$REPO/.venv/bin/python}"
LAUNCHER="${STANOK_LAUNCHER:-$REPO/launcher/stanok-sdk-probe.py}"
SERVER_URL="${STANOK_SERVER_URL:-http://192.168.8.131:8080}"
# Две evidence-зоны (fix A + A+; расследование — в корне проекта, зона супервайзера):
#  - EVIDENCE (в репо): только финальные артефакты, которые читает L1 —
#    summary.json и launcher.stdout.log (thinking модели там нет).
#  - LIVE_DIR (вне репо): всё, что пишется ЖИВО во время прогона —
#    probe-*.jsonl (содержит живой thinking модели!), probe-*.control.log,
#    симлинк evidence.jsonl, malware-scan/. Если они лежат в репо, модель
#    находит их через Glob и читает свой же транскрипт (self-reference loop).
EVIDENCE="$REPO/evidence/$LABEL"
LOG_DIR="${STANOK_LOG_DIR:-/tmp/stanok-logs}"
LIVE_DIR="$LOG_DIR/$LABEL"
LOG_LINK="$LIVE_DIR/evidence.jsonl"
STDOUT_LOG="$EVIDENCE/launcher.stdout.log"
LAUNCH_LOG="$LOG_DIR/$LABEL.launch.log"
LIVE="$DIR/live.py"

# --- нативный транскрипт bundled claude (источник реальной активности) ---
REPO_SLUG="$(printf '%s' "$REPO" | sed 's#^/##; s#/#-#g')"
NATIVE_DIR="$HOME/.claude/projects/-$REPO_SLUG"

# --- lock: ОДИН прогон на репо (flock, неблокирующий). ---
# Защита от параллельных запусков, которые топчут общий repo
# (каждый launch.sh делает git reset --hard + git clean -fdq).
LOCK_FILE="/tmp/stanok-launch-$(printf '%s' "$REPO" | md5sum | cut -c1-12).lock"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "${C_RED}${C_BOLD}LOCK: уже идёт прогон для репо $REPO (lock $LOCK_FILE) — отказ в запуске. Дождись завершения или убей его.${C_RESET}" >&2
    exit 21
fi

mkdir -p "$EVIDENCE" "$LIVE_DIR"

# ------------------------------------------------------------------------------
# Проверки окружения
# ------------------------------------------------------------------------------
if [[ ! -x "$PY" ]]; then
    echo "${C_RED}ERROR: Python env not found/executable: $PY${C_RESET}" >&2
    exit 10
fi
if [[ ! -f "$LAUNCHER" ]]; then
    echo "${C_RED}ERROR: launcher not found: $LAUNCHER${C_RESET}" >&2
    exit 11
fi
if [[ ! -d "$REPO/.git" ]]; then
    echo "${C_RED}ERROR: git repo not found: $REPO${C_RESET}" >&2
    exit 12
fi
if [[ ! -f "$TICKET" ]]; then
    echo "${C_RED}ERROR: ticket not found: $TICKET${C_RESET}" >&2
    exit 13
fi

# ------------------------------------------------------------------------------
# Pre-flight: жив ли локальный сервер?
# ------------------------------------------------------------------------------
PROPS=""
if [[ -n "${STANOK_SKIP_SERVER_CHECK:-}" ]]; then
    echo "${C_YELLOW}⚠ pre-flight сервера пропущен (STANOK_SKIP_SERVER_CHECK=1)${C_RESET}"
else
    PROPS="$(curl -s --noproxy '*' --max-time 5 "$SERVER_URL/props" 2>/dev/null || true)"
fi

if [[ -n "$PROPS" ]]; then
    MODEL="$(printf '%s' "$PROPS" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("model_alias","?"))' 2>/dev/null || echo "?")"
    CTX="$(printf '%s' "$PROPS" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("default_generation_settings",{}).get("n_ctx","?"))' 2>/dev/null || echo "?")"
    SLOTS="$(printf '%s' "$PROPS" | "$PY" -c 'import json,sys; d=json.load(sys.stdin); print(d.get("total_slots","?"))' 2>/dev/null || echo "?")"
    # баннер печатаем внутри stanok_run, чтобы он попадал и в launch.log (tail -f)
else
    echo "${C_RED}${C_BOLD}СЕРВЕР НЕДОСТУПЕН${C_RESET}  ${C_GRAY}($SERVER_URL/props не ответил за 5s)${C_RESET}" >&2
    echo "${C_RED}  Станок НЕ запущен. Подними llama-server, затем повтори.${C_RESET}" >&2
    echo "${C_RED}  (быстрый отказ вместо долгой тишины — это и есть pre-flight)${C_RESET}" >&2
    exit 20
fi

# ------------------------------------------------------------------------------
# Режим --background: детач всего прогона в фон (stdout -> launch.log)
# ------------------------------------------------------------------------------
if [[ "$BACKGROUND" == "1" && "$CORE" == "0" ]]; then
    echo "--- режим --background: станок стартует в фоне ---"
    echo "    наблюдение: tail -f $LAUNCH_LOG   (или второй терминал)"
    echo "    лог:        $LAUNCH_LOG"
    echo "    evidence:   $EVIDENCE"
    setsid nohup "$0" "$TICKET" "$LABEL" --core > "$LAUNCH_LOG" 2>&1 < /dev/null &
    exit 0
fi

# ------------------------------------------------------------------------------
# Итоговый summary-блок
# ------------------------------------------------------------------------------
print_summary() {
    local rc="$1" elapsed="$2" mm ss
    mm=$(( elapsed / 60 )); ss=$(( elapsed % 60 ))
    echo ""
    echo "${C_BOLD}━━━ СВОДКА ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"
    echo "rc=$rc · elapsed ${mm}m ${ss}s · ticket $TICKET"
    if [[ -f "$STDOUT_LOG" ]]; then
        grep -E "VERIFIER:|PROBE-RESULT:|REVIEW-VERDICT:|C5:|doctor:" "$STDOUT_LOG" 2>/dev/null \
            | sed 's/^/  /' || true
        grep -E "!!!|EXCEPTION|Traceback|СЕССИЯ ЗАВЕРШИЛАСЬ|API Error|HEADLESS-STOP" "$STDOUT_LOG" 2>/dev/null \
            | head -5 | sed 's/^/  ERR: /' || true
    fi
    echo "  live (probe):   $LIVE_DIR"
    echo "  launch.log:     $LAUNCH_LOG"
    echo "${C_BOLD}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${C_RESET}"

    # --- машинный summary для координатора: summary.json (один Read = весь итог) ---
    "$PY" - "$STDOUT_LOG" "$EVIDENCE/summary.json" "$rc" "$elapsed" "$TICKET" "$LABEL" <<'PYEOF'
import json, re, sys
stdout_log, out, rc, elapsed, ticket, label = sys.argv[1:7]
try:
    with open(stdout_log, encoding="utf-8", errors="replace") as f:
        text = f.read()
except OSError:
    text = ""
def first(pat):
    m = re.search(pat, text)
    return m.group(1).strip() if m else None
summary = {
    "label": label,
    "ticket": ticket,
    "rc": int(rc),
    "elapsed_s": int(elapsed),
    "verifier": first(r"VERIFIER: (PASS|FAIL)"),
    "probe_result": first(r"PROBE-RESULT: ([A-Z-]+)"),
    "cloud_calls": first(r"cloud_calls=(\d+)"),
    "review_verdict": first(r"REVIEW-VERDICT: (\w+)"),
    "c5": "PASS" if re.search(r"C5: PASS", text) else ("FAIL" if re.search(r"C5: FAIL", text) else None),
    "errors": [l.strip() for l in text.splitlines()
               if re.search(r"!!!|EXCEPTION|Traceback|СЕССИЯ ЗАВЕРШИЛАСЬ|API Error|HEADLESS-STOP", l)][:5],
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(summary, f, ensure_ascii=False, indent=2)
PYEOF
}

# ------------------------------------------------------------------------------
# Функция: весь прогон (лаунчер + живой форматер + summary)
# ------------------------------------------------------------------------------
stanok_run() {
    START_TS="$(date +%s)"
    # маркер живучести: пока существует — прогон идёт (читает подкоманда status)
    printf '%s %s\n' "$START_TS" "$$" > "$EVIDENCE/.running"
    SNAPSHOT="/tmp/stanok-launch-${LABEL//[^A-Za-z0-9_.-]/_}-$$.before"
    LAUNCH_PID=""

    # --- зелёный баннер pre-flight (из переменных, заполненных до вызова) ---
    echo "${C_GREEN}СЕРВЕР OK${C_RESET}  ${C_BOLD}${MODEL}${C_RESET} · n_ctx ${CTX} · слотов ${SLOTS} @ ${SERVER_URL}"
    if [[ "$DIRECT" == "1" ]]; then
        echo "${C_CYAN}--direct: headless-запуск напрямую, без супервайзор-обёртки${C_RESET}"
    fi

    # --- reset репо ---
    echo "--- reset репо до чистого состояния ---"
    (
        cd "$REPO" || exit 9

        git reset --hard HEAD >/dev/null 2>&1
        git clean -fdq >/dev/null 2>&1

        mkdir -p src tests docs
        rm -rf .stanok-locks

        echo "reset ok"
    ) || {
        echo "${C_RED}ERROR: reset репо failed${C_RESET}" >&2
        return 14
    }

    # Убираем старый симлинк evidence.jsonl
    if [[ -L "$LOG_LINK" || -f "$LOG_LINK" ]]; then
        rm -f "$LOG_LINK"
    fi

    echo "--- запуск лаунчера: $TICKET -> evidence $EVIDENCE ---"

    # Запоминаем существующие probe-файлы ДО запуска (live-артефакты в LIVE_DIR)
    find "$LIVE_DIR" \
        -maxdepth 1 \
        -type f \
        -name 'probe-*.jsonl' \
        -printf '%f\n' \
        2>/dev/null \
        | sort > "$SNAPSHOT"

    # Запуск stanok-sdk-probe.py в фоне
    # локальные ретраи main (STANOK_LOCAL_RETRIES, default 1): при FAIL модель получает
    # в том же прогоне контекст упавшего теста и чинит точечно; только если не помогло —
    # эскалация на уровень супервайзера (полный рестарт тикета с новым label).
    # Облако НЕ зовётся никогда (--no-cloud, инвариант).
    env \
        PYTHONUNBUFFERED=1 \
        STANOK_REPO="$REPO" \
        STANOK_EVIDENCE="$LIVE_DIR" \
        "$PY" -u "$LAUNCHER" \
        "$(cat "$TICKET")" \
        --no-cloud \
        --local-retries "${STANOK_LOCAL_RETRIES:-1}" > "$STDOUT_LOG" 2>&1 &
    LAUNCH_PID=$!

    cleanup() {
        kill -TERM "$LAUNCH_PID" 2>/dev/null || true
        wait "$LAUNCH_PID" 2>/dev/null || true
        rm -f "$SNAPSHOT" 2>/dev/null || true
        rm -f "$EVIDENCE/.running" 2>/dev/null || true
    }
    trap cleanup EXIT INT TERM

    # --------------------------------------------------------------------------
    # Live Formatter в foreground: probe-события + хвост stdout лаунчера
    # --------------------------------------------------------------------------
    "$PY" -u "$LIVE" "$LIVE_DIR" "$LOG_LINK" "$SNAPSHOT" "$LAUNCH_PID" "$STDOUT_LOG" "$NATIVE_DIR"

    # --------------------------------------------------------------------------
    # Завершение
    # --------------------------------------------------------------------------
    wait "$LAUNCH_PID" 2>/dev/null
    rc=$?

    print_summary "$rc" "$(( $(date +%s) - START_TS ))"

    rm -f "$SNAPSHOT" 2>/dev/null || true
    rm -f "$EVIDENCE/.running" 2>/dev/null || true
    trap - EXIT INT TERM
    return "$rc"
}

# ------------------------------------------------------------------------------
# Точка входа
# ------------------------------------------------------------------------------
if [[ "$CORE" == "1" ]]; then
    # detached-процесс: stdout уже перенаправлен в launch.log родителем
    stanok_run
    rc=$?
    exit "$rc"
fi

# foreground: вывод на экран + дубликат в launch.log
stanok_run | tee "$LAUNCH_LOG"
rc=$?
exit "$rc"


