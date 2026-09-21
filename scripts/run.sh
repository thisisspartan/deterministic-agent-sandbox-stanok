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
# RC TABLE (W12) — run.sh's own codes are DISJOINT from every runner's codes
# (pytest 0-5, node --test 0/1), so a caller never has to guess who produced
# the code:
#   0    pass (all tests green)
#   1    a test FAILED (runner failure; a runner that itself exits 2 or 6
#        is remapped to 1 — pytest 2 = interrupted, 6 is outside its range);
#        also: `list` found a test-like file no registry line claims
#   2    run.sh REFUSED the call: unknown subcommand, bad shape/charset,
#        unknown extension, missing file, wrong arg count
#   6    ENV-FAIL: the stack's runner is unavailable in this environment
#        (preflight probe failed) — an environment defect, NOT a red test
#   7    SECURITY: symlink in a path component, or the resolved path
#        escapes tests/ (test) or src/ (smoke)
#   124  timeout (test: 60s, smoke: 10s)
#   3,4,5  pytest's own codes, passed through unremapped: 3 = internal
#        error, 4 = usage error, 5 = no tests ran (a bare assert-script is
#        NOT a test — see CLAUDE.md "Test forms")
#
# STACK REGISTRY — the single stack extension point: exactly ONE line per
# stack, format:
#   <ext>|<test-glob>|<name-regex>|<test-runner>|<smoke-runner>|<preflight>
#   test-glob    : find(1) -name glob for `list` (basename match)
#   name-regex   : ERE for the basename; validates `test`/`smoke` args (charset)
#   test-runner  : command line for `test`  (timeout 60, stdin </dev/null)
#   smoke-runner : command line for `smoke` (timeout 10, stdin </dev/null)
#   preflight    : cheap runner-availability probe (timeout 10, stdin
#                  </dev/null); a non-zero exit is ENV-FAIL (rc=6) — the
#                  runner is missing from the environment, NOT a red test
# The test-runner, smoke-runner, find-glob and usage text are all GENERATED
# from this registry — adding a stack is one line here + its runtime in the
# Dockerfile + (if needed) its domains in settings.stanok.json.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$REPO_ROOT"

# py runner: `env PYTHONDONTWRITEBYTECODE=1 uv run --no-project pytest ...` —
# uv resolves the environment itself (host: the repo's .venv; image: the
# system python, UV_SYSTEM_PYTHON=1 + UV_PYTHON_PREFERENCE=only-system).
# --no-project keeps uv from hunting for a pyproject.toml; -p no:cacheprovider
# keeps pytest from writing .pytest_cache into the read-only repo root;
# PYTHONDONTWRITEBYTECODE=1 keeps CPython from writing __pycache__/*.pyc into
# the repo (cache artifacts must not reach the W12 `list` check or the
# contract_lock manifest — the env prefix goes through `env` because
# `timeout` cannot parse a VAR=value word itself).
STACKS='js|*.test.js|[A-Za-z0-9_-]+\.test\.js|node --test --test-force-exit|node|node --version
py|*_test.py|[A-Za-z0-9_-]+_test\.py|env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3 -m pytest -q -p no:cacheprovider -o pythonpath=src|env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3|env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3 -m pytest --version
jq|*.json|[A-Za-z0-9_-]+\.json|jq empty|jq empty|command -v jq'

# Generate the usage alternatives from the registry (single source).
stack_alts() {
  local what="$1" ext glob alts=""
  while IFS='|' read -r ext glob _ _ _ _; do
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
# resolved path does not escape the root. Exits 2 on shape/missing, 7 on
# symlink/traversal (W12: 7 is disjoint from every runner code — the old
# rc=1 collided with "a test failed").
validate_path() {
  local f="$1" root="$2"
  local p full
  [ -f "$f" ] || { echo "run.sh: no such file: $f" >&2; exit 2; }
  p="$REPO_ROOT/$f"
  while [ "${p#"$REPO_ROOT"/}" != "$p" ]; do
    [ -L "$p" ] && { echo "run.sh: Security Error: symlink in path: $p" >&2; exit 7; }
    p="$(dirname "$p")"
  done
  full="$(realpath "$f")"
  [[ "$full" == "$root/"* ]] ||
    { echo "run.sh: Security Error: path escapes $root: $f" >&2; exit 7; }
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
    declare -A PREFLIGHT=()
    for f in "$@"; do
      matched=0
      while IFS='|' read -r _ _ name_re tcmd _ pre; do
        if [[ "$f" =~ ^tests(/[^/]+)*/${name_re}$ ]]; then
          RUNNER["$f"]="$tcmd"
          PREFLIGHT["$f"]="$pre"
          matched=1
          break
        fi
      done <<< "$STACKS"
      [ "$matched" = 1 ] ||
        { echo "run.sh: only $(stack_alts test) allowed (got: $f)" >&2; exit 2; }
      # SEC-01: file exists, no symlinks, no traversal out of tests/.
      validate_path "$f" "$TESTS_ROOT"
    done
    # ENV-FAIL (rc=6): the runner must be available BEFORE any test runs —
    # a missing pytest/node is an environment failure, not a red test (the
    # CC-081 incident: `No module named pytest` returned rc=1 and the
    # machine burned a turn "fixing" the environment). Preflight each
    # distinct runner once; pytest's own rc range is 0-5, so 6 is unambiguous.
    declare -A PREFLIGHT_DONE=()
    for f in "$@"; do
      pre="${PREFLIGHT[$f]}"
      if [ -z "${PREFLIGHT_DONE[$pre]:-}" ]; then
        PREFLIGHT_DONE["$pre"]=1
        # shellcheck disable=SC2086  # registry command line, word-split on purpose
        timeout 10 $pre < /dev/null > /dev/null 2>&1 || {
          echo "run.sh: ENV-FAIL: test runner unavailable: $pre" >&2
          exit 6
        }
      fi
    done
    rc=0
    for f in "$@"; do
      echo "=== $f ==="
      # The ONE canonical test invocation for the whole machine (D3): the
      # deterministic runner flags live in the registry only — no other
      # component invokes a test runner. --test-force-exit makes a leaked
      # handle exit 0 instead of hanging to rc=124.
      # shellcheck disable=SC2086  # registry command line, word-split on purpose
      timeout 60 ${RUNNER["$f"]} "$f" < /dev/null || {
        r=$?
        # rc namespace: 2 (refused path) and 6 (ENV-FAIL) belong to run.sh. A
        # runner that itself exits 2/6 (pytest: collection error) FAILED a test.
        case "$r" in 2|6) r=1 ;; esac
        rc=$r
      }
    done
    exit "$rc"
    ;;
  smoke)
    [ $# -eq 1 ] || usage
    f="$1"
    SRC_ROOT="$(realpath "$REPO_ROOT/src")"
    while IFS='|' read -r ext _ _ _ scmd pre; do
      case "$f" in
        src/*."$ext")
          # SEC-01: file exists, no symlinks, no traversal out of src/.
          validate_path "$f" "$SRC_ROOT"
          # ENV-FAIL (rc=6): the smoke runner must be available (same
          # contract as `test` — environment failure, not a red module).
          # shellcheck disable=SC2086  # registry command line, word-split on purpose
          timeout 10 $pre < /dev/null > /dev/null 2>&1 || {
            echo "run.sh: ENV-FAIL: smoke runner unavailable: $pre" >&2
            exit 6
          }
          # shellcheck disable=SC2086  # registry command line, word-split on purpose
          exec timeout 10 $scmd "$f" < /dev/null
          ;;
      esac
    done <<< "$STACKS"
    echo "run.sh: only $(stack_alts smoke) allowed (got: $f)" >&2
    exit 2
    ;;
  list)
    [ -d tests ] || { echo "run.sh: no tests/ directory" >&2; exit 1; }
    {
      while IFS='|' read -r _ glob _ _ _ _; do
        find tests -name "$glob"
      done <<< "$STACKS"
    } | sort -u
    # W12 property 1: `list` must not be SILENT about test-like files no
    # registry line claims (the reviewer's case: a failing calc_test.go next
    # to ok_test.py — old `list` did not show it, verify_gate = PASS).
    # Rule (owner-delegated, W12): a file under tests/ is test-like when its
    # basename contains "test" (case-insensitive); fixture/data/cache
    # directories (basename "fixtures", "data" or "__pycache__") are exempt —
    # a .pyc cache artifact is not a test (w12-verify: the verifier's pytest
    # run regenerated tests/__pycache__/*.pyc and `list` went red). Any
    # unclaimed test-like file fails the listing (rc=1) so the external
    # verifier goes red, not silent.
    unclaimed="$(
      find tests -type f | while IFS= read -r f; do
        base="${f##*/}"
        dir="${f%/*}"
        [[ "${dir##*/}" == "fixtures" || "${dir##*/}" == "data" || "${dir##*/}" == "__pycache__" ]] && continue
        low="$(printf '%s' "$base" | tr 'A-Z' 'a-z')"
        case "$low" in *test*) ;; *) continue ;; esac
        claimed=0
        while IFS='|' read -r _ glob _ _ _ _; do
          [[ "$base" == $glob ]] && { claimed=1; break; }
        done <<< "$STACKS"
        [ "$claimed" = 1 ] || printf '%s\n' "$f"
      done | sort -u
    )"
    if [ -n "$unclaimed" ]; then
      echo "run.sh: unregistered test-like file(s) in tests/ (no registry line claims them):" >&2
      printf '%s\n' "$unclaimed" >&2
      exit 1
    fi
    ;;
  *)
    usage
    ;;
esac
