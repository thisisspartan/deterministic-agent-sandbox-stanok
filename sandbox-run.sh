#!/usr/bin/env bash
set -euo pipefail

# Root of the machine repo
REPO_ROOT="${STANOK_REPO:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"

if ! command -v bwrap &>/dev/null; then
    echo "ERROR: install bubblewrap (sudo apt install bubblewrap / pacman -S bubblewrap)" >&2
    exit 1
fi

LOG_DIR="${STANOK_LOG_DIR:-/tmp/stanok-logs}"
mkdir -p "$LOG_DIR"

# 1. Build PATH, explicitly including the npm-global and .local/bin directories
RESOLVED_PATH="$PATH"
for p in "$HOME/.npm-global/bin" "$HOME/.local/bin"; do
    if [ -d "$p" ] && [[ ":$RESOLVED_PATH:" != *":$p:"* ]]; then
        RESOLVED_PATH="$p:$RESOLVED_PATH"
    fi
done

# 2. Find the claude and node binaries on the host
HOST_CLAUDE="$(command -v claude || which claude || true)"
HOST_NODE="$(command -v node || which node || true)"

if [ -n "$HOST_CLAUDE" ]; then
    CLAUDE_BIN_DIR="$(dirname "$HOST_CLAUDE")"
    if [[ ":$RESOLVED_PATH:" != *":$CLAUDE_BIN_DIR:"* ]]; then
        RESOLVED_PATH="$CLAUDE_BIN_DIR:$RESOLVED_PATH"
    fi
fi

if [ -n "$HOST_NODE" ]; then
    NODE_BIN_DIR="$(dirname "$HOST_NODE")"
    if [[ ":$RESOLVED_PATH:" != *":$NODE_BIN_DIR:"* ]]; then
        RESOLVED_PATH="$NODE_BIN_DIR:$RESOLVED_PATH"
    fi
fi

# Base sandbox mounts
BWRAP_ARGS=(
  --ro-bind / /
  --dev /dev
  --proc /proc
  --tmpfs /tmp
  --bind "$LOG_DIR" "$LOG_DIR"
  --tmpfs "$HOME"
)

# 3. Pass through all critical user directories (npm, node, local)
for dir in ".npm-global" ".local" ".nvm" ".fnm" ".asdf" ".volta"; do
  if [ -d "$HOME/$dir" ]; then
    BWRAP_ARGS+=(--ro-bind "$HOME/$dir" "$HOME/$dir")
  fi
done

# If claude or node live at a real path outside the standard directories (resolving symlinks)
for bin_file in "$HOST_CLAUDE" "$HOST_NODE"; do
  if [ -n "$bin_file" ] && [ -e "$bin_file" ]; then
    REAL_TARGET="$(readlink -f "$bin_file" || true)"
    if [ -n "$REAL_TARGET" ] && [[ "$REAL_TARGET" == "$HOME/"* ]]; then
      REAL_DIR="$(dirname "$REAL_TARGET")"
      if [ -d "$REAL_DIR" ]; then
        BWRAP_ARGS+=(--ro-bind "$REAL_DIR" "$REAL_DIR")
      fi
    fi
  fi
done

# Pass through the git config
if [ -f "$HOME/.gitconfig" ]; then
  BWRAP_ARGS+=(--ro-bind "$HOME/.gitconfig" "$HOME/.gitconfig")
fi

# Folder for Claude Code sessions and settings (must be writable)
mkdir -p "$HOME/.claude"
BWRAP_ARGS+=(--bind "$HOME/.claude" "$HOME/.claude")
if [ -f "$HOME/.claude.json" ]; then
  BWRAP_ARGS+=(--bind "$HOME/.claude.json" "$HOME/.claude.json")
fi

# 4. Pass through the supervisor's tickets from the parent directory in STRICT Read-Only mode
PARENT_DIR="$(dirname "$REPO_ROOT")"
if [ -d "$PARENT_DIR/tickets" ]; then
  BWRAP_ARGS+=(--ro-bind "$PARENT_DIR/tickets" "$PARENT_DIR/tickets")
fi

# 5. Mount the machine's working repo (read/write)
BWRAP_ARGS=(
  "${BWRAP_ARGS[@]}"
  --bind "$REPO_ROOT" "$REPO_ROOT"
  --chdir "$REPO_ROOT"
  --setenv PATH "$RESOLVED_PATH"
  --setenv HOME "$HOME"
  --setenv STANOK_REPO "$REPO_ROOT"
  --setenv STANOK_LOG_DIR "$LOG_DIR"
  --setenv STANOK_HOST_PID "$$"
  --unshare-pid
  --unshare-uts
  --die-with-parent
)

exec bwrap "${BWRAP_ARGS[@]}" "$@"
