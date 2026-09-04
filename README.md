# stanok — станок Claude Code на локальной модели

Автономный «станок»: берёт текстовый тикет, решает его TDD-циклом
(coder → tester → reviewer) под детерминированными хуками, гоняет
`node tests/*.test.js` и выдаёт итог в `evidence/<label>/summary.json`.

Это — инфраструктура. Код проекта (`src/`, `tests/`, `docs/`) и тикеты
живут в родительском репо (см. README на уровень выше). Этот репо —
подключаемый git-submodule для любого проекта.

## Требования

- Python 3.12+, Node.js (запуск тестов), claude-code (бинарь станка)
- Локальный llama-server, Anthropic-совместимый (`STANOK_SERVER_URL`)
- Родительский репо НЕ должен содержать `CLAUDE.md` выше этого репо
  (роль контроль-рума задаётся через `--append-system-prompt-file`,
  иначе станок автозагружает родительский CLAUDE.md — ролевой утёк)

## Установка

```bash
./setup.sh                                   # .venv + claude-agent-sdk
DOCTOR_EXPECT_NO_CLOUD=1 bash hooks/doctor.sh  # ожидается: 12 ok, 0 fail
```

## Запуск

```bash
./launch.sh run <ticket.md> <label> [--background|--direct]
# `run` необязателен: `./launch.sh <ticket.md> <label> [--background|--direct]` эквивалентно.
# Тикет резолвится по трём базам (корень проекта -> корень станка -> как передан),
# поэтому канонический вызов из корня проекта: `./stanok/launch.sh tickets/x.md <label>`.
# Shim сам cd'ит в корень проекта: вызов работает из любого cwd; --background с
# несуществующим тикетом падает сразу (rc=13), а не рожает мёртвый детaч.
./launch.sh status <label>      # JSON: running/done/interrupted/missing
./launch.sh stop <label>        # прервать прогон (TERM по pid из .running)
./launch.sh watch <label>       # живой просмотр events.jsonl + stdout
```

- `--background` — детач в фон (наблюдение: `tail -f /tmp/stanok-logs/<label>.launch.log`)
- `--direct` — headless напрямую, путь тикета относительно репо

## Структура

```
launcher/stanok.py            — ЕДИНЫЙ Runner (CLI run/status/stop/watch,
                                гейты, Job/Attempt, typed summary.json)
launch.sh                     — тонкий shim: exec venv-python launcher/stanok.py
hooks/                        — детерминированные гейты (path-guard,
                                test-lock, malware-scan, verifier, …)
.claude/agents/               — роли coder/reviewer/tester
.claude/settings.stanok.json  — песочница станка (allow/deny, хуки)
CLAUDE.md                     — роль станка (автозагружается внутри репо)
setup.sh                      — развёртывание окружения (.venv)
src/ tests/ docs/             — рабочие каталоги станка (пустые, на старте)
```

## Конфигурация (все через env)

| Переменная           | Дефолт                       | Что задаёт                |
|----------------------|------------------------------|---------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`  | llama-server              |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`            | локальная модель          |
| `STANOK_PROXY`       | `http://127.0.0.1:8118`  | прокси для веб-тулинга    |
| `STANOK_CLAUDE_BIN`  | `claude` (из PATH)           | бинарь claude-code        |
| `STANOK_PY`          | `<repo>/.venv/bin/python`    | python для Runner         |
| `STANOK_REPO`        | `<repo>/stanok`              | корень станка (перекрытие)|
| `STANOK_EVIDENCE`    | live-дир (`/tmp/stanok-logs`) | флаги malware-scan        |
| `STANOK_CLOUD_CREDS` | `~/.cloud-creds`             | секрет облачного reviewer |

## Как это устроено (коротко)

1. `launch.sh run` (shim → Runner) проходит гейты fail-closed: ROLE-LEAK
   (rc=24), lock (rc=21), dirty-tree (rc=22, незакоммиченные изменения — старт
   запрещён), pre-flight `/props` сервера (rc=20). Только на чистом дереве
   сбрасывает репо в чистое состояние (`git reset --hard` + `git clean -fdq`)
   и гоняет doctor-инварианты.
2. Runner открывает Claude-сессию (cwd = репо) на ДЕФОЛТНОМ транспорте SDK
   (без `_internal`): sandbox-настройки из `.claude/settings.stanok.json`,
   только Read/Write/Edit/Grep/Glob/Agent, Bash запрещён, хуки на каждом
   Write/Edit. can_use_tool: SAFE-авто-allow, CRITICAL → Telegram (DecisionProvider).
3. Модель (coder) пишет тест → реализацию → документацию, спавнит
   sub-агентов `tester`/`reviewer`. После каждого Write/Edit хуки сканируют
   код (malware-scan) и проверяют «код ↔ тест» (verifier). Job/Attempt:
   попытка → verify → локальные ретраи (STANOK_LOCAL_RETRIES=1) → cloud FAIL-only
   (по умолчанию облако ПОДАВЛЕНО; явный `--cloud` включает внешний reviewer).
4. Финал: `VERIFIER: PASS/FAIL`, `PROBE-RESULT: …`, rc Runner — typed
   `evidence/<label>/summary.json` (без regex-парсинга stdout).
