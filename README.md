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
./launch.sh run <ticket.md> <label> [--background|--direct] [--local-retries N] [-- extra...]
# `run` is optional: `./launch.sh <ticket.md> <label> ...` is equivalent.
# The ticket is resolved against three bases (project root -> machine root -> as given),
# so the canonical call from the project root is: `./stanok/launch.sh tickets/x.md <label>`.
# The shim cd's into the project root itself: the call works from any cwd; --background with
# a nonexistent ticket fails immediately (rc=13) instead of spawning a dead detach.
./launch.sh status <label>      # JSON: running/done/interrupted/missing
./launch.sh stop <label>        # interrupt the run (TERM by pid from .running)
```

- `--background` — detach to the background (observe: `tail -f /tmp/stanok-logs/<label>.launch.log`)
- `--direct` — headless directly, ticket path relative to the repo
- `--local-retries N` — in-session retry turns on verifier FAIL (default 2)

## Structure

```
launcher/stanok.py            — THE single Runner (CLI run/status/stop,
                                gates, background self-spawn, Job/Attempt,
                                typed summary.json)
launcher/sandbox.py           — the Docker boundary (R2, former sandbox-run.sh):
                                repo mounted read-only with writable carve-outs
                                (src/, tests/, docs/, scripts/, evidence/);
                                .git read-only; cap-drop=ALL, no-new-privileges,
                                resource limits
launch.sh                     — thin shim: exec venv-python launcher/stanok.py
Dockerfile                    — the machine image (debian + toolchain +
                                uv + claude-agent-sdk + pytest + Node.js +
                                Claude Code CLI 2.1.88 + bubblewrap + socat)
hooks/                        — doctor (thin pytest wrapper, R5),
                                commit-msg (the TDD verifier is
                                in-process in launcher/stanok.py, R1)
launcher/tests_harness/       — the doctor checks as pytest (R5)
.claude/settings.stanok.json  — the machine config (allow/deny,
                                native sandbox + allowedDomains)
CLAUDE.md                     — the machine role (auto-loaded inside the repo)
setup.sh                      — environment deployment (.venv + docker image)
src/ tests/ docs/ scripts/    — the machine working directories (empty at start)
```

## Configuration (all via env)

| Variable             | Default                   | What it sets                     |
|----------------------|---------------------------|----------------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`   | llama-server                     |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`         | local model                      |
| `STANOK_CLAUDE_BIN`  | `claude` (from PATH)      | claude-code binary               |
| `STANOK_PY`          | `<repo>/.venv/bin/python` | python for the Runner (host-side; remapped to the image python inside the container) |
| `STANOK_REPO`        | `<repo>/stanok`           | machine root (override)          |
| `STANOK_EVIDENCE`    | `<repo>/evidence`         | evidence dir (summary.json, logs) |
| `STANOK_LOCAL_RETRIES` | `2`                     | in-session retry turns on verifier FAIL |
| `STANOK_REQUIRED_WINDOW` | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from settings | preflight: minimal server `n_ctx` (rc=20 if less) |
| `STANOK_SKIP_SERVER_CHECK` | unset                   | `1` — skip the preflight `/props` check entirely |
| `STANOK_OPIK_URL`      | `http://localhost:8080` | Opik backend (trace-count check) |
| `STANOK_DOCKER_IMAGE`| `stanok-machine:latest`   | the machine image                |
| `STANOK_CONTAINER_MEM` | `4g`                    | container memory limit           |
| `STANOK_CONTAINER_PIDS`| `512`                   | container pids limit             |
| `STANOK_CONTAINER_CPUS`| `2`                     | container CPU limit              |

## How it works (briefly)

1. `launch.sh` (thin shim → Runner) — the Runner passes the fail-closed
   gates in this order: label-guard (rc=15) -> ROLE-LEAK (rc=24) ->
   ticket (rc=13) -> dirty-tree (rc=22, uncommitted changes — start
   forbidden) -> then: `--background` spawns a detached self-run, or sync
   runs either in-process (host no-sandbox / container side — the lock
   (rc=21) is taken there) or as a supervised `docker run`
   (`launcher/sandbox.py`; the container-side Runner re-runs the gates and
   takes the lock). Before the `docker run`: the image preflight (rc=25) —
   the image LABEL `stanok.digest` must equal sha256(Dockerfile +
   scripts/run.sh) and every stack's preflight command must succeed inside
   the image (`docker run --rm`); a stale image is a 1-second launch
   failure, not a mid-run ENV-FAIL -> ticket header (rc=13: an `impl:`/`test:`/`docs:` line
   or `reset: none` is required — the ticket-scoped invariant, W2.1; literal
   paths are validated: relative, no `..`, top-level dir inside
   src/tests/docs/scripts) -> pre-flight `/props` of the server (rc=20;
   fail-closed also when the server `n_ctx` is below the required window).
   The dirty-tree gate is fail-closed: no destructive reset/clean — the
   operator commits before launch.
2. The Runner opens ONE Claude session (cwd = repo) inside the Docker
   container (`launcher/sandbox.py`): settings from `.claude/settings.stanok.json`,
   tools Read/Write/Edit/Grep/Glob/Bash — Bash is native and UNRESTRICTED;
   the boundary is the container (cap-drop=ALL, no-new-privileges,
   resource limits) plus the claude-code native sandbox (bwrap per Bash
   command, `enableWeakerNestedSandbox`, network restricted to
   `allowedDomains`); subagents (Agent/Task) are denied.
3. Monolithic TDD in a single session: the model writes the test first
   (red), then the implementation (green), then docs. After every Write/Edit
   under `tests/`: the in-process PostToolUse hook (launcher/stanok.py,
   SDK `hooks` option — no shell command) runs the matching test through
   `scripts/run.sh` and injects the verdict (RED CONFIRMED) into the
   session — the TDD red phase is harness-provided, not model discipline.
4. On verifier FAIL the Runner appends an in-session retry turn
   (`--local-retries`, default 2) with the failure block.
5. Final: `verifier: PASS/FAIL`, `probe_result: CLEAN-FIRST |
   PASS-AFTER-LOCAL-RETRY | VERIFY-FAIL | EARLY-ABORT`, Runner rc — typed
   `evidence/<label>/summary.json` (no regex parsing of stdout).

## Commits

The agent does NOT commit: `.git` is mounted read-only inside the container,
so git writes fail at the filesystem layer (reads — `git log`/`blame`/`diff`
— work). The operator commits (outside the container) — the dirty-tree gate
(rc=22) is the checkpoint: a run starts only on a clean tree.
