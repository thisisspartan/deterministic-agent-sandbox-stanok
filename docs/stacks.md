# Stack registry: one manifest per stack + generator (D2)

The `STACK REGISTRY` in `scripts/run.sh` is no longer a hand-edited heredoc.
It is **generated** from one TOML manifest per stack in `scripts/stacks/` by
`scripts/gen_stacks.sh`. Adding a stack = editing ONE manifest + regenerating.

## Manifest format

One file per stack: `scripts/stacks/<ext>.toml`. All keys are required. The
manifests use only strings and arrays of strings (the generator parses them
with a small fixed `sed` parser — no TOML library).

| key            | type             | meaning                                                        |
|----------------|------------------|----------------------------------------------------------------|
| `ext`          | string           | file extension (no leading dot)                                |
| `test_glob`    | string           | `find(1) -name` glob for `list` (basename match)               |
| `name_regex`   | string           | ERE for the basename; validates `test`/`smoke` args (charset)  |
| `test_runner`  | string           | command line for `test` (timeout 60, stdin `/dev/null`)         |
| `smoke_runner` | string           | command line for `smoke` (timeout 10, stdin `/dev/null`)        |
| `preflight`    | string           | runner-availability probe; non-zero exit = ENV-FAIL (rc=6)      |
| `domains`      | array of strings | network domains the stack needs in the image                   |
| `runtime`      | array of strings | runtime packages the stack needs in the image, one line each   |

Example (`scripts/stacks/js.toml`):

```toml
ext = "js"
test_glob = "*.test.js"
name_regex = "[A-Za-z0-9_-]+\\.test\\.js"
test_runner = "node --test --test-force-exit"
smoke_runner = "node"
preflight = "node --version"
domains = ["registry.npmjs.org"]
runtime = ["node v22.22.3 (nodejs.org tarball, sha256-pinned in Dockerfile)"]
```

## Generator

```
bash scripts/gen_stacks.sh          # (re)generate the artifacts
bash scripts/gen_stacks.sh --check  # verify the committed artifacts are in sync
```

With **no args** the generator reads `scripts/stacks/*.toml` (sorted by
filename) and writes three artifacts:

- `scripts/stacks.generated.sh` — a bash file whose ONLY content is the
  `STACKS='...'` assignment (one registry line per stack, in manifest sort
  order). This is the file `scripts/run.sh` sources.
- `scripts/stacks.generated/domains.json` — a JSON array: the sorted union of
  all manifests' `domains` arrays.
- `scripts/stacks.generated/runtime.list` — the `runtime` lines of all
  manifests, in manifest order, one per line.

`--check` regenerates all three into a temp dir and exits **0** iff they are
byte-identical to the committed files, **1** otherwise (printing which file
drifted). This is the verify hook the supervisor's doctor calls.

## Rule

The generated files (`scripts/stacks.generated.sh` and
`scripts/stacks.generated/*`) are **committed artifacts and must never be
edited by hand.** To add or change a stack:

1. Edit (or add) its manifest in `scripts/stacks/`.
2. Run `bash scripts/gen_stacks.sh`.
3. Commit the manifest **and** the regenerated files together.

The registry line order inside `STACKS` is behavior-irrelevant (`run.sh`
matches each argument against every line); the generator emits lines in
manifest filename sort order. Each line is byte-identical to the value in its
manifest.

## Suite mode: `test --all` (D4)

`bash scripts/run.sh test --all` runs **EVERY** test file that `list` would
print in one invocation — the same discovery (registry globs, sorted-unique)
and the same W12 unclaimed-test-like-file rule: an unclaimed file fails the
suite with rc=1 (named on stderr), exactly as it fails `list`.

- `--all` is recognized **ONLY** as the sole argument to `test`:
  `test --all` → suite run; `test --all <x>` or `test <path> --all` → rc=2
  (refused, usage on stderr).
- Each file runs with its own stack's test-runner, sequentially, with the
  same per-file timeout (60 s) and the same `=== <file> ===` header as the
  per-file `test` subcommand. A failing file does **NOT** stop the suite —
  all files run.
- Preflight: each distinct preflight command runs once before the suite
  (ENV-FAIL rc=6, same semantics as the per-file path).
- Zero test files → rc=0, no output (an empty suite passes).

| rc  | meaning                                                            |
|-----|--------------------------------------------------------------------|
| 0   | all files passed (or the suite is empty)                           |
| 1   | a test failed, or an unclaimed test-like file exists              |
| 2   | refused: `--all` is not the sole argument to `test`               |
| 6   | ENV-FAIL: a stack's runner is unavailable (preflight failed)      |
| 124 | a file hit the 60 s timeout — the suite stops at the first timeout |

The per-file `test <path>` path is **UNCHANGED** (same rc semantics, same
output); `smoke` and `list` are UNCHANGED.

## Appendix: exact file contents (for immediate creation)

> NOTE: In the current container the `scripts/` directory is mounted
> read-only at the OS level (only `scripts/run.sh` the file is writable), so
> the files below could not be created in `scripts/`. They are recorded here
> verbatim so they can be written the moment `scripts/` is writable. The
> generated artifacts (`stacks.generated.sh`, `stacks.generated/*`) are
> produced by running the generator and are not hardcoded.

### `scripts/stacks/jq.toml`

```toml
ext = "jq"
test_glob = "*.json"
name_regex = "[A-Za-z0-9_-]+\\.json"
test_runner = "jq empty"
smoke_runner = "jq empty"
preflight = "command -v jq"
domains = []
runtime = ["jq"]
```

### `scripts/stacks/js.toml`

```toml
ext = "js"
test_glob = "*.test.js"
name_regex = "[A-Za-z0-9_-]+\\.test\\.js"
test_runner = "node --test --test-force-exit"
smoke_runner = "node"
preflight = "node --version"
domains = ["registry.npmjs.org"]
runtime = ["node v22.22.3 (nodejs.org tarball, sha256-pinned in Dockerfile)"]
```

### `scripts/stacks/py.toml`

```toml
ext = "py"
test_glob = "*_test.py"
name_regex = "[A-Za-z0-9_-]+_test\\.py"
test_runner = "env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3 -m pytest -q -p no:cacheprovider -o pythonpath=src"
smoke_runner = "env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3"
preflight = "env PYTHONDONTWRITEBYTECODE=1 uv run --no-project python3 -m pytest --version"
domains = ["pypi.org", "files.pythonhosted.org"]
runtime = ["python3", "python3-venv", "uv (pinned 0.5.24)", "pytest"]
```

### `scripts/gen_stacks.sh`

```bash
#!/usr/bin/env bash
# gen_stacks.sh — generate the STACK REGISTRY artifacts from the per-stack
# TOML manifests in scripts/stacks/ (one manifest per stack).
#
#   bash scripts/gen_stacks.sh          — (re)generate:
#     scripts/stacks.generated.sh          the STACKS='...' assignment
#     scripts/stacks.generated/domains.json  sorted union of all domains
#     scripts/stacks.generated/runtime.list  runtime lines, manifest order
#   bash scripts/gen_stacks.sh --check  — regenerate into a temp dir and
#     exit 0 iff the committed artifacts are byte-identical (1 = drift,
#     printing which file drifted).
#
# Stacks are emitted in manifest filename sort order. The manifests use
# only strings and arrays of strings; they are parsed with a small fixed
# sed parser (no TOML library).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STACKS_DIR="$SCRIPT_DIR/stacks"
OUT_SH="$SCRIPT_DIR/stacks.generated.sh"
OUT_DIR="$SCRIPT_DIR/stacks.generated"

# --- tiny fixed TOML parser (strings + arrays of strings, one line each) ---
toml_str() {  # $1=file $2=key -> the string value
  sed -n "s/^${2} = \"\\(.*\\)\"$/\\1/p" "$1"
}

toml_arr() {  # $1=file $2=key -> one element per line
  local inner
  inner="$(sed -n "s/^${2} = \\[\\(.*\\)\\]$/\\1/p" "$1")"
  [ -n "$inner" ] || return 0
  printf '%s\n' "$inner" | sed 's/", "/\n/g' | sed 's/^"//; s/"$//'
}

# --- collect manifests in filename sort order ---
manifests=()
for f in "$STACKS_DIR"/*.toml; do
  [ -e "$f" ] && manifests+=("$f")
done
[ "${#manifests[@]}" -gt 0 ] || {
  echo "gen_stacks.sh: no manifests in $STACKS_DIR" >&2
  exit 2
}
mapfile -t manifests < <(printf '%s\n' "${manifests[@]}" | sort)

generate() {  # $1=out .sh path  $2=out dir
  local out_sh="$1" out_dir="$2"
  mkdir -p "$out_dir"
  local lines=() doms=() runtimes=()
  local m ext glob nre trun srun pre d r i j
  for m in "${manifests[@]}"; do
    ext="$(toml_str "$m" ext)"
    glob="$(toml_str "$m" test_glob)"
    nre="$(toml_str "$m" name_regex)"
    trun="$(toml_str "$m" test_runner)"
    srun="$(toml_str "$m" smoke_runner)"
    pre="$(toml_str "$m" preflight)"
    { [ -n "$ext" ] && [ -n "$glob" ] && [ -n "$nre" ] &&
      [ -n "$trun" ] && [ -n "$srun" ] && [ -n "$pre" ]; } || {
      echo "gen_stacks.sh: manifest $m is missing a required key" >&2
      exit 2
    }
    lines+=("${ext}|${glob}|${nre}|${trun}|${srun}|${pre}")
    while IFS= read -r d; do
      [ -n "$d" ] && doms+=("$d")
    done < <(toml_arr "$m" domains)
    while IFS= read -r r; do
      [ -n "$r" ] && runtimes+=("$r")
    done < <(toml_arr "$m" runtime)
  done
  # 1) STACKS='...' — the ONLY content of the generated .sh file
  {
    printf "STACKS='"
    for i in "${!lines[@]}"; do
      [ "$i" -gt 0 ] && printf '\n'
      printf '%s' "${lines[$i]}"
    done
    printf "'\n"
  } > "$out_sh"
  # 2) domains.json — sorted union
  local sorted=()
  if [ "${#doms[@]}" -gt 0 ]; then
    mapfile -t sorted < <(printf '%s\n' "${doms[@]}" | sort -u)
  fi
  {
    if [ "${#sorted[@]}" -eq 0 ]; then
      printf '[]\n'
    else
      printf '[\n'
      for j in "${!sorted[@]}"; do
        [ "$j" -gt 0 ] && printf ',\n'
        printf '  "%s"' "${sorted[$j]}"
      done
      printf '\n]\n'
    fi
  } > "$out_dir/domains.json"
  # 3) runtime.list — manifest order, one per line
  if [ "${#runtimes[@]}" -gt 0 ]; then
    printf '%s\n' "${runtimes[@]}" > "$out_dir/runtime.list"
  else
    : > "$out_dir/runtime.list"
  fi
}

case "${1:-}" in
  "")
    generate "$OUT_SH" "$OUT_DIR"
    ;;
  --check)
    tmp="$(mktemp -d "${TMPDIR:-/tmp}/gen_stacks.XXXXXX")"
    trap 'rm -rf "$tmp"' EXIT
    generate "$tmp/stacks.generated.sh" "$tmp/stacks.generated"
    rc=0
    for rel in "stacks.generated.sh" "stacks.generated/domains.json" \
               "stacks.generated/runtime.list"; do
      if ! cmp -s "$tmp/$rel" "$SCRIPT_DIR/$rel"; then
        echo "gen_stacks.sh: drift: $rel" >&2
        rc=1
      fi
    done
    exit "$rc"
    ;;
  *)
    echo "usage: gen_stacks.sh [--check]" >&2
    exit 2
    ;;
esac
```

### `scripts/run.sh` edit (the only other change)

Replace the inline `STACKS='...'` heredoc with:

```bash
# STACK REGISTRY — GENERATED from scripts/stacks/*.toml by
# scripts/gen_stacks.sh. Do not edit by hand; edit the manifest and run
# `bash scripts/gen_stacks.sh`.
source "$SCRIPT_DIR/stacks.generated.sh"
```

(Keeps the existing field-format comment block above it; nothing else in
`run.sh` changes.)
