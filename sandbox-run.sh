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

# The native (inner) sandbox re-binds its temp dir `/tmp/claude-<uid>` read-write,
# but ONLY if it exists: the inner runtime silently SKIPS a non-existent write path,
# leaving it under its own `--ro-bind / /` (→ "read-only file system:
# /tmp/claude-<uid>/cwd-*"). `--tmpfs /tmp` above is empty, so create it here.
# (cli.js: write-allow = [".", AC()] where AC() = $CLAUDE_CODE_TMPDIR/claude-$(id -u);
#  KC_ drops allow-paths that don't exist.)
BWRAP_ARGS+=(--dir "${CLAUDE_CODE_TMPDIR:-/tmp}/claude-$(id -u)")

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

# 5. Mount the machine's working repo: READ-ONLY by default, with explicit
#    writable carve-outs for the work areas (src/, tests/, docs/, evidence/,
#    .stanok-logs/).
#    .git is READ-ONLY (SEC-01): the model cannot commit, plant hooks, or rewrite
#    git state from inside the sandbox. No git writes happen anywhere: launch.sh
#    fail-closed gates a dirty tree on the host (rc=22, via `stanok.py
#    check-dirty`) BEFORE entering the sandbox, and the in-sandbox
#    prepare_workspace() only preps the writable dirs + unfreezes tests/.
#    The carve-out directories must exist on the host before bwrap runs
#    (bwrap fails on a missing bind source).
mkdir -p "$REPO_ROOT/src" "$REPO_ROOT/tests" "$REPO_ROOT/docs" \
         "$REPO_ROOT/evidence" "$REPO_ROOT/.stanok-logs"

#    The native (inner) sandbox ro-binds over a fixed set of repo paths —
#    settings files, dotfiles, dangerous dirs. For a path that does NOT exist it
#    must CREATE the mountpoint, which bwrap cannot do on our read-only repo bind
#    ("Can't create file ...: Read-only file system"). Pre-create them so the
#    inner runtime binds in place. Create-if-MISSING only: an existing file is
#    never truncated. The files are .gitignore'd so they don't trip the
#    dirty-tree gate (rc=22).
for f in .gitconfig .gitmodules .bashrc .bash_profile .zshrc .zprofile .profile .ripgreprc; do
    [ -e "$REPO_ROOT/$f" ] || : > "$REPO_ROOT/$f"
done
# JSON targets must hold valid JSON ('{}'), not be empty: an empty file is a
# parse error and "silently disables ALL settings from that file".
for f in .mcp.json .claude/settings.json .claude/settings.local.json; do
    [ -e "$REPO_ROOT/$f" ] || printf '{}\n' > "$REPO_ROOT/$f"
done
# Empty dirs are invisible to git — no .gitignore entry needed.
mkdir -p "$REPO_ROOT/.vscode" "$REPO_ROOT/.idea" \
         "$REPO_ROOT/.claude/skills" "$REPO_ROOT/.claude/commands" "$REPO_ROOT/.claude/agents" \
         "$REPO_ROOT/.claude/.git"

BWRAP_ARGS=(
  "${BWRAP_ARGS[@]}"
  --ro-bind "$REPO_ROOT" "$REPO_ROOT"
  --ro-bind "$REPO_ROOT/.claude" "$REPO_ROOT/.claude"
  --ro-bind "$REPO_ROOT/hooks" "$REPO_ROOT/hooks"
  --bind "$REPO_ROOT/src" "$REPO_ROOT/src"
  --bind "$REPO_ROOT/tests" "$REPO_ROOT/tests"
  --bind "$REPO_ROOT/docs" "$REPO_ROOT/docs"
  --bind "$REPO_ROOT/evidence" "$REPO_ROOT/evidence"
  --bind "$REPO_ROOT/.stanok-logs" "$REPO_ROOT/.stanok-logs"
  --ro-bind "$REPO_ROOT/.git" "$REPO_ROOT/.git"
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
