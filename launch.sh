#!/usr/bin/env bash
# Запуск станка. Тонкий shim: весь оркестратор переехал в launcher/stanok.py
# (единый Runner: run/status/stop/watch, гейты, Job/Attempt, typed summary.json).
#
# Режимы (передаются прямиком в Runner):
#   ./launch.sh <ticket> <label>                 — синхронно, вывод на экран
#   ./launch.sh <ticket> <label> --background    — детач в фон, мгновенный возврат;
#                                                  наблюдение: ./launch.sh status <label>
#                                                  или tail -f /tmp/stanok-logs/<label>.launch.log
#   ./launch.sh <ticket> <label> --direct        — путь тикета относительно РЕПО (stanok/),
#                                                  а не корня проекта
#   ./launch.sh status <label>                   — JSON-статус (running/done/interrupted/missing)
#   ./launch.sh stop <label>                     — прервать прогон (TERM по pid из .running)
#   ./launch.sh watch <label>                    — живой просмотр (events + stdout)
#
# Локальные ретраи и --no-cloud — по умолчанию самого Runner
# (STANOK_LOCAL_RETRIES=1, облако подавлено). Возвраты: 0=PASS, 1=FAIL, 15=label-guard,
# 20=preflight, 21=lock, 22=dirty-tree (незакоммиченные изменения — сначала закоммить),
# 24=ROLE-LEAK.
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
# Детерминированный cwd = корень проекта (родитель stanok/): путь тикета и
# фоновый детaч ресолвятся одинаково из любого места вызова (исправляет класс
# багов «запустили не из корня» — exit 127/13 из TUI).
cd "$DIR/.."
PY="${STANOK_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: python не найден: $PY" >&2
    echo "  Разверни окружение: $DIR/setup.sh  (создаёт .venv с claude-agent-sdk)" >&2
    exit 99
fi
exec "$PY" "$DIR/launcher/stanok.py" "$@"
