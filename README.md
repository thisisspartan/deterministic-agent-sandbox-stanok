# stanok — a Claude Code machine on a local model

An autonomous "machine": takes a text ticket, solves it in a single TDD session
(monolithic — no subagents) under deterministic hooks and a Docker container
boundary (with the claude-code native bwrap sandbox running inside it),
runs tests through the project's own `scripts/run.sh`, and outputs the result
to `evidence/<label>/summary.json`.

This is infrastructure. The project code (`src/`, `tests/`, `docs/`) and the tickets
live in the parent repo (see the README one level up). This repo is a
pluggable git submodule for any project.

## Requirements

- Docker (the machine boundary; the image bakes in Node.js + Claude Code
  CLI 2.1.88 — hermetic, no host bind-mounts), whatever runtime the
  project's `scripts/run.sh` uses
- A local llama-server, Anthropic-compatible (`STANOK_SERVER_URL`)
- The parent repo must NOT contain a `CLAUDE.md` above this repo
  (the control-room role is set via `--append-system-prompt-file`,
  otherwise the machine auto-loads the parent CLAUDE.md — role leak)

## Setup

```bash
./setup.sh                                   # .venv + claude-agent-sdk + CLI staging + docker image build
bash hooks/doctor.sh                         # all doctor checks must pass (pytest)
uv run --directory . pytest launcher/tests_harness --collect-only -q | tail -1  # check count
```

## Running

```bash
./launch.sh run <ticket.md> <label> [--follow] [--direct] [--local-retries N] [-- extra...]
# The ticket is resolved against three bases (project root -> machine root -> as given),
# so the canonical call from the project root is: `./stanok/launch.sh tickets/x.md <label>`.
# The shim cd's into the machine root (the directory containing launch.sh):
# the call works from any cwd; --follow with a nonexistent ticket fails
# immediately (rc=13) instead of spawning a dead detach.
./launch.sh status <label>      # JSON: running/dead/done/missing
./launch.sh wait <label> [--timeout N]  # block until terminal, print the status JSON (CC-140)
./launch.sh stop <label>        # interrupt the run (TERM by pid from .running)
```

- `--follow` — the SOLE background flag: detach to the background, then block
  until the run is terminal and print its status. One `run --follow` call is
  both the launch and the verdict notification the supervisor waits on
  (CC-140/BL-1). Observe a detached launch: `tail -f /tmp/stanok-logs/<label>.launch.log`
- `--direct` — headless directly, ticket path relative to the repo
- `--local-retries N` — in-session retry turns on verifier FAIL (default 2)
- `wait` / `run --follow` exit semantics: `0` on ANY terminal state (done/dead/missing —
  including a completed-but-failed run), `124` at the 45-min cap. The verdict is read
  from `evidence/<label>/summary.json`, never from the exit code (decision 2026-10-08:
  documented as the current contract, not changed; `test_wait_follow` tests this semantics).

## Triage and environment notes (verified)

- Triage order on a failed run: `evidence/<label>/summary.json` (`rc`, `verifier`,
  `failures`/`errors`) -> the rc namespace (`ExitCode` docstring in `launcher/stanok.py`,
  gate order in `launcher/cli.py main()`) -> `/tmp/stanok-logs/<label>.launch.log`
  (read it only when `summary.json` is missing — an aborted run).
- Running as root is refused by a gate (`launcher/gates.py`, exit 1) — use a regular user.
- Docker-dependent doctor tests skip with reason `docker not available` when the host
  has no Docker — expected on a laptop, not a defect.
- The `jq` stack needs `jq` on the host for the hermetic tests; without it the
  `run.sh` preflight returns ENV-FAIL (rc=6) — an environment defect, not a red test.
- In a clone without the supervisor zone (no `CONTEXT.md` / `specs/`), the tests that
  require those files skip with an explicit reason — nothing to do.
- rc=22 (dirty tree): commit or stash the changes in this repo before a launch —
  the gate is fail-closed by design.

## Structure

```
launch.sh                     — thin shim: exec venv-python launcher/stanok.py
launcher/                     — the Runner: stanok.py (hub) + functional
                                submodules cli/gates/ticket/sandbox/session/
                                verify/summary/opik + tests_harness/ (the
                                doctor checks as pytest)
hooks/doctor.sh               — thin pytest wrapper
.claude/settings.stanok.json  — the machine config (allow/deny, native
                                sandbox + allowedDomains)
Dockerfile / setup.sh         — the machine image and environment deployment
CLAUDE.md                     — the machine role (auto-loaded inside the repo)
src/ tests/ docs/ scripts/    — the machine working directories
```

The call chain, the module/ownership map, the coupling design and the
"where to change what" guide: **`ARCHITECTURE.md`**.

## Configuration (all via env)

| Variable             | Default                   | What it sets                     |
|----------------------|---------------------------|----------------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`   | inference server                 |
| `STANOK_MODEL`       | `qwen3.8-flash-next-iq3_xxs` | local model                     |
| `STANOK_CLAUDE_BIN`  | `claude` (from PATH)      | claude-code binary               |
| `STANOK_PY`          | `<repo>/.venv/bin/python` | python for the Runner (host-side; remapped to the image python inside the container) |
| `STANOK_REPO`        | `<repo>/stanok`           | machine root (override)          |
| `STANOK_LOG_DIR`     | `/tmp/stanok-logs`        | session logs + container-side verdict staging (published to `evidence/<label>/` by the host) |
| `STANOK_LOCAL_RETRIES` | `2`                     | in-session retry turns on verifier FAIL |
| `STANOK_REQUIRED_WINDOW` | env (`P0-launch.sh`, = `$TOK`) | preflight: minimal server `n_ctx` (rc=20 if less) |
| `STANOK_SKIP_SERVER_CHECK` | unset                   | `1` — skip the preflight `/props` check entirely |
| `STANOK_OPIK_URL`      | `http://localhost:8080` | Opik backend (trace-count check) |
| `STANOK_DOCKER_IMAGE`| `stanok-machine:latest`   | the machine image                |
| `STANOK_CONTAINER_MEM` | `4g`                    | container memory limit           |
| `STANOK_CONTAINER_PIDS`| `512`                   | container pids limit             |
| `STANOK_CONTAINER_CPUS`| `2`                     | container CPU limit              |

## How it works

The full chain (host gates -> container session -> verdict publishing), the
ownership map, the coupling design and the change guide are in
**`ARCHITECTURE.md`** — the single source for the architecture description.
In one line: the Runner passes fail-closed gates, opens ONE Claude session
in the container (the repo `:ro` plus per-ticket `:rw` carve-outs, the
pre-existing contract files re-bound `:ro`), the TDD red phase is
harness-provided by the in-process verifier hook, on verifier FAIL the
Runner appends an in-session retry turn (`--local-retries`), and the host
re-checks the container's verdict (I5) before publishing it to
`evidence/<label>/summary.json`.

## Commits

The agent does NOT commit: `.git` is mounted read-only inside the container,
so git writes fail at the filesystem layer (reads — `git log`/`blame`/`diff`
— work). The operator commits (outside the container) — the dirty-tree gate
(rc=22) is the checkpoint: a run starts only on a clean tree.
