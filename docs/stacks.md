# Stack registry: one manifest per stack + generator (D2)

The `STACK REGISTRY` in `scripts/run.sh` is no longer a hand-edited heredoc.
It is **generated** from one TOML manifest per stack in `scripts/stacks/` by
`scripts/gen_stacks.sh`. Adding a stack = editing ONE manifest + regenerating.

## Manifest format

One file per stack: `scripts/stacks/<ext>.toml`. All six keys are required.
The manifests use only strings (the generator parses them with a small fixed
`sed` parser — no TOML library).

| key            | type   | meaning                                                        |
|----------------|--------|----------------------------------------------------------------|
| `ext`          | string | file extension (no leading dot)                                |
| `test_glob`    | string | `find(1) -name` glob for `list` (basename match)               |
| `name_regex`   | string | ERE for the basename; validates `test`/`smoke` args (charset)  |
| `test_runner`  | string | command line for `test` (timeout 60, stdin `/dev/null`)         |
| `smoke_runner` | string | command line for `smoke` (timeout 10, stdin `/dev/null`)        |
| `preflight`    | string | runner-availability probe; non-zero exit = ENV-FAIL (rc=6)      |

CC-155: the former `domains`/`runtime` keys were dropped — their only consumer
was the also-dropped `stacks.generated/domains.json`/`runtime.list`, and an
unconsumed key rots silently (the `runtime` list still named `uv` after CC-152
removed it from the runner). The manifest now carries exactly what `run.sh`
needs. `settings.stanok.json` `allowedDomains` and the Dockerfile runtime are
hand-maintained and are **not** derived from these manifests.

Example (`scripts/stacks/js.toml`):

```toml
ext = "js"
test_glob = "*.test.js"
name_regex = "[A-Za-z0-9_-]+\\.test\\.js"
test_runner = "node --test --test-force-exit"
smoke_runner = "node"
preflight = "node --version"
```

## Generator

```
bash scripts/gen_stacks.sh          # (re)generate the artifacts
bash scripts/gen_stacks.sh --check  # verify the committed artifacts are in sync
```

With **no args** the generator reads `scripts/stacks/*.toml` (sorted by
filename) and writes one artifact:

- `scripts/stacks.generated.sh` — a bash file whose ONLY content is the
  `STACKS='...'` assignment (one registry line per stack, in manifest sort
  order). This is the file `scripts/run.sh` sources.

`--check` regenerates it into a temp dir and exits **0** iff it is
byte-identical to the committed file, **1** otherwise (naming the drifted
file). This is the verify hook the supervisor's doctor calls.

## Rule

`scripts/stacks.generated.sh` is a **committed artifact and must never be
edited by hand.** To add or change a stack:

1. Edit (or add) its manifest in `scripts/stacks/`.
2. Run `bash scripts/gen_stacks.sh`.
3. Commit the manifest **and** the regenerated file together.

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

## Appendix: manifest contents

> NOTE: the manifests are illustrative copies. The live files are
> `scripts/stacks/*.toml` — and `scripts/gen_stacks.sh` is the generator
> itself; it is not reproduced here (a byte-copy in docs only drifts).

### `scripts/stacks/jq.toml`

```toml
ext = "jq"
test_glob = "*.json"
name_regex = "[A-Za-z0-9_-]+\\.json"
test_runner = "jq empty"
smoke_runner = "jq empty"
preflight = "command -v jq"
```

### `scripts/stacks/js.toml`

```toml
ext = "js"
test_glob = "*.test.js"
name_regex = "[A-Za-z0-9_-]+\\.test\\.js"
test_runner = "node --test --test-force-exit"
smoke_runner = "node"
preflight = "node --version"
```

### `scripts/stacks/py.toml`

```toml
ext = "py"
test_glob = "*_test.py"
name_regex = "[A-Za-z0-9_-]+_test\\.py"
test_runner = "env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider -o pythonpath=src"
smoke_runner = "env PYTHONDONTWRITEBYTECODE=1 python3"
preflight = "env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest --version"
```

CC-152 dropped `uv run --no-project` from the py runner (`uv` stays a
host-side/doctor tool, not a runner dependency).

### `scripts/run.sh`

The registry is sourced, not inlined:

```bash
# STACK REGISTRY — GENERATED from scripts/stacks/*.toml by
# scripts/gen_stacks.sh. Do not edit by hand; edit the manifest and run
# `bash scripts/gen_stacks.sh`.
source "$SCRIPT_DIR/stacks.generated.sh"
```
