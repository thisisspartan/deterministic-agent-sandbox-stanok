#!/usr/bin/env bash
# run.sh — the ONLY command available to the machine's model (Bash via bash-gate).
# The model does NOT assemble shell commands: the subcommands are fixed, the script
# validates the paths. No shell operators, no network, no git.
#
#   bash scripts/run.sh test <tests/*.test.js>...   — run the tests (single-file, one at a time)
#   bash scripts/run.sh smoke <src/*.js>            — smoke run (stdin=/dev/null, timeout 10s)
#   bash scripts/run.sh list                        — list the test files
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

usage() {
  echo "usage: run.sh {test <tests/*.test.js>... | smoke <src/*.js> | list}" >&2
  exit 2
}

cmd="${1:-}"
[ -n "$cmd" ] || usage
shift

case "$cmd" in
  test)
    [ $# -ge 1 ] || usage
    for f in "$@"; do
      case "$f" in
        tests/*.test.js) ;;
        *) echo "run.sh: only tests/*.test.js allowed (got: $f)" >&2; exit 2 ;;
      esac
      [ -f "$f" ] || { echo "run.sh: no such file: $f" >&2; exit 2; }
    done
    rc=0
    for f in "$@"; do
      echo "=== $f ==="
      node "$f" || rc=$?
    done
    exit "$rc"
    ;;
  smoke)
    [ $# -eq 1 ] || usage
    case "$1" in
      src/*.js) ;;
      *) echo "run.sh: only src/*.js allowed (got: $1)" >&2; exit 2 ;;
    esac
    [ -f "$1" ] || { echo "run.sh: no such file: $1" >&2; exit 2; }
    exec timeout 10 node "$1" < /dev/null
    ;;
  list)
    find tests -name '*.test.js' | sort
    ;;
  *)
    usage
    ;;
esac
