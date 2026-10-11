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

CC-234 (инцидент cc231/cc233): путь состояния больше не hardcoded /tmp —
он строится из TMPDIR (Pod редиректит TMPDIR во writable emptyDir; под
readOnlyRootFilesystem старый путь не писался никогда, счётчик молчал,
breaker был мёртв 5 прогонов). Fail-closed на сбой записи состояния:
гард, не способный сохранить состояние, мёртв — deny громко, а не
молчаливый pass. Сбой разбора stdin и сбой записи маркера остаются
fail-open (exit 0): отказ важнее маркера.

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

# CC-234: TMPDIR-based (the Pod's writable emptyDir; /tmp is read-only
# there). Unset TMPDIR (host/Docker) -> /tmp as before.
p = os.path.join(os.environ.get("TMPDIR") or "/tmp",
                 "claude-loop-guard", f"{sid}.state")
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
except OSError as e:
    # CC-234 fail-closed: состояние не записано -> гард не может считать
    # повторы -> deny громко (молчаливый pass и убил breaker в Pod).
    sys.stderr.write(
        f"loop-guard: состояние не записано ({e}) — circuit breaker не "
        "может работать; вызов запрещён. Проверьте доступность TMPDIR.\n")
    sys.exit(2)

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
