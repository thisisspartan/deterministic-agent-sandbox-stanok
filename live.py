#!/usr/bin/env python3
# Live-форматер для launch.sh (stanok-cc, tui/control-room).
#
# Источник РЕАЛЬНОЙ активности — НАТИВНЫЙ session-транскрипт bundled claude:
#   $HOME/.claude/projects/-<cwd-путь-через-дефисы>/<session-id>.jsonl
# Его пишет сам claude (тот же механизм, что в интерактивном режиме) — без каких-либо
# правок в станок-пробе / SDK-скрипте. В транскрипте лежат реальные события:
#   assistant -> thinking / text / tool_use (с полными аргументами)
#   user      -> tool_result (с полным выводом)
#
# Дополнительно:
#   - хвост launcher.stdout.log  -> баннер, doctor, VERIFIER/PROBE-RESULT, ошибки
#   - probe-evidence.jsonl       -> только error-события (остальное там — null-шум),
#                                   плюс симлинк evidence.jsonl на свежий probe-файл
#
# Хардбит печатается ТОЛЬКО при тишине (>= HEARTBEAT_GAP сек): пока события идут,
# экран живёт самим стримом. Idle-watchdog (>90s) — как раньше.
#
# argv: EVIDENCE LOG_LINK SNAPSHOT LAUNCHER_PID STDOUT_LOG NATIVE_DIR
import glob
import json
import os
import re
import signal
import sys
import time

EVIDENCE, LOG_LINK, SNAPSHOT, LAUNCHER_PID, STDOUT_LOG, NATIVE_DIR = sys.argv[1:7]
LAUNCHER_PID = int(LAUNCHER_PID)

GREEN = "\033[32m"
GRAY = "\033[90m"
WHITE = "\033[37m"
RED = "\033[31m"
BOLD = "\033[1m"
UNDERLINE = "\033[4m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
RESET = "\033[0m"
RED_BOLD = RED + BOLD

HEARTBEAT_SECS = 30.0      # повтор хардбита
HEARTBEAT_GAP = 45.0       # хардбит только если тишина >= 45s
IDLE_WARN_SECS = 90.0      # idle-watchdog
IDLE_WARN_REPEAT = 30.0

SESSION_RE = re.compile(
    r"сессия\s+([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})"
)

STOP = False
START = time.time()
RENDERED = 0
TOOL_NAMES = {}


def on_signal(signum, frame):
    global STOP
    STOP = True


signal.signal(signal.SIGINT, on_signal)
signal.signal(signal.SIGTERM, on_signal)


def emit(text, activity=True):
    """Печать в стрим. activity=True -> считается реальным контентом (сбрасывает тишину)."""
    global RENDERED
    print(text, flush=True)
    if activity:
        RENDERED += 1


def launcher_alive():
    try:
        os.kill(LAUNCHER_PID, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def short(value, limit=120):
    if value is None:
        return ""
    if isinstance(value, str):
        value = value.strip()
    else:
        try:
            value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            value = str(value)
    value = " ".join(str(value).split())
    if len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def elapsed():
    mm, ss = divmod(int(time.time() - START), 60)
    return f"[{mm:02d}:{ss:02d}]"


def normalize_block_type(block):
    raw = str(block.get("type", "")).lower()
    mapping = {
        "text": "text", "textblock": "text",
        "thinking": "thinking", "thinkingblock": "thinking",
        "tool_use": "tool_use", "tooluseblock": "tool_use",
        "tool_result": "tool_result", "toolresultblock": "tool_result",
    }
    return mapping.get(raw, raw)


# ----------------------------------------------------------------------------
# Рендер нативного транскрипта
# ----------------------------------------------------------------------------

def tool_argument(name, value):
    if not isinstance(value, dict):
        return short(value, 100)
    if name == "Bash":
        return short(value.get("command") or value.get("cmd") or value, 100)
    for key in ("file_path", "path", "command", "pattern", "query", "url"):
        if key in value:
            return short(value[key], 100)
    try:
        return short(json.dumps(value, ensure_ascii=False, separators=(",", ":")), 100)
    except Exception:
        return short(value, 100)


def render_thinking(block):
    text = block.get("thinking") or block.get("text") or ""
    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
    if not lines:
        return False
    emit(f"{GRAY}◆ {short(lines[0], 120)}{RESET}")
    return True


def render_text(text):
    if not text:
        return False
    lines = [l.strip() for l in str(text).splitlines() if l.strip()]
    printed = False
    for line in lines:
        if line.startswith("<") and line.endswith(">"):
            continue
        emit(f"{WHITE}● {short(line, 130)}{RESET}")
        printed = True
    return printed


def render_tool_use(block):
    name = block.get("name") or "Tool"
    tid = block.get("id")
    if tid:
        TOOL_NAMES[tid] = name
    inp = block.get("input") or {}
    arg = tool_argument(name, inp)
    emit(f"{GREEN}▶ {elapsed()} {BOLD}{name}{RESET}({UNDERLINE}{arg}{RESET})")
    return True


def render_tool_result(block):
    content = block.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
            elif item is not None:
                parts.append(str(item))
        content = "\n".join(parts)
    if content is None:
        content = ""
    lines = [l.strip() for l in str(content).splitlines() if l.strip()]
    if not lines:
        return False
    tid = block.get("tool_use_id") or block.get("id")
    label = (TOOL_NAMES.get(tid) + ": ") if (tid and tid in TOOL_NAMES) else ""
    color = RED_BOLD if block.get("is_error") else GRAY
    prefix = f"└ {label}"
    emit(f"  {color}{prefix}{short(lines[0], 120)}{RESET}", activity=True)
    for extra in lines[1:3]:
        emit(f"  {color}{prefix}{short(extra, 110)}{RESET}", activity=False)
    if len(lines) > 3:
        emit(f"  {color}{prefix}... ещё {len(lines) - 3} строк{RESET}", activity=False)
    return True


def render_native(event):
    """Рендер строки нативного транскрипта. True если напечатал контент."""
    if not isinstance(event, dict):
        return False
    t = event.get("type")
    message = event.get("message")
    if not isinstance(message, dict):
        return False
    content = message.get("content")
    if not isinstance(content, list):
        return False
    printed = False
    for block in content:
        if not isinstance(block, dict):
            continue
        bt = normalize_block_type(block)
        if t == "assistant":
            if bt == "thinking":
                printed |= render_thinking(block)
            elif bt == "text":
                printed |= render_text(block.get("text", ""))
            elif bt == "tool_use":
                printed |= render_tool_use(block)
        elif t == "user" and bt == "tool_result":
            printed |= render_tool_result(block)
    return printed


# ----------------------------------------------------------------------------
# probe-evidence.jsonl: только error-события (симлинк делает launch.sh)
# ----------------------------------------------------------------------------

def render_probe_event(event):
    if not isinstance(event, dict):
        return False
    if event.get("type") == "error":
        err = event.get("error") or event.get("message") or event
        emit(f"{RED_BOLD}└ ERROR: {short(err, 120)}{RESET}")
        return True
    return False


def load_snapshot():
    try:
        with open(SNAPSHOT, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except OSError:
        return set()


BEFORE = load_snapshot()


def find_new_probe(processed_set):
    candidates = []
    try:
        names = os.listdir(EVIDENCE)
    except OSError:
        return None
    for name in names:
        if not name.startswith("probe-") or not name.endswith(".jsonl"):
            continue
        if name in BEFORE or name in processed_set:
            continue
        path = os.path.join(EVIDENCE, name)
        try:
            if not os.path.isfile(path):
                continue
            candidates.append((os.path.getmtime(path), path))
        except OSError:
            continue
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def link_evidence(probe_path):
    target = os.path.basename(probe_path)
    tmp_link = f"{LOG_LINK}.tmp-{os.getpid()}"
    try:
        try:
            os.unlink(tmp_link)
        except FileNotFoundError:
            pass
        os.symlink(target, tmp_link)
        os.replace(tmp_link, LOG_LINK)
        return True
    except OSError:
        try:
            os.unlink(tmp_link)
        except OSError:
            pass
        return False


# ----------------------------------------------------------------------------
# launcher.stdout.log
# ----------------------------------------------------------------------------

ERROR_HINTS = ("!!!", "EXCEPTION", "Traceback", "СЕССИЯ ЗАВЕРШИЛАСЬ", "ОШИБКА",
               "API Error", "ERROR", "FAIL")
VERDICT_HINTS = ("VERIFIER:", "PROBE-RESULT:", "REVIEW-VERDICT:", "C5:", "doctor:")


def render_stdout(line):
    line = line.strip()
    if not line:
        return
    if any(h in line for h in ERROR_HINTS):
        emit(f"{RED_BOLD}└ {line}{RESET}", activity=False)
    elif any(line.startswith(h) for h in VERDICT_HINTS):
        ok = any(k in line for k in ("PASS", "rc=0", "CLEAN", "ok", "OK"))
        color = GREEN if ok else RED
        emit(f"{BOLD}{color}└ {line}{RESET}", activity=False)
    elif line.startswith("STANOK"):
        emit(f"{BOLD}{WHITE}└ {line}{RESET}", activity=False)
    else:
        emit(f"{GRAY}└ {line}{RESET}", activity=False)


def iter_new_lines(f):
    while True:
        line = f.readline()
        if not line:
            return
        line = line.strip()
        if line:
            yield line


# ----------------------------------------------------------------------------
# Нативный транскрипт: поиск по session id из stdout лаунчера
# ----------------------------------------------------------------------------

SESSION = [None]
native_f = [None]


def try_open_native():
    if native_f[0] is not None or not SESSION[0]:
        return
    path = os.path.join(NATIVE_DIR, SESSION[0] + ".jsonl")
    if not os.path.isfile(path):
        hits = glob.glob(os.path.join(os.path.dirname(NATIVE_DIR), "*", SESSION[0] + ".jsonl"))
        path = hits[0] if hits else None
    if path and os.path.isfile(path):
        try:
            native_f[0] = open(path, "r", encoding="utf-8", errors="replace")
            emit(f"{GREEN}└ live: транскрипт {os.path.basename(path)}{RESET}", activity=False)
        except OSError:
            native_f[0] = None


def drain(f, is_stdout, is_native):
    if not f:
        return
    try:
        for line in iter_new_lines(f):
            try:
                if is_stdout:
                    if SESSION[0] is None:
                        m = SESSION_RE.search(line)
                        if m:
                            SESSION[0] = m.group(1)
                    render_stdout(line)
                else:
                    event = json.loads(line)
                    if is_native:
                        render_native(event)
                    else:
                        render_probe_event(event)
            except Exception:
                pass
    except OSError:
        pass


# ----------------------------------------------------------------------------
# Главный цикл
# ----------------------------------------------------------------------------

def main():
    global START
    START = time.time()

    processed = set()
    probe_path = None
    probe_f = None
    stdout_f = None

    last_activity = START
    last_heartbeat = START
    last_idle_warn = 0.0
    last_rendered = 0

    while not STOP:
        # 1) нативный транскрипт claude — реальная активность
        try_open_native()
        if native_f[0]:
            drain(native_f[0], is_stdout=False, is_native=True)

        # 2) хвост stdout лаунчера (+ ловим session id)
        if stdout_f is None:
            try:
                stdout_f = open(STDOUT_LOG, "r", encoding="utf-8", errors="replace")
            except OSError:
                stdout_f = None
        if stdout_f:
            drain(stdout_f, is_stdout=True, is_native=False)

        # 3) probe-evidence: симлинк + только error
        new_probe = find_new_probe(processed)
        if new_probe and new_probe != probe_path:
            if probe_f:
                probe_f.close()
            probe_path = new_probe
            processed.add(os.path.basename(probe_path))
            link_evidence(probe_path)
            try:
                probe_f = open(probe_path, "r", encoding="utf-8", errors="replace")
            except OSError:
                probe_f = None
        if probe_f:
            drain(probe_f, is_stdout=False, is_native=False)

        if not launcher_alive():
            drain(native_f[0], is_stdout=False, is_native=True)
            drain(stdout_f, is_stdout=True, is_native=False)
            drain(probe_f, is_stdout=False, is_native=False)
            break

        if RENDERED != last_rendered:
            last_activity = time.time()
            last_rendered = RENDERED

        now = time.time()
        # хардбит — только при тишине
        if now - last_activity >= HEARTBEAT_GAP and now - last_heartbeat >= HEARTBEAT_SECS:
            last_heartbeat = now
            emit(f"{GRAY}⏱ {elapsed()} · жив · тишина {int(now - last_activity)}s{RESET}",
                 activity=False)
        # idle-watchdog
        if now - last_activity >= IDLE_WARN_SECS and now - last_idle_warn >= IDLE_WARN_REPEAT:
            last_idle_warn = now
            emit(f"{RED_BOLD}⚠ ТИШИНА {int(now - last_activity)}s {elapsed()}{RESET}",
                 activity=False)
            emit(f"{YELLOW}  Вероятно модель думает или зависла. "
                 f"Проверь: curl -s http://192.168.8.131:8080/props. Ctrl-C — прервать прогон.{RESET}",
                 activity=False)

        time.sleep(0.05)

    for f in (native_f[0], stdout_f, probe_f):
        if f:
            try:
                f.close()
            except Exception:
                pass
    return 0


raise SystemExit(main())
