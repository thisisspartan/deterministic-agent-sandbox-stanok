#!/usr/bin/env bash
# R2: thin shim — all logic (gates, background, k8s supervision) lives in
# launcher/stanok.py. The CLI surface:
#   ./launch.sh [run] <ticket> <label> [--follow] [--local-retries N] [-- extra...]
#   ./launch.sh status <label>
#   ./launch.sh wait <label> [--timeout N]   # CC-140: block until terminal, print status
#   ./launch.sh stop <label>
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
export STANOK_REPO="${STANOK_REPO:-$DIR}"
cd "$DIR"

PY="${STANOK_PY:-$DIR/.venv/bin/python}"
if [ ! -x "$PY" ]; then
    echo "ERROR: python not found: $PY" >&2
    echo "  Set up the environment: $DIR/setup.sh  (creates .venv with claude-agent-sdk)" >&2
    exit 99
fi

# Per-uid Claude tmp dir (host-side). The Pod session gets its tmp root from
# pod_runner (CLAUDE_CODE_TMPDIR -> the WORK/tmp emptyDir; incidents
# cc231/cc233: cli.js builds the Bash tmp root as CLAUDE_CODE_TMPDIR ||
# "/tmp/claude-<uid>"). Host-side this is the path cli.js would resolve by
# default: CLAUDE_TMPDIR is the TMPDIR the nested sandbox runtime exports
# (cli.js aG8), default /tmp/claude.
mkdir -p "/tmp/claude-$(id -u)" && chmod 700 "/tmp/claude-$(id -u)"
export CLAUDE_TMPDIR="/tmp/claude-$(id -u)"

exec "$PY" "$DIR/launcher/stanok.py" "$@"
