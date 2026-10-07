#!/usr/bin/env python3
"""PreToolUse (all tools) loop guard. exit 2 = deny, stderr идёт модели как причина.

Считает только ПОДРЯД идущие повторения одного и того же вызова: любой
другой tool call сбрасывает счётчик. TDD-цикл (run.sh test -> Edit ->
run.sh test) не триггерит; 5 идентичных вызовов подряд — deny на 5-м.

CC-207 (инцидент CC-204-retry3: 31 идентичный Read, текст отказа вошёл в
контекст как ещё одна строка и петлю не разорвал): отказ — это СИГНАЛ
ЗАВЕРШЕНИЯ. На 5-м подряд identical-вызове хук пишет JSON-маркер
{"tool","hash","n","ts"} в STANOK_LOOP_TRAP_FILE (env не задан — маркера
нет: вне stanok-сессии хук остаётся чистой предупреждающей заглушкой).
Лончер читает маркер и завершает run с probe_result "LOOP-TRAP".
Fail-open: любой сбой = exit 0; сбой записи маркера никогда не блокирует
отказ.

Копия машинной сессии (cwd=stanok/). Копия supervisor-сессии
(darkcast/.claude/hooks/loop-guard.py) намеренно НЕ синхронизируется
(решение оператора 2026-10-08): supervisor-гард остаётся предупреждающим
порога 10."""
import sys, json, hashlib, os
from datetime import datetime

THRESHOLD = 5

try:
    d = json.load(sys.stdin)
    name = d.get("tool_name") or ""
    inp = d.get("tool_input") or {}
    sid = d.get("session_id") or "nosession"
    if name == "Bash":
        payload = inp.get("command") or ""
        if not payload:
            sys.exit(0)
    else:
        payload = json.dumps(inp, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256((name + "\0" + payload).encode()).hexdigest()
except Exception:
    sys.exit(0)

p = f"/tmp/claude-loop-guard/{sid}.state"
last, n = None, 0
try:
    with open(p) as f:
        st = json.load(f)
        last = st.get("last")
        n = int(st.get("n", 0))
except (FileNotFoundError, OSError, ValueError, TypeError):
    pass

if h == last:
    n += 1
else:
    last, n = h, 1

try:
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w") as f:
        json.dump({"last": last, "n": n}, f)
except OSError:
    pass

if n >= THRESHOLD:
    marker = os.environ.get("STANOK_LOOP_TRAP_FILE")
    if marker:
        try:
            dname = os.path.dirname(marker)
            if dname:
                os.makedirs(dname, exist_ok=True)
            with open(marker, "w") as f:
                json.dump({"tool": name, "hash": h, "n": n,
                           "ts": datetime.now().isoformat(timespec="seconds")}, f)
        except Exception:
            pass  # fail-open: отказ важнее маркера
    sys.stderr.write(
        f"Этот вызов ({name}) повторяется {n} раз подряд без любого другого "
        "действия между вызовами. Сессия завершается circuit breaker'ом: "
        "петля прервана, повторять этот вызов больше не будет.\n")
    sys.exit(2)
sys.exit(0)
