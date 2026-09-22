#!/usr/bin/env bash
# R2: thin shim — all logic (gates, background, Docker supervision) lives in
# launcher/stanok.py. The CLI surface is unchanged:
#   ./launch.sh [run] <ticket> <label> [--background] [--direct] [--local-retries N] [-- extra...]
#   ./launch.sh status <label>
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

# Pre-create the per-uid Claude tmp dir: bwrap resolves mount points via
# realpathSync and silently skips non-existent folders, so the FIRST Bash
# invocation of a session misses the /tmp/claude-<uid> bind if the dir is
# created lazily after bwrap args are formed.
mkdir -p "/tmp/claude-$(id -u)" && chmod 700 "/tmp/claude-$(id -u)"
export CLAUDE_TMPDIR="/tmp/claude-$(id -u)"

exec "$PY" "$DIR/launcher/stanok.py" "$@"
