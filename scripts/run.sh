#!/usr/bin/env bash
# run.sh — the project's test entrypoint: the ONLY interface the machine's
# model and the external verifier use to run tests (see CLAUDE.md,
# "Project entrypoint"). The model has native Bash, but this script is the
# fixed contract: the subcommands are fixed, the script validates the paths.
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
    TESTS_ROOT="$(realpath "$REPO_ROOT/tests")"
    for f in "$@"; do
      # SEC-01: nested layout allowed (tests/<dir>/.../name.test.js), strict charset.
      [[ "$f" =~ ^tests(/[^/]+)*/[A-Za-z0-9_-]+\.test\.js$ ]] ||
        { echo "run.sh: only tests/**/*.test.js allowed (got: $f)" >&2; exit 2; }
      [ -f "$f" ] || { echo "run.sh: no such file: $f" >&2; exit 2; }
      # SEC-01: symlink protection — no path component (file or dir) may be a symlink.
      p="$REPO_ROOT/$f"
      while [ "${p#"$REPO_ROOT"/}" != "$p" ]; do
        [ -L "$p" ] && { echo "run.sh: Security Error: symlink in path: $p" >&2; exit 1; }
        p="$(dirname "$p")"
      done
      # SEC-01: resolved path must stay inside tests/ (traversal protection).
      full="$(realpath "$f")"
      [[ "$full" == "$TESTS_ROOT/"* ]] ||
        { echo "run.sh: Security Error: path escapes tests/: $f" >&2; exit 1; }
    done
    rc=0
    for f in "$@"; do
      echo "=== $f ==="
      # The ONE canonical test invocation for the whole machine (D3): the
      # deterministic runner flags live here only — no other component invokes
      # node on a test. --test-force-exit makes a leaked handle exit 0 instead
      # of hanging to rc=124.
      timeout 60 node --test --test-force-exit "$f" < /dev/null || rc=$?
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
