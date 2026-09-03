#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

# Проверяем наличие bubblewrap
if ! command -v bwrap &>/dev/null; then
    echo "ERROR: установи bubblewrap (sudo apt install bubblewrap / pacman -S bubblewrap)" >&2
    exit 1
fi

# Запуск в изолированном пространстве имен ядра Linux
exec bwrap \
  --ro-bind / / \
  --dev /dev \
  --proc /proc \
  --tmpfs /tmp \
  --tmpfs "$HOME" \
  --bind "$REPO_ROOT" "$REPO_ROOT" \
  --ro-bind "$REPO_ROOT/.git" "$REPO_ROOT/.git" \
  --setenv PATH "$PATH" \
  --setenv HOME "$HOME" \
  --unshare-pid \
  --unshare-uts \
  --die-with-parent \
  "$@"
