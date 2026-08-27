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
DOCTOR_EXPECT_NO_CLOUD=1 bash hooks/doctor.sh  # ожидается: 10 ok, 0 fail
```

## Запуск

```bash
./launch.sh <ticket.md> <label> [--background|--direct]
./launch.sh status <label>      # JSON: running/done/interrupted/missing
```

- `--background` — детач в фон (наблюдение: `tail -f /tmp/stanok-logs/<label>.launch.log`)
- `--direct` — headless напрямую, путь тикета относительно репо

## Структура

```
launcher/stanok-sdk-probe.py  — оркестратор (Claude Agent SDK, C1-C5)
launch.sh                     — обёртка: pre-flight /props, reset, live-рендер
live.py                       — живой форматтер probe-событий
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
| `STANOK_SERVER_URL`  | `http://192.168.8.131:8080`  | llama-server              |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`            | локальная модель          |
| `STANOK_PROXY`       | `http://192.168.8.131:8118`  | прокси для веб-тулинга    |
| `STANOK_CLAUDE_BIN`  | `claude` (из PATH)           | бинарь claude-code        |
| `STANOK_PY`          | `<repo>/.venv/bin/python`    | python для лаунчера       |
| `STANOK_LAUNCHER`    | `<repo>/launcher/…py`        | путь к оркестратору       |
| `STANOK_EVIDENCE`    | `<repo>/evidence`            | live-артефакты            |
| `STANOK_CLOUD_CREDS` | `~/.cloud-creds`             | секрет облачного reviewer |

## Как это устроено (коротко)

1. `launch.sh` сбрасывает репо в чистое состояние (`git reset --hard` +
   `git clean -fdq`), проверяет `/props` сервера и запускает оркестратор.
2. Оркестратор открывает Claude-сессию (cwd = репо) с sandbox-настройками
   из `.claude/settings.stanok.json`: только Read/Write/Edit/Grep/Glob/Agent,
   Bash запрещён, хуки на каждом Write/Edit.
3. Модель (coder) пишет тест → реализацию → документацию, спавнит
   sub-агентов `tester`/`reviewer`. После каждого Write/Edit хуки сканируют
   код (malware-scan) и проверяют «код ↔ тест» (verifier).
4. Финал: `VERIFIER: PASS/FAIL`, `REVIEW-VERDICT: CLEAN/DEFECT`, rc лаунчера —
   всё в `evidence/<label>/summary.json`.
