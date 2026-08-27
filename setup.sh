#!/usr/bin/env bash
# Подготовка окружения станка: .venv + зависимости лаунчера.
# Запуск: ./setup.sh  (из корня репо stanok)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PY="${PYTHON_BIN:-python3}"

if [[ ! -x ".venv/bin/python" ]]; then
    echo "--- создаю .venv ---"
    "$PY" -m venv .venv
fi

echo "--- ставлю зависимости ---"
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo "--- commit-msg hook (TASK-ID гейт станка) ---"
if [[ ! -L ".git/hooks/commit-msg" ]]; then
    mkdir -p .git/hooks
    ln -sf ../../hooks/commit-msg .git/hooks/commit-msg
    echo "  создан .git/hooks/commit-msg -> ../../hooks/commit-msg"
else
    echo "  уже установлен"
fi

echo "--- проверка SDK ---"
.venv/bin/python -c "from claude_agent_sdk import query; print('claude-agent-sdk OK')"

echo
echo "Окружение готово. Проверка станка:"
echo "  DOCTOR_EXPECT_NO_CLOUD=1 bash hooks/doctor.sh"
