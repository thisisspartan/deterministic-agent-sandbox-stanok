#!/usr/bin/env bash
# run.sh — the project's test entrypoint: the ONLY interface the machine's
# model and the external verifier use to run tests (see CLAUDE.md,
# "Project entrypoint"). The model has native Bash, but this script is the
# fixed contract: the subcommands are fixed, the script validates the paths.
#
#   bash scripts/run.sh test <tests/**/<test-glob>>   — run the tests
#   bash scripts/run.sh smoke <src/*.<ext>>           — smoke run (stdin=/dev/null, timeout 10s)
#   bash scripts/run.sh list                           — list the test files (sorted, unique)
#
# STACK REGISTRY — the single stack extension point: exactly ONE line per
# stack, format:
#   <ext>|<test-glob>|<name-regex>|<test-runner>|<smoke-runner>
#   test-glob    : find(1) -name glob for `list` (basename match)
#   name-regex   : ERE for the basename; validates `test`/`smoke` args (charset)
#   test-runner  : command line for `test`  (timeout 60, stdin </dev/null)
#   smoke-runner : command line for `smoke` (timeout 10, stdin </dev/null)
# The test-runner, smoke-runner, find-glob and usage text are all GENERATED
# from this registry — adding a stack is one line here + its runtime in the
# Dockerfile + (if needed) its domains in settings.stanok.json.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

STACKS='js|*.test.js|[A-Za-z0-9_-]+\.test\.js|node --test --test-force-exit|node
py|*_test.py|[A-Za-z0-9_-]+_test\.py|python3|python3'

# Generate the usage alternatives from the registry (single source).
stack_alts() {
  local what="$1" ext glob alts=""
  while IFS='|' read -r ext glob _ _ _; do
    case "$what" in
      test) alts="${alts:+${alts} | }tests/**/${glob}" ;;
      smoke) alts="${alts:+${alts} | }src/*.${ext}" ;;
    esac
  done <<< "$STACKS"
  printf '%s' "$alts"
}

usage() {
  echo "usage: run.sh {test <$(stack_alts test)> | smoke <$(stack_alts smoke)> | list}" >&2
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
    # SEC-01: resolve each arg to its registry stack (charset), then
    # validate existence / symlinks / containment in tests/.
    declare -A RUNNER=()
    for f in "$@"; do
      matched=0
      while IFS='|' read -r _ _ name_re tcmd _; do
        if [[ "$f" =~ ^tests(/[^/]+)*/${name_re}$ ]]; then
          RUNNER["$f"]="$tcmd"
          matched=1
          break
        fi
      done <<< "$STACKS"
      [ "$matched" = 1 ] ||
        { echo "run.sh: only $(stack_alts test) allowed (got: $f)" >&2; exit 2; }
      # SEC-01: file exists, no symlinks, no traversal out of tests/.
      validate_path "$f" "$TESTS_ROOT"
    done
    rc=0
    for f in "$@"; do
      echo "=== $f ==="
      # The ONE canonical test invocation for the whole machine (D3): the
      # deterministic runner flags live in the registry only — no other
      # component invokes a test runner. --test-force-exit makes a leaked
      # handle exit 0 instead of hanging to rc=124.
      # shellcheck disable=SC2086  # registry command line, word-split on purpose
      timeout 60 ${RUNNER["$f"]} "$f" < /dev/null || rc=$?
    done
    exit "$rc"
    ;;
  smoke)
    [ $# -eq 1 ] || usage
    f="$1"
    while IFS='|' read -r ext _ _ _ scmd; do
      case "$f" in
        src/*."$ext")
          [ -f "$f" ] || { echo "run.sh: no such file: $f" >&2; exit 2; }
          # shellcheck disable=SC2086  # registry command line, word-split on purpose
          exec timeout 10 $scmd "$f" < /dev/null
          ;;
      esac
    done <<< "$STACKS"
    echo "run.sh: only $(stack_alts smoke) allowed (got: $f)" >&2
    exit 2
    ;;
  list)
    {
      while IFS='|' read -r _ glob _ _ _; do
        find tests -name "$glob"
      done <<< "$STACKS"
    } | sort -u
    ;;
  *)
    usage
    ;;
esac
