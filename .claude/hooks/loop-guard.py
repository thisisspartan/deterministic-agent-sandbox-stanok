#!/usr/bin/env python3
"""PreToolUse(Bash) loop guard. exit 2 = deny, stderr идёт модели как причина.
Fail-open: любой сбой = exit 0 (хук никогда не блокирует и не вешает turn)."""
import sys, json, hashlib, os

try:
    d = json.load(sys.stdin)
    cmd = (d.get("tool_input") or {}).get("command") or ""
    sid = d.get("session_id") or "nosession"
except Exception:
    sys.exit(0)
if not cmd:
    sys.exit(0)

h = hashlib.sha256(cmd.encode()).hexdigest()
p = f"/tmp/claude-loop-guard/{sid}.log"
os.makedirs(os.path.dirname(p), exist_ok=True)
try:
    with open(p) as f:
        n = sum(1 for line in f if line.strip() == h)
except (FileNotFoundError, OSError):
    n = 0

# Порог 10: deny на 10-м буквальном повторе (9 предыдущих уже были).
if n >= 9:
    sys.stderr.write(
        f"Эта команда уже выполнялась {n + 1} раз в этой сессии без смены "
        "подхода. Не повторяй — действуй по уже полученному результату или "
        "явно смени подход.\n")
    sys.exit(2)

with open(p, "a") as f:
    f.write(h + "\n")
sys.exit(0)
