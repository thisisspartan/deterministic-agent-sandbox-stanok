        #!/usr/bin/env python3
"""Stanok 2.0 — оркестратор Claude Code-станка на локальной модели.

Гоняет одну задачу-тикет на локальном llama-server через Claude Agent SDK:
* TDD-цикл: coder -> tester -> reviewer под детерминированными хуками
    (path-guard / test-lock / domain-allowlist / malware-scan / verifier).
* verify_gate() прогоняет ВСЕ tests/*.test.js (node, реальный exit code)
    -> VERIFIER: PASS/FAIL + rc лаунчера.
* C5 FAIL-only: облачный reviewer вызывается ТОЛЬКО если verify_gate() вернул
    FAIL хотя бы раз; секрет читается из CLOUD_CREDS и передаётся ТОЛЬКО
    через Popen(env=...) (envp) — в argv/ps aux его нет.
* Telegram (C4): опционален, tolerant к отсутствию кредов, из hot-path убран.

Запуск (от НЕ-root):
    ./launch.sh <ticket> <label>              # обычный прогон
    ./launch.sh <ticket> <label> --background # детач в фон
    ./launch.sh status <label>                # JSON-статус

Внешние зависимости (все переопределяются env):
    STANOK_SERVER_URL  — llama-server (дефолт http://192.168.8.131:8080)
    STANOK_MODEL       — имя локальной модели (Qwen3.8-27B-MTP)
    STANOK_PROXY       — прокси для веб-тулинга (дефолт http://192.168.8.131:8118)
    STANOK_NO_PROXY    — no_proxy список (по умолчанию локальный сервер)
    STANOK_CLAUDE_BIN  — бинарь claude-code (дефолт: из PATH)
    STANOK_REPO        — корень репо (дефолт: родитель этого файла)
    STANOK_EVIDENCE    — каталог live-артефактов (дефолт <repo>/evidence)
    STANOK_CLOUD_CREDS — файл секрета облачного reviewer (опционально)
    STANOK_CLOUD_MODEL — модель облачного reviewer (deepseek-v4-flash)
"""
import argparse
import asyncio
import dataclasses
import glob
import json
import os
import re
import shutil
import subprocess
from urllib.parse import urlparse
import sys
import time
import uuid
from collections import Counter
from dataclasses import replace

from claude_agent_sdk import ClaudeAgentOptions, query
from claude_agent_sdk.types import (
    HookMatcher,
    PermissionResultAllow,
    PermissionResultDeny,
    ToolPermissionContext,
)
from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

from telegram import Bot
from telegram.request import HTTPXRequest

# --- Константы контура (переносимы: дефолты выводятся из расположения файла) -----
LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.environ.get("STANOK_REPO", os.path.dirname(LAUNCHER_DIR))
EVIDENCE = os.environ.get("STANOK_EVIDENCE", os.path.join(REPO_ROOT, "evidence"))
CREDS = os.environ.get("STANOK_TG_CREDS", os.path.expanduser("~/.stanok/tg-creds"))

LOCAL_MODEL = os.environ.get("STANOK_MODEL", "Qwen3.8-27B-MTP")
SERVER_URL = os.environ.get("STANOK_SERVER_URL", "http://192.168.8.131:8080")
LOCAL_PROXY = os.environ.get("STANOK_PROXY", "http://192.168.8.131:8118")
NO_PROXY = os.environ.get("STANOK_NO_PROXY", "192.168.8.131,localhost,127.0.0.1")
TG_TIMEOUT = float(os.environ.get("STANOK_TG_TIMEOUT", "120"))

# --- Cloud-ревьюер (C2): внешний LLM, секрет только через envp --------------------
CLOUD_BASE_URL = os.environ.get("STANOK_CLOUD_BASE_URL", "https://api.deepseek.com/anthropic")
CLOUD_MODEL = os.environ.get("STANOK_CLOUD_MODEL", "deepseek-v4-flash")
CLOUD_CREDS = os.environ.get("STANOK_CLOUD_CREDS", os.path.expanduser("~/.cloud-creds"))
CLAUDE_BIN = os.environ.get("STANOK_CLAUDE_BIN", shutil.which("claude") or "claude")
NPM_GLOBAL_BIN = os.environ.get("STANOK_NPM_BIN", os.path.dirname(CLAUDE_BIN))

# subagent_type, который main-агент может спавнить (C1: reviewer(внешний) + tester)
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

# --- FINDING-2: launcher никогда не должен работать от root ----------------------
def root_refusal() -> None:
    if os.geteuid() == 0:
        print("STANOK-CC ABORT: станок нельзя запускать от root", file=sys.stderr, flush=True)
        sys.exit(1)


def doctor_gate(expect_no_cloud: bool = False) -> None:
    env = dict(os.environ)
    if expect_no_cloud:
        # ПАТЧ 5: на прогоне без облака doctor.sh ДОЛЖЕН подтвердить тишину cloud.
        env["DOCTOR_EXPECT_NO_CLOUD"] = "1"
    rc = subprocess.call(["bash", f"{REPO_ROOT}/hooks/doctor.sh"], env=env)
    if rc != 0:
        print(f"STANOK-CC ABORT: doctor.sh — инварианты станка не выполнены (rc={rc})",
            file=sys.stderr, flush=True)
        sys.exit(1)


# --- Telegram (C4: в hot-path не участвует; tolerant к отсутствию кредов) ----------
def tg_build():
    """Возвращает (bot|None, chat_id|''). Отсутствие кредов НЕ роняет прогон
    (в финальной архитектуре Telegram->архив, init под флагом, default off)."""
    if not (TG_TOKEN and TG_ALLOWED_IDS):
        print("  [TG] нет кредов — Telegram отключён (C4: архив)", flush=True)
        return None, ""
    _bot_req = HTTPXRequest(
        proxy=LOCAL_PROXY,
        read_timeout=40, connect_timeout=15, write_timeout=15,
    )
    bot = Bot(token=TG_TOKEN, request=_bot_req, get_updates_request=_bot_req)
    return bot, TG_ALLOWED_IDS


async def tg_send(bot, chat_id: str, text: str) -> bool:
    try:
        await bot.send_message(chat_id=int(chat_id), text=text)
        return True
    except Exception as e:  # noqa: BLE001
        print(f"  [TG] sendMessage FAIL: {type(e).__name__}: {e}", flush=True)
        return False


async def tg_flush_stale(bot) -> int:
    last = 1
    try:
        old = await bot.get_updates(offset=0, timeout=1)
        if old:
            last = max(u.update_id for u in old) + 1
            await bot.get_updates(offset=last, timeout=1)
            print(f"  [TG] сброшено старых апдейтов: {len(old)} (start offset={last})", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  [TG] flush warning: {type(e).__name__}: {e}", flush=True)
    return last


async def tg_wait_decision(bot, chat_id: str, ask: str, timeout: float) -> tuple[str, str]:
    offset = await tg_flush_stale(bot)
    if not await tg_send(bot, chat_id, ask):
        return ("error", "sendMessage не прошёл — гейт отказал по error")
    deadline = time.time() + timeout
    last_offset = offset
    print(f"  [TG] вопрос отправлен, ждём ответ <= {timeout:.0f}s", flush=True)
    while time.time() < deadline:
        remaining = deadline - time.time()
        try:
            lp = min(5.0, remaining)
            updates = await bot.get_updates(
                offset=last_offset, timeout=max(lp, 1.0), allowed_updates=["message"]
            )
        except Exception as e:  # noqa: BLE001
            print(f"  [TG] getUpdates err {type(e).__name__} (continue)", flush=True)
            await asyncio.sleep(1)
            continue
        for u in updates:
            last_offset = max(last_offset, u.update_id + 1)
            m = u.message or u.edited_message
            if not m or not m.from_user:
                continue
            uid = str(m.from_user.id)
            if uid != chat_id:
                print(f"  [TG] игнор сообщения от чужого id={uid}", flush=True)
                continue
            text = (m.text or "").strip().lower()
            if text in ALLOW_WORDS:
                return ("allow", f"пользователь {uid} ответил: {m.text!r}")
            if text in DENY_WORDS:
                return ("deny", f"пользователь {uid} ответил: {m.text!r}")
            print(f"  [TG] сообщение от {uid} не распознано, жду дальше: {m.text[:60]!r}", flush=True)
    return ("timeout", f"таймаут {timeout:.0f}s без ответа -> default DENY")


# --- Классификатор критичности (без изменений; WebFetch-ветка упрощается в C3) ----
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
    """C3: hook domain-allowlist уже отсекает чужие домены до can_use_tool,
    поэтому долетевший WebFetch всегда SAFE (авто-allow). Ремень, не гейт."""
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
    # realpath (не abspath): симлинк внутри репо, ведущий наружу (напр. src/x ->
    # /home/hermes/.cloud-creds), лексически пройдёт abspath-проверку, но физически
    # ведёт за пределы. realpath резолвит -> rel.startswith("..") -> CRITICAL.
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
        # БАГ 1 фикс: read-only ≠ безопасный для ПУТИ. Read/Grep/Glob по абсолютному
        # пути за пределами репо (напр. /home/hermes/darkcast/CONTEXT.md — зона
        # супервайзера) = CRITICAL -> ручной гейт. Без этого станок читал чужие
        # файлы и перенимал роль супервайзера (тикет 007, test-007-rerun).
        # БАГ 1б: служебные зоны ВНУТРИ репо (.claude/, .git/, hooks/) тоже
        # CRITICAL — чтение конфига станка засоряло контекст мета-данными и
        # провоцировало роль-конфузию (test-e2e-final: settings.stanok.json).
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


# --- Верификатор #104 (механический гейт, внешний раннер) -------------------------
def verify_gate() -> tuple[bool, list[tuple[str, str]]]:
    tests = sorted(glob.glob(os.path.join(REPO_ROOT, "tests", "*.test.js")))
    # headless-STOP фикс (2026-08-19): пустой tests/ = НЕ «все тесты прошли» вакуумно,
    # а «ни один деливерабл не создан». В headless оператора нет — ждать некому,
    # пауза = FAIL. Иначе модель, закончившая ход текстом (end_turn/EOS) без
    # deliverables, давала бы vacuous PASS -> CLEAN-FIRST rc=0 (FALSE-CLEAN).
    if not tests:
        return (False, [("(нет тестов)",
                        "PREMATURE-STOP / NO-DELIVERABLES: после прогона в tests/ нет ни "
                        "одного *.test.js — задача не выполнена; в headless ждать оператора "
                        "некому, это FAIL (rc!=0), а не пауза")])
    failures: list[tuple[str, str]] = []
    for t in tests:
        base = os.path.basename(t)
        try:
            p = subprocess.run(
                ["node", os.path.join("tests", base)],
                cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
            )
        except subprocess.TimeoutExpired:
            failures.append((base, "timeout 60s"))
            continue
        if p.returncode != 0:
            out = (p.stdout or "") + "\n" + (p.stderr or "")
            first = next(
                (ln.strip() for ln in out.splitlines()
                if re.search(r"fail|expected|assert|error|not ok", ln, re.I)),
                "unknown failure",
            )
            failures.append((base, first))
    return (len(failures) == 0, failures)


def _last_turn_is_text_only(stream_out: str) -> bool:
    """True, если последний AssistantMessage в стриме — ТЕКСТОВАЯ реплика БЕЗ tool_use.

    Признак headless-STOP: модель сама решила «готово» (end_turn/EOS) после текста-отчёта,
    не вызвав инструмент и не доведя дело. tool_use-блок в content имеет ключи
    {'id','name','input'}; текст — {'text'}; думание — {'thinking','signature'}."""
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


# --- Cloud-ревьюер (C2) -----------------------------------------------------------
def _read_cloud_token() -> str:
    """Секрет ТОЛЬКО из ~/.cloud-creds (0600). В argv не попадает никогда."""
    try:
        with open(CLOUD_CREDS, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("DEEPSEEK_TOKEN="):
                    return line.split("=", 1)[1].strip()
    except OSError as e:
        print(f"CLOUD-REVIEWER: не могу прочитать {CLOUD_CREDS}: {e}", flush=True)
    return ""


def _reviewer_system_prompt() -> str:
    """Тот же контракт, что reviewer.md — независимый adversarial reviewer."""
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


# --- Методологический слой (Matt Pocock skills, инжекция через --append-system-prompt) --
# Добавлен через ClaudeAgentOptions(system_prompt={"type":"preset","append":...}) -> SDK
# мапит в `--append-system-prompt` (ADДИТИВНО, не заменяет базовый/CLAUDE.md). Это
# методический текст, а НЕ правила: hard gates (path-guard/test-lock/verifier) — источник
# истины и обходу не подлежат. Флаг --pocock-inject включает инжекцию для A/B-пробы.
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


def _cloud_env(token: str) -> dict[str, str]:
    """ОТДЕЛЬНЫЙ env-словарь для cloud-спавна (execve envp). Process-env перебивает
    settings.json env, поэтому local-base_url из project-settings не контаминирует.
    Popen env= = чистый env как env -i: наследованного окружения нет."""
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
        # интернет ТОЛЬКО через прокси; локальная модель в no_proxy.
        "http_proxy": LOCAL_PROXY,
        "https_proxy": LOCAL_PROXY,
        "all_proxy": "",
        "no_proxy": NO_PROXY,
    }


def cloud_review(task_prompt: str, state_desc: str,
                failures: list[tuple[str, str]]) -> tuple[str, str, str]:
    """C2+C5: внешний `claude -p` на DeepSeek. Вызывается ТОЛЬКО после FAIL>=1.

    Возвращает (verdict, model, outfile); verdict: 'CLEAN'|'DEFECT'|'ERROR'."""
    token = _read_cloud_token()
    if not token:
        print("CLOUD-REVIEWER: НЕТ токена (~/.cloud-creds пуст) — ERROR", flush=True)
        return ("ERROR", "", "")
    ts = time.strftime("%Y%m%d-%H%M%S")
    outfile = f"{EVIDENCE}/cloud-review-{ts}.jsonl"
    os.makedirs(EVIDENCE, exist_ok=True)

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
    print(f"CLOUD-REVIEWER: спавн `claude -p` env=cloud({CLOUD_MODEL}) cwd={REPO_ROOT} -> {outfile}",
        flush=True)
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
                print(f"CLOUD-REVIEWER: TIMEOUT 1800s -> kill, rc={rc}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"CLOUD-REVIEWER: EXCEPTION при спавне: {type(e).__name__}: {e}", flush=True)
        return ("ERROR", "", outfile)

    verdict, model = _parse_cloud_review(outfile)
    print(f"CLOUD-REVIEWER: rc={rc} resolvedModel={model} verdict={verdict} "
        f"cloud_review=1 (FAIL-триггер)", flush=True)
    # observability: resolvedModel записан в evidence (audit «ровно один cloud-спавн»).
    with open(outfile, "a") as f:
        f.write(json.dumps({"type": "CLOUD_REVIEW_LOG",
                            "data": {"resolvedModel": model, "verdict": verdict,
                                    "rc": rc, "ts": ts}}) + "\n")
    return (verdict, model, outfile)


def _parse_cloud_review(outfile: str) -> tuple[str, str]:
    """(verdict, model) из cloud-review.jsonl. Формат-факт S227: парсить по
    ключевым словам CLEAN/DEFECT, не строго. resolvedModel из событий."""
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


# --- ПАТЧ 2: security-gate (малвар-скан -> эскалация через reviewer) --------------
def security_gate(sid: str, stream_out: str) -> tuple[bool, str]:
    """Pending-флаг malware-scan для сессии разрешён ТОЛЬКО если:
    (a) флага уже нет (повторный чистый скан того же файла -> CLEARED-AUTO), ЛИБО
    (b) реальный reviewer-субагент вернул REVIEW-VERDICT: CLEAN в своём выводе.
    Вердикт берётся из TaskNotificationMessage.summary (итоговый вывод async-субагента:
    субагенты спавнятся как ASYNC-агенты, tool_result в UserMessage НЕ возвращается —
    только TaskNotificationMessage + output_file). UserMessage НЕ читается: async-launch
    метаданные содержат шаблон формата из промпта («REVIEW-VERDICT: CLEAN или
    REVIEW-VERDICT: DEFECT») и дают ложный CLEAN. Fail-closed: флаг без reviewer-CLEAN
    => (False, причина)."""
    flags = sorted(glob.glob(os.path.join(EVIDENCE, "malware-scan", f"pending-{sid}-*.flag")))
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
                    # ПРЕДОТВРАЩЕНИЕ FALSE-CLEAN ПО ШАБЛОНУ: искать вердикт НЕ в
                    # первой строке вывода (там может быть шаблон «CLEAN или DEFECT»),
                    # а в финальной части — реальный вердикт стоит в КОНЦЕ ответа
                    # субагента. Используем ТОЛЬКО последнее вхождение REVIEW-VERDICT.
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


# --- Логирование сырого контрольного канала (CLI<->SDK) -------------------------
class LoggingTransport:
    def __init__(self, prompt, options, log_path: str):
        configured = replace(options, permission_prompt_tool_name="stdio")
        self.inner = SubprocessCLITransport(prompt=prompt, options=configured)
        self._log_path = log_path
        self._log(f"[{time.time():.3f}] LoggingTransport init; {options.cwd}")

    def _log(self, msg: str) -> None:
        with open(self._log_path, "a") as f:
            f.write(msg + "\n")

    async def connect(self) -> None:
        await self.inner.connect()

    async def write(self, data: str) -> None:
        self._log(f"[{time.time():.3f}] WRITE->stdin: {data[:200]!r}")
        await self.inner.write(data)

    def read_messages(self):
        return self._logged_read()

    async def _logged_read(self):
        async for msg in self.inner.read_messages():
            t = msg.get("type")
            req = msg.get("request") or {}
            self._log(f"[{time.time():.3f}] READ<-stdout: type={t} "
                    f"subtype={req.get('subtype','')} tool={req.get('tool_name','')}")
            yield msg

    async def close(self) -> None:
        await self.inner.close()

    def is_ready(self) -> bool:
        return self.inner.is_ready()

    async def end_input(self) -> None:
        self._log(f"[{time.time():.3f}] end_input() CALLED")
        await self.inner.end_input()


async def noop_user_prompt_hook(input_, tool_use_id, context):
    return {}


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


# --- Env CLI-процесса (локальная модель, #133) -----------------------------------
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


async def run_main_session(prompt: str, session_id: str, stream_out: str,
                        control_log: str, can_use_tool,
                        local_extra_prompt: str = "",
                        pocock_inject: bool = False) -> tuple[str, str]:
    """Один main-прогон SDK (локальная модель). Возвращает (exc, result).

    pocock_inject=True: ClaudeAgentOptions(system_prompt={"type":"preset","append":...})
    -> SDK мапит в `--append-system-prompt` (АДДИТИВНО к базовому системному промпту и
    project-context/CLAUDE.md). str-форма (`--system-prompt`) ЗАМЕНИЛА бы базовый промпт —
    потому dict-form обязателен. Проверено в subprocess_cli.py 568-577."""
    full_prompt = prompt + (f"\n\n{local_extra_prompt}" if local_extra_prompt else "")

    async def stream_prompt():
        yield {
            "type": "user",
            "session_id": "",
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
    transport = LoggingTransport(prompt=stream_prompt(), options=options, log_path=control_log)
    t0 = time.time()
    msg_types = Counter()
    exc = None
    result = None
    print(f"  [main] сессия {session_id} | model={LOCAL_MODEL} | cwd={REPO_ROOT}", flush=True)
    with open(stream_out, "w") as f:
        f.write(json.dumps({"type": "STANOK_START",
                            "data": {"session_id": session_id, "model": LOCAL_MODEL,
                                    "prompt": full_prompt}}) + "\n")
        try:
            async for msg in query(prompt=stream_prompt(), options=options, transport=transport):
                t = type(msg).__name__
                msg_types[t] += 1
                f.write(json.dumps({"type": t, "data": dataclass_asdict(msg)}) + "\n")
                if t == "ResultMessage":
                    result = str(getattr(msg, "result", "") or "")
        except Exception as e:  # noqa: BLE001
            exc = e
            print(f"  [main] !!! EXCEPTION: {type(e).__name__}: {e}", flush=True)
    print(f"  [main] время: {time.time()-t0:.1f}s | типы: {dict(msg_types)}", flush=True)
    return (str(exc) if exc else "", result or "")


def format_failures(vfail: list[tuple[str, str]]) -> str:
    return "; ".join(f"{t}: {l}" for t, l in vfail)


async def main() -> int:
    ap = argparse.ArgumentParser(prog="stanok-sdk-probe.py",
                                description="PROBE-лаунчер Stanok 2.0 (копия, C1-C5)")
    ap.add_argument("prompt", help="текст задачи")
    ap.add_argument("--local-retries", type=int, default=3,
                    help="локальные ретраи main после FAIL (C5, default 3)")
    ap.add_argument("--post-defect-retries", type=int, default=2,
                    help="рераны после cloud-DEFECT-находки (C5, default 2)")
    ap.add_argument("--no-cloud", action="store_true",
                    help="подавить cloud_review (для проб без облака)")
    ap.add_argument("--pocock-inject", action="store_true",
                    help="инжектировать POCOCK_METHODOLOGY_PROMPT через --append-system-prompt "
                        "(A/B-проба методологии)")
    args = ap.parse_args()
    prompt = args.prompt.strip()
    if not prompt:
        print("USAGE: stanok-sdk-probe.py \"<TASK>\" [--local-retries N] [--no-cloud]",
            file=sys.stderr, flush=True)
        return 2

    root_refusal()
    doctor_gate(expect_no_cloud=args.no_cloud)
    bot, chat_id = tg_build()
    os.makedirs(EVIDENCE, exist_ok=True)

    sessions: list[tuple[str, str]] = []

    def final(rc: int) -> int:
        """ПАТЧ 2: rc=0 возможен только если по ВСЕМ сессиям нет неразрешённых
        malware-флагов (каждый либо снят авто-клиром, либо имеет reviewer-CLEAN)."""
        bad: list[str] = []
        for sid_, so_ in sessions:
            ok, why = security_gate(sid_, so_)
            if not ok:
                bad.append(why)
        if bad:
            print(f"SECURITY-GATE: неразрешённые malware-флаги ({len(bad)}):", flush=True)
            for b in bad:
                print(f"  - {b}", flush=True)
            print("PROBE-RESULT: SECURITY-PENDING rc=1", flush=True)
            return 1
        return rc

    async def can_use_tool(tool_name: str, tool_input: dict, context: ToolPermissionContext):
        agent = context.agent_id or "MAIN"
        if tool_name == "Agent":
            sub_type = (tool_input or {}).get("subagent_type", "")
            if sub_type in ALLOWED_SUBAGENTS:
                print(f"  [ALLOW-callback] Agent {sub_type} (agent={agent}) -> allow", flush=True)
                return PermissionResultAllow()
            print(f"  [DENY-callback] Agent (agent={agent}) subagent_type={sub_type!r} "
                f"-> deny (разрешён только {ALLOWED_SUBAGENTS})", flush=True)
            return PermissionResultDeny()
        klass, reason = classify_criticality(tool_name, tool_input)
        if klass == "SAFE":
            print(f"  [AUTO-ALLOW] {tool_name}: {reason}", flush=True)
            return PermissionResultAllow()
        if not bot:
            print(f"  [CRITICAL->DENY] {tool_name} (нет Telegram): {reason}", flush=True)
            return PermissionResultDeny()
        t_start = time.monotonic()
        print(f"  [CRITICAL  ] {tool_name}: {reason}", flush=True)
        ask = (f"🚦 Stanok 2.0 (probe) — запрос\nСессия: probe\nИнструмент: {tool_name}\n"
            f"Вход: {json.dumps(tool_input, ensure_ascii=False)[:300]}\n"
            f"Ответь: allow или deny (таймаут {TG_TIMEOUT:.0f}с -> DENY)")
        decision, detail = await tg_wait_decision(bot, chat_id, ask, TG_TIMEOUT)
        wait = time.monotonic() - t_start
        if decision == "allow":
            print(f"  [TG->ALLOW] {tool_name} ({wait:.1f}s): {detail}", flush=True)
            return PermissionResultAllow()
        print(f"  [TG->DENY ] {tool_name} ({wait:.1f}s): {detail}", flush=True)
        return PermissionResultDeny()

    # ---- C5: поток прогона ----
    print(f"STANOK 2.0 PROBE — C1-C5 | model={LOCAL_MODEL} | cwd={REPO_ROOT}", flush=True)
    print(f"PROBE: cloud_review={'подавлен' if args.no_cloud else 'ACTIVE'} "
        f"({CLOUD_MODEL}, FAIL-only) | local-retries={args.local_retries} "
        f"| pocock-inject={args.pocock_inject}", flush=True)

    # 1. первый main-прогон
    sid = str(uuid.uuid4())
    stream_out = f"{EVIDENCE}/probe-{sid}.jsonl"
    control_log = f"{EVIDENCE}/probe-{sid}.control.log"
    exc, result = await run_main_session(prompt, sid, stream_out, control_log, can_use_tool,
                                        pocock_inject=args.pocock_inject)
    sessions.append((sid, stream_out))
    if exc:
        print(f"!!! СЕССИЯ ЗАВЕРШИЛАСЬ С ОШИБКОЙ: {exc}", flush=True)
        return 1

    # 2. verify
    print("\n--- VERIFIER (механический гейт #104) ---", flush=True)
    verify_ok, vfail = verify_gate()
    if verify_ok:
        print("VERIFIER: PASS — все тесты прошли", flush=True)
    else:
        for test, line in vfail:
            print(f"VERIFIER: FAIL — {test}: {line}", flush=True)
        if _last_turn_is_text_only(stream_out):
            print("HEADLESS-STOP: последний ход модели — ТЕКСТОВАЯ реплика без tool_use "
                "(end_turn/EOS), деливераблы не созданы; в headless оператора нет — "
                "это FAIL (rc!=0), а не пауза", flush=True)

    if verify_ok:
        print("C5: PASS с первой попытки -> rc=0, БЕЗ cloud (policy: не звать когда не нужно)",
            flush=True)
        print(f"PROBE-RESULT: CLEAN-FIRST rc=0 cloud_calls=0", flush=True)
        return final(0)

    # 3. FAIL хотя бы раз -> локальные ретраи main (контекст упавшего теста)
    retry = 0
    while retry < args.local_retries and not verify_ok:
        retry += 1
        extra = (f"VERIFIER: упавшие тесты:\n{format_failures(vfail)}\n"
                f"Почини САМУ ПРИЧИНУ (правильный src ИЛИ по-настоящему неверный тест "
                f"— править залоченный тест может только tester).")
        print(f"\nC5: локальный ретрай main #{retry} (FAIL-контекст)", flush=True)
        sid = str(uuid.uuid4())
        stream_out = f"{EVIDENCE}/probe-{sid}.jsonl"
        control_log = f"{EVIDENCE}/probe-{sid}.control.log"
        exc, result = await run_main_session(prompt, sid, stream_out, control_log,
                                            can_use_tool, local_extra_prompt=extra,
                                            pocock_inject=args.pocock_inject)
        sessions.append((sid, stream_out))
        if exc:
            print(f"!!! СЕССИЯ ЗАВЕРШИЛАСЬ С ОШИБКОЙ: {exc}", flush=True)
            return 1
        verify_ok, vfail = verify_gate()
        if verify_ok:
            print("VERIFIER: PASS — все тесты прошли (после локального ретрая)", flush=True)
        else:
            for test, line in vfail:
                print(f"VERIFIER: FAIL — {test}: {line}", flush=True)
            if _last_turn_is_text_only(stream_out):
                print("HEADLESS-STOP: ретрай снова закончился текстом без tool_use — "
                    "модель не выполняет шаги инструментами; rc!=0", flush=True)

    state_desc = ("PASS-after-local-retries" if verify_ok else
                f"FAIL-after-{args.local_retries}-local-retries")

    # 4. cloud_review (FAIL-only)
    if args.no_cloud:
        print(f"C5: --no-cloud — cloud_review ПРОПУЩЕН; verify {'PASS' if verify_ok else 'FAIL'}",
            flush=True)
        if verify_ok:
            # PROBE-RESULT обязателен: по нему summary.json заполняет probe_result/cloud_calls
            # (без строки локальный PASS был бы невидим в сводке супервайзера).
            print(f"PROBE-RESULT: PASS-AFTER-LOCAL-RETRY rc=0 cloud_calls=0", flush=True)
            return final(0)
        return 1

    verdict, model, outfile = cloud_review(prompt, state_desc, [] if verify_ok else vfail)
    print(f"C5: cloud-вердикт={verdict} resolvedModel={model} evidence={outfile}", flush=True)

    # 5. результат cloud
    if verdict == "DEFECT":
        # находка -> реран main с находкой -> verify
        for i in range(args.post_defect_retries):
            print(f"\nC5: реран #{i+1} после cloud-DEFECT (применяем находку)", flush=True)
            sid = str(uuid.uuid4())
            stream_out = f"{EVIDENCE}/probe-{sid}.jsonl"
            control_log = f"{EVIDENCE}/probe-{sid}.control.log"
            extra = (f"Независимый cloud-ревьюер нашёл дефект (см. cloud-review jsonl): "
                    f"{format_failures(vfail) if not verify_ok else 'проверь src/tests свежим взглядом'}. "
                    f"Исправь САМУ ПРИЧИНУ. Тест после лока правит только tester.")
            exc, result = await run_main_session(prompt, sid, stream_out, control_log,
                                                can_use_tool, local_extra_prompt=extra,
                                                pocock_inject=args.pocock_inject)
            sessions.append((sid, stream_out))
            if exc:
                print(f"!!! СЕССИЯ ЗАВЕРШИЛАСЬ С ОШИБКОЙ: {exc}", flush=True)
                return 1
            verify_ok, vfail = verify_gate()
            if verify_ok:
                print(f"C5: после DEFECT-рерана verify PASS -> rc=0 (PASS+CLEAN)", flush=True)
                print(f"PROBE-RESULT: CLOUD-DEFECT-TO-PASS rc=0 cloud_calls=1", flush=True)
                return final(0)
        print("C5: DEFECT-находка не привела к PASS за все рераны -> rc=1", flush=True)
        print(f"PROBE-RESULT: CLOUD-DEFECT-NO-RESCUE rc=1 cloud_calls=1", flush=True)
        return 1

    if verdict == "CLEAN":
        if verify_ok:
            print("C5: cloud CLEAN + verify PASS -> rc=0", flush=True)
            print(f"PROBE-RESULT: CLOUD-CLEAN-PASS rc=0 cloud_calls=1", flush=True)
            return final(0)
        print("C5: cloud CLEAN НО verify FAIL -> hard gate rc=1 (cloud не отменяет verifier)",
            flush=True)
        print(f"PROBE-RESULT: CLOUD-CLEAN-FAIL rc=1 cloud_calls=1", flush=True)
        return 1

    # ERROR (нет токена / спавн упал)
    print(f"C5: cloud ERROR (verdict={verdict!r}); verify={'PASS' if verify_ok else 'FAIL'}",
        flush=True)
    print(f"PROBE-RESULT: CLOUD-ERROR rc={'0' if verify_ok else '1'}", flush=True)
    return final(0) if verify_ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
