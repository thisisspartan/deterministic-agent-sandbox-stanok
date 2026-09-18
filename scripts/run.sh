#!/usr/bin/env bash
# run.sh — the project's test entrypoint: the ONLY interface the machine's
# model and the external verifier use to run tests (see CLAUDE.md,
# "Project entrypoint"). The model has native Bash, but this script is the
# fixed contract: the subcommands are fixed, the script validates the paths.
#
#   bash scripts/run.sh test <tests/*.test.js | tests/*_test.py>   — run the tests
#   bash scripts/run.sh smoke <src/*.js | src/*.py>               — smoke run (stdin=/dev/null, timeout 10s)
#   bash scripts/run.sh list                                      — list the test files
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

usage() {
  echo "usage: run.sh {test <tests/*.test.js|*_test.py> | smoke <src/*.js|src/*.py> | list}" >&2
  exit 2
}

# SEC-01: shared path validation for a path that must live inside <root>/:
# strict charset, file exists, no symlink in any path component, and the
# resolved path does not escape the root. Exits 2 on shape/missing, 1 on
# symlink/traversal.
validate_path() {
  local f="$1" root="$2"
  local p full
  [ -f "$f" ] || { echo "run.sh: no such file: $f" >&2; exit 2; }
  p="$REPO_ROOT/$f"
  while [ "${p#"$REPO_ROOT"/}" != "$p" ]; do
    [ -L "$p" ] && { echo "run.sh: Security Error: symlink in path: $p" >&2; exit 1; }
    p="$(dirname "$p")"
  done
  full="$(realpath "$f")"
  [[ "$full" == "$root/"* ]] ||
    { echo "run.sh: Security Error: path escapes $root: $f" >&2; exit 1; }
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
      if [[ "$f" =~ ^tests(/[^/]+)*/[A-Za-z0-9_-]+\.test\.js$ ]]; then
        :
      elif [[ "$f" =~ ^tests(/[^/]+)*/[A-Za-z0-9_-]+_test\.py$ ]]; then
        :
      else
        echo "run.sh: only tests/**/*.test.js or tests/**/*_test.py allowed (got: $f)" >&2
        exit 2
      fi
      # SEC-01: file exists, no symlinks, no traversal out of tests/.
      validate_path "$f" "$TESTS_ROOT"
    done
    rc=0
    for f in "$@"; do
      echo "=== $f ==="
      case "$f" in
        *.js)
          # The ONE canonical test invocation for the whole machine (D3): the
          # deterministic runner flags live here only — no other component invokes
          # node on a test. --test-force-exit makes a leaked handle exit 0 instead
          # of hanging to rc=124.
          timeout 60 node --test --test-force-exit "$f" < /dev/null || rc=$?
          ;;
        *.py)
          timeout 60 python3 "$f" < /dev/null || rc=$?
          ;;
      esac
    done
    exit "$rc"
    ;;
  smoke)
    [ $# -eq 1 ] || usage
    case "$1" in
      src/*.js) ;;
      src/*.py) ;;
      *) echo "run.sh: only src/*.js or src/*.py allowed (got: $1)" >&2; exit 2 ;;
    esac
    [ -f "$1" ] || { echo "run.sh: no such file: $1" >&2; exit 2; }
    case "$1" in
      *.js) exec timeout 10 node "$1" < /dev/null ;;
      *.py) exec timeout 10 python3 "$1" < /dev/null ;;
    esac
    ;;
  list)
    find tests -name '*.test.js' | sort
    find tests -name '*_test.py' | sort
    ;;
  *)
    usage
    ;;
esac
