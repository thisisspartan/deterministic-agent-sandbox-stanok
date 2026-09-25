#!/usr/bin/env bash
# R2: thin shim — all logic (gates, background, Docker supervision) lives in
# launcher/stanok.py. The CLI surface:
#   ./launch.sh [run] <ticket> <label> [--background] [--follow] [--direct] [--local-retries N] [-- extra...]
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

# Per-uid Claude tmp dir. In the CONTAINER this path is a tmpfs created by
# launcher/sandbox.py (CC-141) — a host pre-create is not visible there, and
# bwrap silently skips non-existent write paths (the old "Слой 2" EROFS on the
# FIRST Bash call). Kept host-side for the host/no-sandbox path, where the CLI
# resolves the same path itself: CLAUDE_TMPDIR is the TMPDIR the nested
# sandbox runtime exports (cli.js aG8), default /tmp/claude.
mkdir -p "/tmp/claude-$(id -u)" && chmod 700 "/tmp/claude-$(id -u)"
export CLAUDE_TMPDIR="/tmp/claude-$(id -u)"

exec "$PY" "$DIR/launcher/stanok.py" "$@"
