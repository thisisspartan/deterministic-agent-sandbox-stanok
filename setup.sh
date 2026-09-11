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
# git-path: works in a plain repo (.git dir) AND in a submodule (.git file ->
# .git/modules/<name>/hooks).
HOOKS_DIR="$(git rev-parse --git-path hooks)"
mkdir -p "$HOOKS_DIR"
if [[ ! -L "$HOOKS_DIR/commit-msg" ]]; then
    ln -srf "$DIR/hooks/commit-msg" "$HOOKS_DIR/commit-msg"
    echo "  created $HOOKS_DIR/commit-msg -> $DIR/hooks/commit-msg"
else
    echo "  already installed"
fi

echo "--- SDK check ---"
.venv/bin/python -c "from claude_agent_sdk import query; print('claude-agent-sdk OK')"

echo
echo "Environment ready. Machine check:"
echo "  bash hooks/doctor.sh"
