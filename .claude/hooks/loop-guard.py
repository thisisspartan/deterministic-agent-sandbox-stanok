#!/usr/bin/env python3
"""PreToolUse (all tools) loop guard. exit 2 = deny, stderr идёт модели как причина.

Считает только ПОДРЯД идущие повторения одного и того же вызова: любой
другой tool call сбрасывает счётчик. TDD-цикл (run.sh test -> Edit ->
run.sh test) не триггерит; 10 идентичных вызовов подряд — deny на 10-м.
Fail-open: любой сбой = exit 0 (хук никогда не блокирует и не вешает turn)."""
import sys, json, hashlib, os

THRESHOLD = 10

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
    sys.stderr.write(
        f"Этот вызов ({name}) повторяется {n} раз подряд без любого другого "
        "действия между вызовами. Не повторяй — действуй по уже полученному "
        "результату или явно смени подход.\n")
    sys.exit(2)
sys.exit(0)
