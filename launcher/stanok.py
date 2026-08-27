#!/usr/bin/env python3
"""Stanok — ЕДИНЫЙ Runner станка на локальной модели.

Заменяет тройку (launch.sh-оркестратор + stanok-sdk-probe.py + live.py) одним
Python-процессом: CLI (run/status/stop/watch), Job/Attempt модель, typed events
(events.jsonl), summary.json из типизированного состояния (без regex-парсинга),
дефолтный транспорт SDK (без _internal LoggingTransport).

CLI:
  stanok run <ticket> <label> [--direct] [--background]  — запуск тикета
  stanok status <label>                                   — JSON-статус для поллинга
  stanok stop <label>                                     — прервать прогон (TERM по pid)
  stanok watch <label>                                    — живой просмотр events.jsonl

Эксплуатационный контракт (для супервайзера; старые коды сохранены):
  rc=0 PASS / rc!=0 FAIL; label-guard rc=15; pre-flight rc=20; lock rc=21;
  ROLE-LEAK rc=24; doctor rc=1; python3 rc=25 больше НЕ нужен (Runner сам Python).
  Финальные артефакты: evidence/<label>/summary.json + launcher.stdout.log (в репо).
  Live-артефакты: /tmp/stanok-logs/<label>/probe-*.jsonl + events.jsonl (вне репо,
  чтобы модель не читала свой транскрипт через Glob — self-reference loop).
  Локальные ретраи main (STANOK_LOCAL_RETRIES, default 1): при FAIL модель получает
  контекст упавшего теста и чинит точечно; только если не помогло — эскалация на
  супервайзера. Облако НЕ зовётся (--no-cloud, инвариант).

Внешние зависимости (все переопределяются env):
  STANOK_SERVER_URL / STANOK_MODEL / STANOK_PROXY / STANOK_NO_PROXY
  STANOK_CLAUDE_BIN / STANOK_LOG_DIR / STANOK_CLOUD_CREDS / STANOK_CLOUD_MODEL
  STANOK_LOCAL_RETRIES / STANOK_PY
"""

import argparse
import asyncio
import dataclasses
import fcntl
import glob
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import uuid
from collections import Counter
from urllib.parse import urlparse

# claude_agent_sdk / telegram импортируются ЛЕНИВО (внутри функций, которым нужны):
# гейты (status/stop/pre-flight/ROLE-LEAK) — чистый stdlib и работают под системным
# python3 без .venv; SDK нужен только для самого main-прогона (run_main_session),
# telegram — только для DecisionProvider (tg_build).

# --- Константы контура (переносимы: дефолты выводятся из расположения файла) -----
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.environ.get("STANOK_REPO", os.path.dirname(LAUNCHER_DIR)))
LOG_DIR = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
CREDS = os.environ.get("STANOK_TG_CREDS", os.path.expanduser("~/.stanok/tg-creds"))

LOCAL_MODEL = os.environ.get("STANOK_MODEL", "Qwen3.8-27B-MTP")
SERVER_URL = os.environ.get("STANOK_SERVER_URL", "http://127.0.0.1:8080")
LOCAL_PROXY = os.environ.get("STANOK_PROXY", "http://127.0.0.1:8118")
NO_PROXY = os.environ.get("STANOK_NO_PROXY", "127.0.0.1,localhost")
TG_TIMEOUT = float(os.environ.get("STANOK_TG_TIMEOUT", "120"))

# --- Cloud-ревьюер (C2): внешний LLM, секрет только через envp --------------------
CLOUD_BASE_URL = os.environ.get("STANOK_CLOUD_BASE_URL", "https://api.deepseek.com/anthropic")
CLOUD_MODEL = os.environ.get("STANOK_CLOUD_MODEL", "deepseek-v4-flash")
CLOUD_CREDS = os.environ.get("STANOK_CLOUD_CREDS", os.path.expanduser("~/.cloud-creds"))
CLAUDE_BIN = os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude")
NPM_GLOBAL_BIN = os.environ.get("STANOK_NPM_BIN", os.path.dirname(CLAUDE_BIN))

ALLOWED_SUBAGENTS = {"reviewer", "tester"}

TG_TOKEN = os.environ.get("TG_TOKEN", "")
TG_ALLOWED_IDS = os.environ.get("TG_ALLOWED_IDS", "")
if not (TG_TOKEN and TG_ALLOWED_IDS) and os.path.exists(CREDS):
    for line in open(CREDS, encoding="utf-8"):
        line = line.strip()
        if line.startswith("TG_TOKEN="):
            TG_TOKEN = line.split("=", 1)[1]
        elif line.startswith("TG_ALLOWED_IDS="):
            TG_ALLOWED_IDS = line.split("=", 1)[1]

ALLOW_WORDS = {"allow", "да", "yes", "разрешить", "approve", "ok"}
DENY_WORDS = {"deny", "нет", "no", "запретить", "block"}

ALLOWED_WRITE_PREFIXES = ("src/", "tests/", "docs/")

# --- Текущие пути прогона (устанавливаются в run_job) -----------------------------
_stdout_log_f = None   # открытый launcher.stdout.log (в репо evidence/<label>)
_events_path = None    # live events.jsonl (вне репо)
_marker_path = None    # evidence/<label>/.running
_live_dir = None       # /tmp/stanok-logs/<label>
_evidence_dir = None   # repo/evidence/<label>


# ==================================================================================
# Вывод: лог в stdout (терминал/launch.log) + зеркало в launcher.stdout.log (репо)
# ==================================================================================
def log(msg: str = "") -> None:
    print(msg, flush=True)
    if _stdout_log_f is not None:
        try:
            _stdout_log_f.write(msg + "\n")
            _stdout_log_f.flush()
        except OSError:
            pass


def emit(etype: str, data: dict) -> None:
    """Typed event -> live events.jsonl (машиночитаемый след для watch/status)."""
    if _events_path is None:
        return
    try:
        with open(_events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), "type": etype, "data": data},
                               ensure_ascii=False) + "\n")
    except OSError:
        pass


# ==================================================================================
# Модель Job/Attempt (Фаза C)
# ==================================================================================
@dataclasses.dataclass
class Attempt:
    id: str                 # uuid попытки (== session_id SDK)
    started_at: float
    ended_at: float | None = None
    state: str = "running"  # running | passed | failed | error
    verify_ok: bool | None = None
    vfail: list = dataclasses.field(default_factory=list)
    exc: str = ""
    stream: str = ""        # путь probe-<sid>.jsonl (SDK event stream)
    result: str = ""


@dataclasses.dataclass
class Job:
    label: str
    ticket: str
    attempts: list = dataclasses.field(default_factory=list)
    state: str = "running"          # running | done | interrupted | error
    rc: int | None = None
    probe_result: str | None = None
    verifier: str | None = None     # PASS | FAIL (по последней попытке)
    c5: str | None = None           # PASS | FAIL
    cloud_calls: int = 0
    review_verdict: str | None = None
    errors: list = dataclasses.field(default_factory=list)
    started_at: float = dataclasses.field(default_factory=time.time)
    finished_at: float | None = None

    def last(self) -> Attempt | None:
        return self.attempts[-1] if self.attempts else None


def label_paths(label: str) -> tuple[str, str]:
    """(evidence_dir_репо, live_dir_/tmp)."""
    return (os.path.join(REPO_ROOT, "evidence", label),
            os.path.join(LOG_DIR, label))


# ==================================================================================
# Стартовые гейты (инварианты станка)
# ==================================================================================
def root_refusal() -> None:
    if os.geteuid() == 0:
        log("STANOK-CC ABORT: станок нельзя запускать от root")
        sys.exit(1)


def role_leak_check() -> None:
    """Ролевая изоляция: выше репо НЕ должно быть CLAUDE.md (иначе станок
    автозагрузит роль супервайзера). rc=24. Должен идти ДО lock/mkdir."""
    d = os.path.dirname(REPO_ROOT)
    while d != os.path.dirname(d):
        if os.path.isfile(os.path.join(d, "CLAUDE.md")):
            log(f"ROLE-LEAK: найден родительский CLAUDE.md: {os.path.join(d, 'CLAUDE.md')}")
            log("  Claude Code автозагрузит его в станок -> станок подумает, что он супервайзер.")
            log("  Переименуй/удали файл (роль контроль-рума задаётся через --append-system-prompt-file).")
            sys.exit(24)
        d = os.path.dirname(d)


def acquire_lock() -> None:
    """flock: ОДИН прогон на репо. rc=21, если lock занят."""
    lock_file = f"/tmp/stanok-{hashlib.md5(REPO_ROOT.encode()).hexdigest()[:12]}.lock"
    fd = open(lock_file, "w")
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        log(f"LOCK: уже идёт прогон для репо {REPO_ROOT} (lock {lock_file}) — отказ в запуске.")
        sys.exit(21)
    # держим fd открытым весь прогон (flock освобождается при exit)


def preflight_server() -> dict:
    """Живой ли llama-server? fail-fast rc=20 (без долгой тишины).

    Proxy-less opener: локальный сервер проверяем НАПРЯМУЮ (как `curl --noproxy '*'`),
    чтобы ambient http_proxy (8118) не маршрутизировал локальный /props через прокси."""
    if os.environ.get("STANOK_SKIP_SERVER_CHECK") == "1":
        log("pre-flight сервера пропущен (STANOK_SKIP_SERVER_CHECK=1)")
        return {}
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(urllib.request.Request(
                f"{SERVER_URL}/props", headers={"Accept": "application/json"}),
                timeout=5) as r:
            props = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as e:  # noqa: BLE001
        log(f"СЕРВЕР НЕДОСТУПЕН ({SERVER_URL}/props: {type(e).__name__})")
        log("  Станок НЕ запущен. Подними llama-server, затем повтори.")
        sys.exit(20)
    return props


def reset_repo() -> int:
    """git reset --hard + clean, mkdir src/tests/docs. rc=14 при провале."""
    try:
        subprocess.run(["git", "reset", "--hard", "HEAD"],
                       cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["git", "clean", "-fdq"],
                       cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        log(f"ERROR: reset репо failed: {e}")
        return 14
    for d in ("src", "tests", "docs"):
        os.makedirs(os.path.join(REPO_ROOT, d), exist_ok=True)
    locks = os.path.join(REPO_ROOT, ".stanok-locks")
    if os.path.isdir(locks):
        shutil.rmtree(locks, ignore_errors=True)
    return 0


def dirty_tree_gate() -> bool:
    """True = в репо есть незакоммиченные изменения -> старт запрещён (rc=22).

    reset_repo() делает `git reset --hard` + `git clean -fdq`: при грязном дереве
    это затёрло бы чужую/операторскую работу. Гейт fail-closed, проверяется ДО reset
    и ДО ветки --background (покрывает и родителя, и детaч-ребёнка). Не-git репо не
    блокируем — это ловит гейт rc=12, а сам reset упадёт rc=14.
    """
    try:
        out = subprocess.run(["git", "status", "--porcelain"],
                             cwd=REPO_ROOT, capture_output=True, text=True)
    except OSError:
        return False
    if out.returncode != 0:
        return False
    dirty = [ln for ln in out.stdout.splitlines() if ln.strip()]
    if not dirty:
        return False
    log("ERROR: репо НЕ в чистом состоянии — станок отказывается стартовать (rc=22)")
    log(f"  git reset --hard + git clean -fdq затёр бы незакоммиченные изменения в {REPO_ROOT}")
    log("  Закоммить (или stash) изменения, затем повтори запуск. Незакоммиченное:")
    for ln in dirty[:20]:
        log(f"    {ln}")
    if len(dirty) > 20:
        log(f"    ... и ещё {len(dirty) - 20} изменений")
    return True


def doctor_gate(expect_no_cloud: bool) -> None:
    env = dict(os.environ)
    if expect_no_cloud:
        env["DOCTOR_EXPECT_NO_CLOUD"] = "1"
    rc = subprocess.call(["bash", os.path.join(REPO_ROOT, "hooks", "doctor.sh")], env=env)
    if rc != 0:
        log(f"STANOK-CC ABORT: doctor.sh — инварианты станка не выполнены (rc={rc})")
        sys.exit(1)


# ==================================================================================
# Permission policy (can_use_tool) + Telegram как DecisionProvider
# ==================================================================================
CRITICAL_TOOLS = {"Bash", "WebFetch", "WebSearch", "NotebookEdit", "Skill",
                  "EnterWorktree", "ExitWorktree", "CronCreate", "CronDelete",
                  "CronList", "ScheduleWakeup", "Workflow", "SendMessage",
                  "ReportFindings", "Agent", "TaskCreate", "TaskUpdate",
                  "TaskGet", "TaskList", "TaskOutput", "TaskStop"}

ALLOWED_WEBFETCH_HOSTS = {
    "arxiv.org", "github.com",
    "docs.anthropic.com", "code.claude.com",
    "developer.mozilla.org", "nodejs.org", "docs.python.org",
    "npmjs.com", "pypi.org",
}


def classify_criticality(tool_name: str, tool_input: dict) -> tuple[str, str]:
    """C3: hook domain-allowlist отсекает чужие домены до can_use_tool, поэтому
    долетевший WebFetch всегда SAFE. realpath (не abspath): симлинк внутри репо
    наружу (src/x -> ~/.cloud-creds) лексически проходит abspath, но физически
    ведёт за пределы -> CRITICAL."""
    if tool_name == "WebFetch":
        url = (tool_input or {}).get("url", "")
        try:
            p = urlparse(url)
            host = (p.hostname or "").lower().removeprefix("www.")
            secure = p.scheme == "https"
        except (ValueError, AttributeError):
            host, secure = "", False
        if secure and host in ALLOWED_WEBFETCH_HOSTS:
            return "SAFE", f"WebFetch https://{host} (разрешённый read-only домен): {url}"
        return "CRITICAL", f"WebFetch НЕ-разрешённый домен/схема: {url}"
    if tool_name in CRITICAL_TOOLS:
        return "CRITICAL", f"tool={tool_name} в списке критичных"

    def _real_rel(fp: str) -> str:
        abs_fp = fp if os.path.isabs(fp) else os.path.join(REPO_ROOT, fp)
        return os.path.relpath(os.path.realpath(abs_fp), os.path.realpath(REPO_ROOT))

    if tool_name in ("Write", "Edit"):
        fp = tool_input.get("file_path", "")
        rel = _real_rel(fp) if fp else ""
        if any(rel.startswith(p) for p in ALLOWED_WRITE_PREFIXES):
            return "SAFE", f"Write в защищённый путь: {rel}"
        return "CRITICAL", f"Write ВНЕ защищённых путей: {fp}"
    if tool_name in ("Read", "Grep", "Glob"):
        # БАГ 1: read-only ≠ безопасный для ПУТИ (тикет 007 читал зону супервайзера).
        # БАГ 1б: служебные зоны ВНУТРИ репо (.claude/.git/hooks) тоже CRITICAL.
        path_key = "file_path" if tool_name == "Read" else "path"
        fp = (tool_input or {}).get(path_key) or ""
        if fp:
            rel = _real_rel(fp)
            if rel.startswith("..") or os.path.isabs(rel):
                return "CRITICAL", f"{tool_name} ВНЕ репо (realpath): {fp}"
            if rel.startswith(".claude") or rel.startswith(".git") or rel.startswith("hooks"):
                return "CRITICAL", f"{tool_name} служебная зона: {rel}"
        return "SAFE", f"read-only инструмент в репо: {tool_name}"
    return "CRITICAL", f"неизвестный/прочий инструмент: {tool_name}"


def tg_build():
    if not (TG_TOKEN and TG_ALLOWED_IDS):
        log("  [TG] нет кредов — Telegram отключён (C4: архив)")
        return None, ""
    from telegram import Bot
    from telegram.request import HTTPXRequest
    _bot_req = HTTPXRequest(proxy=LOCAL_PROXY, read_timeout=40, connect_timeout=15,
                            write_timeout=15)
    bot = Bot(token=TG_TOKEN, request=_bot_req, get_updates_request=_bot_req)
    return bot, TG_ALLOWED_IDS


async def tg_send(bot, chat_id: str, text: str) -> bool:
    try:
        await bot.send_message(chat_id=int(chat_id), text=text)
        return True
    except Exception as e:  # noqa: BLE001
        log(f"  [TG] sendMessage FAIL: {type(e).__name__}: {e}")
        return False


async def tg_flush_stale(bot) -> int:
    last = 1
    try:
        old = await bot.get_updates(offset=0, timeout=1)
        if old:
            last = max(u.update_id for u in old) + 1
            await bot.get_updates(offset=last, timeout=1)
            log(f"  [TG] сброшено старых апдейтов: {len(old)} (start offset={last})")
    except Exception as e:  # noqa: BLE001
        log(f"  [TG] flush warning: {type(e).__name__}: {e}")
    return last


async def tg_wait_decision(bot, chat_id: str, ask: str, timeout: float) -> tuple[str, str]:
    offset = await tg_flush_stale(bot)
    if not await tg_send(bot, chat_id, ask):
        return ("error", "sendMessage не прошёл — гейт отказал по error")
    deadline = time.time() + timeout
    last_offset = offset
    log(f"  [TG] вопрос отправлен, ждём ответ <= {timeout:.0f}s")
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            lp = min(5.0, remaining)
            updates = await bot.get_updates(offset=last_offset, timeout=max(lp, 1.0),
                                            allowed_updates=["message"])
        except Exception as e:  # noqa: BLE001
            log(f"  [TG] getUpdates err {type(e).__name__} (continue)")
            await asyncio.sleep(1)
            continue
        for u in updates:
            last_offset = max(last_offset, u.update_id + 1)
            m = u.message or u.edited_message
            if not m or not m.from_user:
                continue
            uid = str(m.from_user.id)
            if uid != chat_id:
                log(f"  [TG] игнор сообщения от чужого id={uid}")
                continue
            text = (m.text or "").strip().lower()
            if text in ALLOW_WORDS:
                return ("allow", f"пользователь {uid} ответил: {m.text!r}")
            if text in DENY_WORDS:
                return ("deny", f"пользователь {uid} ответил: {m.text!r}")
            log(f"  [TG] сообщение от {uid} не распознано, жду дальше: {m.text[:60]!r}")
    return ("timeout", f"таймаут {timeout:.0f}s без ответа -> default DENY")


def make_permission_policy(bot, chat_id):
    """can_use_tool callback: Agent-субагенты, SAFE-авто-allow, CRITICAL -> Telegram."""
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )

    async def can_use_tool(tool_name: str, tool_input: dict, context: "ToolPermissionContext"):
        agent = context.agent_id or "MAIN"
        if tool_name == "Agent":
            sub_type = (tool_input or {}).get("subagent_type", "")
            if sub_type in ALLOWED_SUBAGENTS:
                log(f"  [ALLOW-callback] Agent {sub_type} (agent={agent}) -> allow")
                return PermissionResultAllow()
            log(f"  [DENY-callback] Agent (agent={agent}) subagent_type={sub_type!r} "
                f"-> deny (разрешён только {ALLOWED_SUBAGENTS})")
            return PermissionResultDeny()
        klass, reason = classify_criticality(tool_name, tool_input)
        if klass == "SAFE":
            log(f"  [AUTO-ALLOW] {tool_name}: {reason}")
            return PermissionResultAllow()
        if not bot:
            log(f"  [CRITICAL->DENY] {tool_name} (нет Telegram): {reason}")
            return PermissionResultDeny()
        t_start = time.monotonic()
        log(f"  [CRITICAL  ] {tool_name}: {reason}")
        ask = (f"🚦 Stanok 2.0 — запрос\nСессия: станок\nИнструмент: {tool_name}\n"
               f"Вход: {json.dumps(tool_input, ensure_ascii=False)[:300]}\n"
               f"Ответь: allow или deny (таймаут {TG_TIMEOUT:.0f}с -> DENY)")
        decision, detail = await tg_wait_decision(bot, chat_id, ask, TG_TIMEOUT)
        wait = time.monotonic() - t_start
        if decision == "allow":
            log(f"  [TG->ALLOW] {tool_name} ({wait:.1f}s): {detail}")
            return PermissionResultAllow()
        log(f"  [TG->DENY ] {tool_name} ({wait:.1f}s): {detail}")
        return PermissionResultDeny()

    return can_use_tool


# ==================================================================================
# Верификатор (механический гейт, внешний раннер)
# ==================================================================================
def verify_gate() -> tuple[bool, list[tuple[str, str]]]:
    tests = sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "*.test.js")))
    # headless-STOP: пустой tests/ = «ни один деливерабл не создан» (vacuous-PASS исключён).
    if not tests:
        return (False, [("(нет тестов)",
                         "PREMATURE-STOP / NO-DELIVERABLES: после прогона в tests/ нет ни "
                         "одного *.test.js — задача не выполнена; это FAIL (rc!=0), а не пауза")])
    failures: list[tuple[str, str]] = []
    for t in tests:
        base = os.path.basename(t)
        try:
            p = subprocess.run(["node", os.path.join("tests", base)],
                               cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            failures.append((base, "timeout 60s"))
            continue
        if p.returncode != 0:
            out = (p.stdout or "") + "\n" + (p.stderr or "")
            first = next((ln.strip() for ln in out.splitlines()
                          if re.search(r"fail|expected|assert|error|not ok", ln, re.I)),
                         "unknown failure")
            failures.append((base, first))
    return (len(failures) == 0, failures)


def _last_turn_is_text_only(stream_out: str) -> bool:
    """True, если последний AssistantMessage в стриме — ТЕКСТОВАЯ реплика без tool_use
    (признак headless-STOP: модель закончила текстом, не вызвав инструмент)."""
    last_content: list | None = None
    try:
        with open(stream_out, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "AssistantMessage":
                    content = (d.get("data", {}) or {}).get("content") or []
                    if content:
                        last_content = content
    except OSError:
        return False
    if not last_content:
        return False
    has_tool_use = any(isinstance(c, dict) and "name" in c and "input" in c
                       for c in last_content)
    return not has_tool_use


# ==================================================================================
# Security gate (malware-скан -> reviewer-CLEAN)
# ==================================================================================
def security_gate(sid: str, stream_out: str, live_dir: str) -> tuple[bool, str]:
    """Pending-флаг malware-scan для сессии разрешён ТОЛЬКО если:
    (a) флага уже нет (повторный чистый скан -> CLEARED-AUTO), ЛИБО
    (b) реальный reviewer-субагент вернул REVIEW-VERDICT: CLEAN (из
        TaskNotificationMessage.summary, последнее вхождение — анти-false-clean)."""
    flags = sorted(glob.glob(os.path.join(live_dir, "malware-scan", f"pending-{sid}-*.flag")))
    if not flags:
        return True, ""
    spawned = False
    last_verdict = None
    try:
        with open(stream_out, encoding="utf-8") as f:
            for line in f:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") == "AssistantMessage":
                    for c in (d.get("data", {}) or {}).get("content", []) or []:
                        if isinstance(c, dict) and c.get("name") == "Agent":
                            inp = c.get("input", {}) or {}
                            if inp.get("subagent_type") == "reviewer":
                                spawned = True
                    continue
                if d.get("type") == "TaskNotificationMessage" and spawned:
                    dd = (d.get("data") or {}).get("data") or {}
                    summ = dd.get("summary") or ""
                    matches = [m for m in re.finditer(
                        r"REVIEW-VERDICT\s*:\s*(CLEAN|DEFECT)\b", summ)]
                    if matches:
                        last_verdict = matches[-1].group(1)
    except OSError:
        pass
    if spawned and last_verdict == "CLEAN":
        return True, ""
    return False, (f"sid={sid[:8]} pending={[os.path.basename(x) for x in flags]} "
                   f"reviewer_spawned={spawned} last_reviewer_verdict={last_verdict}")


# ==================================================================================
# Cloud-ревьюер (ReviewPolicy + ReviewerBackend через `claude -p`)
# ==================================================================================
def _read_cloud_token() -> str:
    try:
        with open(CLOUD_CREDS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError as e:
        log(f"CLOUD-REVIEWER: не могу прочитать {CLOUD_CREDS}: {e}")
    return ""


def _reviewer_system_prompt() -> str:
    return (
        "You are an independent adversarial reviewer for the stanok codebase. "
        "You do NOT share the author's model's assumptions — review the code fresh. "
        "1. Read the implementation in src/ and the tests in tests/ in full. "
        "2. Hunt adversarially for planted bugs: wrong operator, hidden special-cased "
        "branches, off-by-one, missing edge cases, wrong assertion, incorrect expected "
        "values, tests that pin a buggy contract instead of the true one. "
        "3. Do NOT modify any file. Do NOT attempt to run code — Bash is unavailable. "
        "4. Report exactly one verdict line as your final output: "
        "`REVIEW-VERDICT: CLEAN <why>` OR "
        "`REVIEW-VERDICT: DEFECT <file> <line>: <what is wrong>; <suggested fix>` "
        "then finish. Do not continue past the verdict."
    )


def _cloud_env(token: str) -> dict[str, str]:
    return {
        "PATH": f"{NPM_GLOBAL_BIN}:/usr/local/bin:/usr/bin:/bin",
        "ANTHROPIC_BASE_URL": CLOUD_BASE_URL,
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_MODEL": CLOUD_MODEL,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": CLOUD_MODEL,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": CLOUD_MODEL,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": CLOUD_MODEL,
        "CLAUDE_CODE_SUBAGENT_MODEL": CLOUD_MODEL,
        "API_TIMEOUT_MS": "1200000",
        "MAX_THINKING_TOKENS": "0",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1",
        "http_proxy": LOCAL_PROXY,
        "https_proxy": LOCAL_PROXY,
        "all_proxy": "",
        "no_proxy": NO_PROXY,
    }


def cloud_review(task_prompt: str, state_desc: str,
                 failures: list[tuple[str, str]]) -> tuple[str, str, str]:
    """Внешний `claude -p` на DeepSeek (FAIL-only). (verdict, model, outfile)."""
    token = _read_cloud_token()
    if not token:
        log("CLOUD-REVIEWER: НЕТ токена (~/.cloud-creds пуст) — ERROR")
        return ("ERROR", "", "")
    ts = time.strftime("%Y%m%d-%H%M%S")
    outfile = os.path.join(_live_dir, f"cloud-review-{ts}.jsonl")
    os.makedirs(_live_dir, exist_ok=True)

    fail_lines = "\n".join(f"- {t}: {l}" for t, l in failures)
    review_task = (
        "Тикет станка: " + task_prompt + "\n"
        "Состояние после прогона: " + state_desc + "\n"
        + (f"VERIFY: падающие тесты:\n{fail_lines}\n" if failures else "")
        + "Прочитай src/ и tests/ (Read/Grep/Glob) и вынеси ровно одну строку вердикта "
        "по контракту (CLEAN или DEFECT)."
    )
    cmd = [
        CLAUDE_BIN, "-p",
        "--append-system-prompt", _reviewer_system_prompt(),
        "--tools", "Read,Grep,Glob",
        "--setting-sources", "project",
        "--permission-mode", "acceptEdits",
        "--output-format", "stream-json",
        "--verbose", "--include-hook-events",
        review_task,
    ]
    log(f"CLOUD-REVIEWER: спавн `claude -p` env=cloud({CLOUD_MODEL}) cwd={REPO_ROOT} -> {outfile}")
    rc = None
    try:
        with open(outfile, "w") as out:
            p = subprocess.Popen(cmd, env=_cloud_env(token), stdout=out,
                                 stderr=subprocess.STDOUT, start_new_session=True,
                                 cwd=REPO_ROOT)
            try:
                rc = p.wait(timeout=1800)
            except subprocess.TimeoutExpired:
                p.kill()
                rc = p.wait()
                log(f"CLOUD-REVIEWER: TIMEOUT 1800s -> kill, rc={rc}")
    except Exception as e:  # noqa: BLE001
        log(f"CLOUD-REVIEWER: EXCEPTION при спавне: {type(e).__name__}: {e}")
        return ("ERROR", "", outfile)

    verdict, model = _parse_cloud_review(outfile)
    log(f"CLOUD-REVIEWER: rc={rc} resolvedModel={model} verdict={verdict} "
        f"cloud_review=1 (FAIL-триггер)")
    with open(outfile, "a") as f:
        f.write(json.dumps({"type": "CLOUD_REVIEW_LOG",
                            "data": {"resolvedModel": model, "verdict": verdict,
                                     "rc": rc, "ts": ts}}) + "\n")
    return (verdict, model, outfile)


def _parse_cloud_review(outfile: str) -> tuple[str, str]:
    try:
        with open(outfile, encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return ("ERROR", "")
    model = ""
    m = re.search(r'resolvedModel["\']?\s*[:=]\s*["\']([^"\']+)', text)
    if m:
        model = m.group(1)
    if not model:
        m = re.search(r'"?subagentModel"?\s*:\s*"([^"]+)"', text)
        if m:
            model = m.group(1)
    if not model:
        m = re.search(r'"model"\s*:\s*"([^"]+)"', text)
        if m:
            model = m.group(1)
    if not model:
        model = CLOUD_MODEL
    if re.search(r"REVIEW-VERDICT\s*:\s*DEFECT", text, re.I):
        return ("DEFECT", model)
    if re.search(r"REVIEW-VERDICT\s*:\s*CLEAN", text, re.I):
        return ("CLEAN", model)
    return ("ERROR", model)


# ==================================================================================
# Методологический слой (Matt Pocock; advisory, инжекция --append-system-prompt)
# ==================================================================================
POCOCK_METHODOLOGY_PROMPT = """\
МЕТОДОЛОГИЧЕСКИЙ СЛОЙ (адаптировано из Matt Pocock skills; advisory — не заменяет
hard gates станка: path-guard/test-lock/verifier остаются источником истины).

## TDD (красный -> зелёный)
- Пиши ТЕСТ ПЕРВЫМ (красная фаза: тест падает, модуль ещё не существует), затем —
минимальную реализацию (зелёная фаза). Порядок Write в стриме — доказательство:
сначала tests/<модуль>.test.js, потом src/<модуль>.js.
- Внедряй «швы» (seams): функции — чистое «вход -> выход» без внешнего состояния;
зависимости прокидывай параметром, а не жёстким импортом. Так тест не требует
сети/процессов/таймера и работает детерминированно.
- АНТИ-ПАТТЕРНЫ (три класса — избегать):
1. ТАВТОЛОГИЧЕСКИЙ тест: ожидание вычисляется тем же выражением, что в src, — тест
    дублирует логику реализации и всегда зелёный, ничего не доказывает. Ожидание
    должно быть литеральной фикстурой или вычисляться НЕЗАВИСИМО от реализации.
2. ГОРИЗОНТАЛЬНОЕ нарезание: сначала делается «общий каркас» (только простые случаи),
    а особые случаи не тестируются вовсе. Нарезай по одному НАСТОЯЩЕМУ поведению за раз,
    каждое с полным циклом тест -> реализация -> зелёный.
3. Тест, СЦЕПЛЕННЫЙ с реализацией: повторяет внутренние детали src (приватные функции,
    порядок вызовов), а не контракт «вход -> выход». Изменение src обязано ломать тест
    ТОЛЬКО если меняется наблюдаемое поведение, не внутренности.

## Вертикальные срезы (to-tickets)
- Реализуй один вертикальный срез за раз: от входного параметра до результата функции,
сквозь ВСЕ его особые случаи. Не раскатывай «горизонтальные слои» (сначала каркас всех
функций, потом ветвления всех).
- На каждый срез — свой тест, доказывающий ИМЕННО это поведение (файл
tests/<модуль>.test.js). Покрывай края: пустой вход, кавычки/экранирование,
пограничные значения.

## Спека перед кодом (to-spec)
- Перед реализацией зафиксируй короткую спеку: (a) сигнатура/контракт функции;
(b) обязательные требования тикета — не добавляй своих; (c) граничные случаи из тикета —
каждый станет отдельным ассертом в тесте. В доке (<модуль>.md) указывай, КАКОМУ
требованию соответствует каждый блок кода.

## Двухосевая самопроверка (code-review)
- ОСЬ A (стандарты): код следует идиомам языка и общему стилю.
- ОСЬ B (спека): поведение КОДА соответствует тикету; найденное отклонение от спеки —
это дефект, а не «иначе». Прогони обе оси по СВОЕМУ коду ПЕРЕД завершением работы,
а не после внешнего ревью.

## Границы
- Это советы, а не правила. Правила станка — path-guard (писать только в src/tests/docs),
test-lock (залоченный тест правит только tester), verifier (тесты — механический
источник истины) — в приоритете и обходу не подлежат.
"""


# ==================================================================================
# Env CLI-процесса (локальная модель)
# ==================================================================================
def build_env() -> dict[str, str]:
    base = {
        "ANTHROPIC_BASE_URL": SERVER_URL,
        "ANTHROPIC_AUTH_TOKEN": "local-dummy",
        "ANTHROPIC_API_KEY": "",
        "ANTHROPIC_DEFAULT_SONNET_MODEL": LOCAL_MODEL,
        "ANTHROPIC_DEFAULT_OPUS_MODEL": LOCAL_MODEL,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": LOCAL_MODEL,
        "ANTHROPIC_MODEL": LOCAL_MODEL,
        "CLAUDE_CODE_SUBAGENT_MODEL": LOCAL_MODEL,
        "MAX_THINKING_TOKENS": "0",
        "API_TIMEOUT_MS": "600000",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
        "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
        "CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS": "1",
        "CLAUDE_CODE_DISABLE_ADVISOR_TOOL": "1",
        "http_proxy": LOCAL_PROXY,
        "https_proxy": LOCAL_PROXY,
        "all_proxy": "",
        "no_proxy": NO_PROXY,
    }
    base.update({
        "CLAUDE_CODE_ENABLE_TELEMETRY": "1",
        "OTEL_METRICS_EXPORTER": "otlp",
        "OTEL_LOGS_EXPORTER": "otlp",
        "OTEL_TRACES_EXPORTER": "otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_SERVICE_NAME": "claude-stanok",
        "CLAUDE_CODE_ENHANCED_TELEMETRY_BETA": "1",
    })
    return base


def dataclass_asdict(obj):
    if dataclasses.is_dataclass(obj):
        out = {}
        for f in dataclasses.fields(obj):
            v = getattr(obj, f.name)
            if dataclasses.is_dataclass(v):
                v = dataclass_asdict(v)
            elif isinstance(v, (list, tuple)):
                v = [dataclass_asdict(x) if dataclasses.is_dataclass(x) else x for x in v]
            elif isinstance(v, dict):
                v = {k: dataclass_asdict(x) if dataclasses.is_dataclass(x) else x for k, x in v.items()}
            out[f.name] = v
        return out
    return {"raw": str(obj)}


async def noop_user_prompt_hook(input_, tool_use_id, context):
    return {}


async def run_main_session(prompt: str, session_id: str, stream_out: str,
                           can_use_tool,
                           local_extra_prompt: str = "",
                           pocock_inject: bool = False) -> tuple[str, str]:
    """Один main-прогон SDK (локальная модель). Возвращает (exc, result).

    ДЕФОЛТНЫЙ транспорт SDK (transport=None): _process_query_inner сам ставит
    permission_prompt_tool_name="stdio" при can_use_tool и сам строит
    SubprocessCLITransport. LoggingTransport (_internal) больше НЕ нужен —
    сырой control.log никто не читал, события пишутся публичным API query()."""
    from claude_agent_sdk import ClaudeAgentOptions, query
    from claude_agent_sdk.types import HookMatcher

    full_prompt = prompt + (f"\n\n{local_extra_prompt}" if local_extra_prompt else "")

    async def stream_prompt():
        yield {
            "type": "user",
            "session_id": session_id,
            "message": {"role": "user", "content": full_prompt},
            "parent_tool_use_id": None,
        }

    options = ClaudeAgentOptions(
        cli_path=CLAUDE_BIN,
        cwd=REPO_ROOT,
        setting_sources=["project"],
        settings=f"{REPO_ROOT}/.claude/settings.stanok.json",
        permission_mode="default",
        can_use_tool=can_use_tool,
        hooks={"UserPromptSubmit": [HookMatcher(matcher=None, hooks=[noop_user_prompt_hook])]},
        include_hook_events=True,
        model=LOCAL_MODEL,
        env=build_env(),
        session_id=session_id,
        system_prompt=({"type": "preset", "append": POCOCK_METHODOLOGY_PROMPT}
                       if pocock_inject else None),
    )
    t0 = time.time()
    msg_types = Counter()
    exc = None
    result = None
    log(f"  [main] сессия {session_id} | model={LOCAL_MODEL} | cwd={REPO_ROOT}")
    with open(stream_out, "w", encoding="utf-8") as f:
        f.write(json.dumps({"type": "STANOK_START",
                            "data": {"session_id": session_id, "model": LOCAL_MODEL,
                                     "prompt": full_prompt}}) + "\n")
        try:
            async for msg in query(prompt=stream_prompt(), options=options):
                t = type(msg).__name__
                msg_types[t] += 1
                f.write(json.dumps({"type": t, "data": dataclass_asdict(msg)}) + "\n")
                if t == "ResultMessage":
                    result = str(getattr(msg, "result", "") or "")
        except Exception as e:  # noqa: BLE001
            exc = e
            log(f"  [main] !!! EXCEPTION: {type(e).__name__}: {e}")
    log(f"  [main] время: {time.time()-t0:.1f}s | типы: {dict(msg_types)}")
    return (str(exc) if exc else "", result or "")


def format_failures(vfail: list[tuple[str, str]]) -> str:
    return "; ".join(f"{t}: {l}" for t, l in vfail)


# ==================================================================================
# Job flow (C5: попытки + verifier + локальные ретраи + cloud FAIL-only)
# ==================================================================================
def _verify_and_log(attempt: Attempt) -> None:
    verify_ok, vfail = verify_gate()
    attempt.verify_ok = verify_ok
    attempt.vfail = vfail
    if verify_ok:
        log("VERIFIER: PASS — все тесты прошли")
    else:
        for test, line in vfail:
            log(f"VERIFIER: FAIL — {test}: {line}")
        if _last_turn_is_text_only(attempt.stream):
            log("HEADLESS-STOP: последний ход модели — ТЕКСТОВАЯ реплика без tool_use "
                "(end_turn/EOS), деливераблы не созданы; в headless оператора нет — "
                "это FAIL (rc!=0), а не пауза")
    emit("attempt.verifier", {"attempt": attempt.id, "ok": verify_ok,
                              "failures": attempt.vfail})


async def _run_attempt(job: Job, prompt: str, can_use_tool,
                       local_extra_prompt: str = "",
                       pocock_inject: bool = False) -> Attempt:
    sid = str(uuid.uuid4())
    attempt = Attempt(id=sid, started_at=time.time())
    attempt.stream = os.path.join(_live_dir, f"probe-{sid}.jsonl")
    emit("attempt.start", {"attempt": attempt.id})
    log(f"\n--- попытка {len(job.attempts) + 1} (сессия {sid[:8]}) "
        f"{'(FAIL-контекст)' if local_extra_prompt else ''} ---")
    exc, result = await run_main_session(prompt, sid, attempt.stream, can_use_tool,
                                         local_extra_prompt=local_extra_prompt,
                                         pocock_inject=pocock_inject)
    attempt.exc = exc
    attempt.result = result
    job.attempts.append(attempt)  # важно: job.last()/len(job.attempts) живут этим
    if exc:
        attempt.state = "error"
        job.errors.append(exc)
        log(f"!!! СЕССИЯ ЗАВЕРШИЛАСЬ С ОШИБКОЙ: {exc}")
        emit("attempt.end", {"attempt": attempt.id, "state": "error"})
        return attempt
    _verify_and_log(attempt)
    attempt.ended_at = time.time()
    attempt.state = "passed" if attempt.verify_ok else "failed"
    emit("attempt.end", {"attempt": attempt.id, "state": attempt.state,
                         "verify_ok": attempt.verify_ok})
    return attempt


def _security_final(job: Job) -> int | None:
    """rc=0 возможен только если по ВСЕМ попыткам нет неразрешённых malware-флагов."""
    bad = []
    for a in job.attempts:
        ok, why = security_gate(a.id, a.stream, _live_dir)
        if not ok:
            bad.append(why)
    if bad:
        log(f"SECURITY-GATE: неразрешённые malware-флаги ({len(bad)}):")
        for b in bad:
            log(f"  - {b}")
        log("PROBE-RESULT: SECURITY-PENDING rc=1")
        return 1
    return None


def _finish(job: Job, probe_result: str, rc: int, c5: str | None) -> int:
    job.probe_result = probe_result
    job.rc = rc
    job.c5 = c5
    job.finished_at = time.time()
    job.state = "done"
    sec = _security_final(job)
    if sec is not None:
        return sec
    log(f"PROBE-RESULT: {probe_result} rc={rc} cloud_calls={job.cloud_calls}")
    emit("job.end", {"state": "done", "rc": rc, "probe_result": probe_result,
                     "cloud_calls": job.cloud_calls})
    return rc


def _fail_context(a: Attempt) -> str:
    return (f"VERIFIER: упавшие тесты:\n{format_failures(a.vfail)}\n"
            f"Почини САМУ ПРИЧИНУ (правильный src ИЛИ по-настоящему неверный тест "
            f"— править залоченный тест может только tester).")


async def job_loop(job: Job, args, can_use_tool) -> int:
    prompt = args.prompt_text
    # 1. первый main-прогон
    a1 = await _run_attempt(job, prompt, can_use_tool, pocock_inject=args.pocock_inject)
    if a1.exc:
        return 1
    if a1.verify_ok:
        log("C5: PASS с первой попытки -> rc=0, БЕЗ cloud (policy: не звать когда не нужно)")
        return _finish(job, "CLEAN-FIRST", 0, "PASS")

    # 2. FAIL -> локальные ретраи main (контекст упавшего теста)
    for _ in range(args.local_retries):
        a = await _run_attempt(job, prompt, can_use_tool, local_extra_prompt=_fail_context(job.last()),
                               pocock_inject=args.pocock_inject)
        if a.exc:
            return 1
        if a.verify_ok:
            log("VERIFIER: PASS — все тесты прошли (после локального ретрая)")
            log("C5: PASS после локального ретрая -> rc=0")
            return _finish(job, "PASS-AFTER-LOCAL-RETRY", 0, "PASS")

    last = job.last()
    state_desc = ("PASS-after-local-retries" if last and last.verify_ok
                  else f"FAIL-after-{args.local_retries}-local-retries")

    # 3. cloud_review (FAIL-only)
    if args.no_cloud:
        log(f"C5: --no-cloud — cloud_review ПРОПУЩЕН; verify "
            f"{'PASS' if last and last.verify_ok else 'FAIL'}")
        if last and last.verify_ok:
            return _finish(job, "PASS-AFTER-LOCAL-RETRY", 0, "PASS")
        return 1

    vfail = last.vfail if last else []
    verdict, model, outfile = cloud_review(prompt, state_desc, [] if (last and last.verify_ok) else vfail)
    job.cloud_calls = 1
    job.review_verdict = verdict
    log(f"C5: cloud-вердикт={verdict} resolvedModel={model} evidence={outfile}")
    emit("cloud", {"verdict": verdict, "model": model, "outfile": outfile})

    # 4. результат cloud
    if verdict == "DEFECT":
        for _ in range(args.post_defect_retries):
            extra = (f"Независимый cloud-ревьюер нашёл дефект (см. cloud-review jsonl): "
                     f"{format_failures(vfail) if not (last and last.verify_ok) else 'проверь src/tests свежим взглядом'}. "
                     f"Исправь САМУ ПРИЧИНУ. Тест после лока правит только tester.")
            a = await _run_attempt(job, prompt, can_use_tool, local_extra_prompt=extra,
                                   pocock_inject=args.pocock_inject)
            if a.exc:
                return 1
            if a.verify_ok:
                log("C5: после DEFECT-рерана verify PASS -> rc=0 (PASS+CLEAN)")
                return _finish(job, "CLOUD-DEFECT-TO-PASS", 0, "PASS")
        log("C5: DEFECT-находка не привела к PASS за все рераны -> rc=1")
        return _finish(job, "CLOUD-DEFECT-NO-RESCUE", 1, "FAIL")

    if verdict == "CLEAN":
        if last and last.verify_ok:
            log("C5: cloud CLEAN + verify PASS -> rc=0")
            return _finish(job, "CLOUD-CLEAN-PASS", 0, "PASS")
        log("C5: cloud CLEAN НО verify FAIL -> hard gate rc=1 (cloud не отменяет verifier)")
        return _finish(job, "CLOUD-CLEAN-FAIL", 1, "FAIL")

    # ERROR (нет токена / спавн упал)
    log(f"C5: cloud ERROR (verdict={verdict!r}); verify={'PASS' if last and last.verify_ok else 'FAIL'}")
    if last and last.verify_ok:
        return _finish(job, "CLOUD-ERROR", 0, "PASS")
    return _finish(job, "CLOUD-ERROR", 1, "FAIL")


def _write_summary(job: Job, ticket_arg: str, elapsed_s: int) -> None:
    last = job.last()
    verifier = "PASS" if (last and last.verify_ok) else "FAIL"
    summary = {
        "label": job.label,
        "ticket": ticket_arg,
        "rc": job.rc,
        "elapsed_s": elapsed_s,
        "verifier": verifier,
        "probe_result": job.probe_result,
        "cloud_calls": job.cloud_calls,
        "review_verdict": job.review_verdict,
        "c5": job.c5,
        "errors": job.errors[:5],
    }
    with open(os.path.join(_evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    emit("summary", summary)


# --- сигналы: прерывание прогона (stop/CTRL-C) -------------------------------
def _install_signal_handlers() -> None:
    def handler(signum, frame):
        log(f"\n!!! СИГНАЛ {signum}: прогон прерван (SIGINT/SIGTERM)")
        if _marker_path and os.path.exists(_marker_path):
            os.remove(_marker_path)
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, handler)
    signal.signal(signal.SIGINT, handler)


# ==================================================================================
# run: полный прогон
# ==================================================================================
def cmd_run_real(args) -> int:
    """Полный прогон: гейты -> reset -> доктор -> job_loop. Собирает can_use_tool."""
    global _stdout_log_f, _events_path, _marker_path, _live_dir, _evidence_dir
    label = args.label
    _evidence_dir, _live_dir = label_paths(label)
    os.makedirs(_evidence_dir, exist_ok=True)
    os.makedirs(_live_dir, exist_ok=True)

    stdout_log = os.path.join(_evidence_dir, "launcher.stdout.log")
    _stdout_log_f = open(stdout_log, "a", encoding="utf-8", errors="replace")
    _events_path = os.path.join(_live_dir, "events.jsonl")
    _marker_path = os.path.join(_evidence_dir, ".running")

    os.environ["STANOK_REPO"] = REPO_ROOT
    os.environ["STANOK_EVIDENCE"] = _live_dir
    os.environ.setdefault("STANOK_PY", sys.executable)
    os.environ.setdefault("STANOK_SERVER_URL", SERVER_URL)

    start_ts = int(time.time())
    with open(_marker_path, "w", encoding="utf-8") as f:
        f.write(f"{start_ts} {os.getpid()}\n")
    _install_signal_handlers()

    job = Job(label=label, ticket=args.ticket_arg)
    emit("job.start", {"label": label, "ticket": args.ticket_arg,
                       "pid": os.getpid(), "ts": start_ts})

    # --- баннер ---
    model = os.environ.get("STANOK_MODEL_ALIAS", "?")
    ctx = os.environ.get("STANOK_CTX", "?")
    slots = os.environ.get("STANOK_SLOTS", "?")
    log(f"СЕРВЕР OK  {model} · n_ctx {ctx} · слотов {slots} @ {SERVER_URL}")
    if args.direct:
        log("--direct: headless-запуск напрямую, без супервайзор-обёртки")
    log(f"STANOK 2.0 RUNNER — C1-C5 | model={LOCAL_MODEL} | cwd={REPO_ROOT}")
    log(f"PROBE: cloud_review={'подавлен' if args.no_cloud else 'ACTIVE'} ({CLOUD_MODEL}, FAIL-only) "
        f"| local-retries={args.local_retries} | pocock-inject={args.pocock_inject}")

    # --- reset репо ---
    log("--- reset репо до чистого состояния ---")
    rc = reset_repo()
    if rc != 0:
        return rc
    log("reset ok")

    # --- doctor-гейт (инварианты станка) ---
    doctor_gate(expect_no_cloud=args.no_cloud)

    # --- Telegram (DecisionProvider для CRITICAL-гейтов) ---
    bot, chat_id = tg_build()
    can_use_tool = make_permission_policy(bot, chat_id)

    try:
        rc = asyncio.run(job_loop(job, args, can_use_tool))
    except Exception as e:  # noqa: BLE001
        job.errors.append(str(e))
        log(f"!!! СЕССИЯ ЗАВЕРШИЛАСЬ С ОШИБКОЙ: {e}")
        rc = 1

    elapsed_s = int(time.time()) - start_ts
    job.verifier = "PASS" if (job.last() and job.last().verify_ok) else "FAIL"
    if job.rc is None:
        job.rc = rc
        job.finished_at = time.time()
        job.state = "done"
    _write_summary(job, args.ticket_arg, elapsed_s)

    if _marker_path and os.path.exists(_marker_path):
        os.remove(_marker_path)
    return rc


# ==================================================================================
# status / stop / watch
# ==================================================================================
def cmd_status(label: str) -> int:
    evidence_dir, live_dir = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    summary_path = os.path.join(evidence_dir, "summary.json")
    stdout_log = os.path.join(evidence_dir, "launcher.stdout.log")
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
        try:
            with open(stdout_log, encoding="utf-8", errors="replace") as f:
                lines = [ln.rstrip() for ln in f if ln.strip()]
            out["last_events"] = [ln[:160] for ln in lines[-5:]]
        except OSError:
            pass
    print(json.dumps(out, ensure_ascii=False))
    return 0


def cmd_stop(label: str) -> int:
    evidence_dir, _ = label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    if not os.path.exists(marker):
        log(f"STOP: прогон '{label}' не запущен (.running нет)")
        return 1
    try:
        _start_s, pid_s = open(marker, encoding="utf-8").read().split()
        pid = int(pid_s)
    except (ValueError, OSError):
        log(f"STOP: .running повреждён (нет pid) у '{label}'")
        return 1
    # TERM в группу процессов (демонизированный прогон — лидер группы) + фолбэк на pid.
    # os.killpg/os.kill возвращают None (не 0) при успехе — успех проверяем по отсутствию
    # ProcessLookupError, а не по возврату.
    killed = False
    try:
        os.killpg(pid, signal.SIGTERM)
        killed = True
    except (ProcessLookupError, PermissionError):
        try:
            os.kill(pid, signal.SIGTERM)
            killed = True
        except (ProcessLookupError, PermissionError):
            killed = False
    if killed:
        log(f"STOP: TERM отправлен pid {pid} ({label}) — прогон прерывается")
        log("      после остановки: status <label> -> interrupted или done rc!=0")
    else:
        log(f"STOP: процесс {pid} уже не запущен — убираю stale .running")
        os.remove(marker)
    return 0


def cmd_watch(label: str, follow: bool) -> int:
    """Лёгкий просмотр live-потока: events.jsonl + хвост probe-*.jsonl + stdout."""
    _, live_dir = label_paths(label)
    evidence_dir, _ = label_paths(label)
    events = os.path.join(live_dir, "events.jsonl")
    stdout_log = os.path.join(evidence_dir, "launcher.stdout.log")
    seen = set()
    try:
        while True:
            if os.path.exists(events):
                with open(events, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if not line or line in seen:
                            continue
                        seen.add(line)
                        try:
                            d = json.loads(line)
                            et = d.get("type", "")
                            data = d.get("data", {})
                            if et in ("job.start", "job.end"):
                                print(f"\n=== {et}: {json.dumps(data, ensure_ascii=False)} ===", flush=True)
                            elif et == "attempt.start":
                                print(f"\n--- attempt {data.get('attempt','')[:8]} start ---", flush=True)
                            elif et == "attempt.end":
                                print(f"--- attempt {data.get('attempt','')[:8]} end: {data.get('state')} ---", flush=True)
                            elif et == "attempt.verifier":
                                print(f"verifier: {'PASS' if data.get('ok') else 'FAIL'} "
                                      f"({len(data.get('failures', []))} failed)", flush=True)
                            elif et == "cloud":
                                print(f"cloud: {data.get('verdict')}", flush=True)
                            elif et == "summary":
                                print(f"SUMMARY: rc={data.get('rc')} verifier={data.get('verifier')}", flush=True)
                        except json.JSONDecodeError:
                            print(line[:160], flush=True)
            if os.path.exists(stdout_log):
                with open(stdout_log, encoding="utf-8", errors="replace") as f:
                    for line in f:
                        line = line.rstrip("\n")
                        if line and line not in seen:
                            seen.add(line)
                            print(f"  {line[:160]}", flush=True)
            if not follow:
                break
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    return 0


# ==================================================================================
# CLI
# ==================================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stanok", description="Stanok — единый Runner станка")
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="запустить тикет")
    r.add_argument("ticket", help="путь к тикету (.md)")
    r.add_argument("label", help="evidence-label")
    r.add_argument("--direct", action="store_true", help="тикет относительно репо + баннер")
    r.add_argument("--background", action="store_true", help="детач в фон")
    r.add_argument("--local-retries", type=int, default=int(os.environ.get("STANOK_LOCAL_RETRIES", "1")))
    r.add_argument("--post-defect-retries", type=int, default=2)
    r.add_argument("--no-cloud", action="store_true", help="подавить cloud_review")
    r.add_argument("--pocock-inject", action="store_true")
    r.add_argument("--detached", action="store_true", help=argparse.SUPPRESS)
    r.set_defaults(func=cmd_dispatch_run)

    s = sub.add_parser("status", help="JSON-статус прогона")
    s.add_argument("label")
    s.set_defaults(func=lambda a: cmd_status(a.label))

    st = sub.add_parser("stop", help="прервать прогон")
    st.add_argument("label")
    st.set_defaults(func=lambda a: cmd_stop(a.label))

    w = sub.add_parser("watch", help="живой просмотр")
    w.add_argument("label")
    w.add_argument("--follow", action="store_true")
    w.set_defaults(func=lambda a: cmd_watch(a.label, a.follow))
    return p


def _resolve_ticket(arg: str) -> "tuple[str, list[str]]":
    """Нормализация пути тикета.

    Пробуем по порядку (возвращаем первый существующий файл + весь список попыток):
      1. REPO_ROOT/arg            — канонический вызов станка изнутри (--direct).
      2. project_root/arg         — родитель stanok/ (канонический вызов супервайзера
                                    `launch.sh tickets/x.md` из корня проекта; заодно
                                    чинит удвоение stanok/stanok/tickets/... из TUI,
                                    где cwd часто = корень проекта).
      3. arg как есть             — абсолютный или cwd-relative.

    Если ни один не существует — возвращаем (arg, tried): вызывающий сам печатает
    диагностику со списком попыток.
    """
    project_root = os.path.dirname(REPO_ROOT)
    tried = [
        os.path.join(REPO_ROOT, arg),
        os.path.join(project_root, arg),
        arg,
    ]
    for p in tried:
        if os.path.isfile(p):
            return p, tried
    return tried[-1], tried


def cmd_dispatch_run(args) -> int:
    # label-guard: label не может начинаться с '--' (забыт позиционный аргумент)
    if args.label.startswith("--"):
        print("ERROR: label не может начинаться с '--' — забыт позиционный аргумент <evidence-label>?",
              file=sys.stderr, flush=True)
        print("  usage: stanok run <ticket.md> <evidence-label> [--direct|--background]",
              file=sys.stderr, flush=True)
        return 15

    # нормализация пути тикета: REPO_ROOT (--direct), затем корень ПРОЕКТА
    # (родитель stanok/ — канонический вызов `launch.sh tickets/x.md` из корня),
    # затем как передан (абсолютный или cwd-relative).
    ticket_path, ticket_tried = _resolve_ticket(args.ticket)

    # fail-fast: тикет обязан существовать ДО ветки --background (иначе фоновый
    # детaч родится с мёртвым путём и тихо умрёт в rc=13 в launch.log).
    if not os.path.isfile(ticket_path):
        print(f"ERROR: ticket not found: {ticket_path}", file=sys.stderr, flush=True)
        print("  пробовал: " + "  ->  ".join(ticket_tried), file=sys.stderr, flush=True)
        return 13

    # dirty-tree гейт (fail-closed): reset --hard + clean -fdq затёр бы
    # незакоммиченные изменения — не стартуем, пусть TUI закоммитит сначала.
    if dirty_tree_gate():
        return 22

    # --background: ре-исполниться демоном (внешний детач), мгновенный возврат
    if args.background and not args.detached:
        log_dir = os.path.join(LOG_DIR, args.label)
        os.makedirs(log_dir, exist_ok=True)
        launch_log = os.path.join(LOG_DIR, f"{args.label}.launch.log")
        cmd = [sys.executable, os.path.abspath(__file__), "run", ticket_path, args.label]
        if args.direct:
            cmd.append("--direct")
        if args.no_cloud:
            cmd.append("--no-cloud")
        if args.pocock_inject:
            cmd.append("--pocock-inject")
        cmd.append("--background")
        cmd.append("--detached")
        with open(launch_log, "ab") as fd:
            subprocess.Popen(cmd, stdout=fd, stderr=subprocess.STDOUT,
                             stdin=subprocess.DEVNULL, start_new_session=True)
        print("--- режим --background: станок стартует в фоне ---")
        print(f"    наблюдение: tail -f {launch_log}   (или второй терминал)")
        print(f"    log:        {launch_log}")
        print(f"    evidence:   {os.path.join(REPO_ROOT, 'evidence', args.label)}")
        return 0

    # --- гейты (fail-closed) ---
    root_refusal()
    role_leak_check()

    if not os.path.isdir(os.path.join(REPO_ROOT, ".git")):
        print(f"ERROR: git repo not found: {REPO_ROOT}", file=sys.stderr, flush=True)
        return 12
    if not os.path.isfile(ticket_path):
        print(f"ERROR: ticket not found: {ticket_path}", file=sys.stderr, flush=True)
        print("  пробовал: " + "  ->  ".join(ticket_tried), file=sys.stderr, flush=True)
        return 13

    # lock: ОДИН прогон на репо
    lock_file = f"/tmp/stanok-{hashlib.md5(REPO_ROOT.encode()).hexdigest()[:12]}.lock"
    lf = open(lock_file, "w")
    try:
        fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print(f"LOCK: уже идёт прогон для репо {REPO_ROOT} (lock {lock_file}) — отказ в запуске.",
              file=sys.stderr, flush=True)
        return 21

    # pre-flight: жив ли сервер (rc=20, proxy-less — см. preflight_server)
    props = preflight_server()
    if props:
        os.environ.setdefault("STANOK_MODEL_ALIAS",
                              str(props.get("model_alias") or "?"))
        os.environ.setdefault("STANOK_CTX",
                              str(props.get("default_generation_settings", {}).get("n_ctx") or "?"))
        os.environ.setdefault("STANOK_SLOTS", str(props.get("total_slots") or "?"))

    args.ticket_arg = args.ticket
    try:
        with open(ticket_path, encoding="utf-8") as f:
            args.prompt_text = f.read().strip()
    except OSError as e:
        print(f"ERROR: не могу прочитать тикет {ticket_path}: {e}", file=sys.stderr, flush=True)
        return 13
    if not args.prompt_text:
        print("ERROR: пустой тикет", file=sys.stderr, flush=True)
        return 13

    return cmd_run_real(args)


def main() -> int:
    # implicit `run`: `stanok <ticket> <label>` == `stanok run <ticket> <label>`
    # (восстанавливает старый протокол launch.sh; run/status/stop/watch явные)
    argv = sys.argv[1:]
    if argv and argv[0] not in ("run", "status", "stop", "watch"):
        argv = ["run"] + argv
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
