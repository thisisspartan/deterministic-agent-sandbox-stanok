#!/usr/bin/env bash
# Machine environment setup: .venv (host-side gate python) + launcher
# dependencies + the Docker machine image.
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

echo "--- staging the Claude Code CLI into the build context (R4) ---"
# The Dockerfile COPYs .build-context/claude-code-2.1.88/ — the CLI checkout
# lives OUTSIDE the build context ($DIR), so stage only the two essential
# files (cli.js + package.json; no .git/source/vendor/maps) here first.
CLI_SRC="${STANOK_CLI_DIR:-/home/hermes/git/claude-code-2.1.88}"
if [[ ! -f "$CLI_SRC/cli.js" || ! -f "$CLI_SRC/package.json" ]]; then
    echo "ERROR: CLI staging source not found: $CLI_SRC (need cli.js + package.json)" >&2
    echo "  Set STANOK_CLI_DIR to the validated claude-code 2.1.88 checkout." >&2
    exit 1
fi
mkdir -p "$DIR/.build-context/claude-code-2.1.88"
cp -f "$CLI_SRC/cli.js" "$CLI_SRC/package.json" "$DIR/.build-context/claude-code-2.1.88/"

echo "--- building the machine image (Docker boundary) ---"
# The .venv above is only the HOST-side python for the Runner's host-side
# gates; the run itself executes in the image (launcher/sandbox.py runs the
# image system python, which carries the SDK).
docker build -t "${STANOK_DOCKER_IMAGE:-stanok-machine:latest}" -f "$DIR/Dockerfile" "$DIR"

echo
echo "Environment ready. Machine check:"
echo "  bash hooks/doctor.sh"
