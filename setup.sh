#!/usr/bin/env bash
# Machine environment setup: .venv + launcher dependencies.
# Run: ./setup.sh  (from the root of the stanok repo)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

PY="${PYTHON_BIN:-python3}"

if [[ ! -x ".venv/bin/python" ]]; then
    echo "--- creating .venv ---"
    "$PY" -m venv .venv
fi

echo "--- installing dependencies ---"
.venv/bin/pip install --upgrade pip >/dev/null
.venv/bin/pip install -r requirements.txt

echo "--- commit-msg hook (the machine's TASK-ID gate) ---"
if [[ ! -L ".git/hooks/commit-msg" ]]; then
    mkdir -p .git/hooks
    ln -sf ../../hooks/commit-msg .git/hooks/commit-msg
    echo "  created .git/hooks/commit-msg -> ../../hooks/commit-msg"
else
    echo "  already installed"
fi

echo "--- SDK check ---"
.venv/bin/python -c "from claude_agent_sdk import query; print('claude-agent-sdk OK')"

echo
echo "Environment ready. Machine check:"
echo "  DOCTOR_EXPECT_NO_CLOUD=1 bash hooks/doctor.sh"
