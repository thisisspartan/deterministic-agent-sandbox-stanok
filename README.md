# stanok — a Claude Code machine on a local model

An autonomous "machine": takes a text ticket, solves it in a single TDD session
(monolithic — no subagents) under deterministic hooks and a bwrap sandbox,
runs `node tests/*.test.js`, and outputs the result to `evidence/<label>/summary.json`.

This is infrastructure. The project code (`src/`, `tests/`, `docs/`) and the tickets
live in the parent repo (see the README one level up). This repo is a
pluggable git submodule for any project.

## Requirements

- Python 3.12+, Node.js (test runs), claude-code (the machine binary), bubblewrap
- A local llama-server, Anthropic-compatible (`STANOK_SERVER_URL`)
- The parent repo must NOT contain a `CLAUDE.md` above this repo
  (the control-room role is set via `--append-system-prompt-file`,
  otherwise the machine auto-loads the parent CLAUDE.md — role leak)

## Setup

```bash
./setup.sh                                   # .venv + claude-agent-sdk
bash hooks/doctor.sh                         # expected: 13 ok, 0 fail
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
                                gates, Job/Attempt, typed summary.json)
launch.sh                     — thin shim: exec venv-python launcher/stanok.py
sandbox-run.sh                — bwrap sandbox: repo mounted read-only with writable
                                carve-outs (src/, tests/, docs/, evidence/,
                                .stanok-logs/);
                                .git is mounted strictly read-only (--ro-bind)
hooks/                        — verifier (PostToolUse Write|Edit: runs the
                                matching test, injects RED/GREEN), doctor,
                                commit-msg
.claude/settings.stanok.json  — the machine sandbox (allow/deny, hooks)
CLAUDE.md                     — the machine role (auto-loaded inside the repo)
setup.sh                      — environment deployment (.venv)
src/ tests/ docs/             — the machine working directories (empty at start)
```

## Configuration (all via env)

| Variable             | Default                   | What it sets                     |
|----------------------|---------------------------|----------------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`   | llama-server                     |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`         | local model                      |
| `STANOK_CLAUDE_BIN`  | `claude` (from PATH)      | claude-code binary               |
| `STANOK_PY`          | `<repo>/.venv/bin/python` | python for the Runner            |
| `STANOK_REPO`        | `<repo>/stanok`           | machine root (override)          |
| `STANOK_EVIDENCE`    | `<repo>/evidence`         | evidence dir (summary.json, logs) |
| `STANOK_LOCAL_RETRIES` | `2`                     | in-session retry turns on verifier FAIL |
| `STANOK_REQUIRED_WINDOW` | `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from settings | preflight: minimal server `n_ctx` (rc=20 if less) |
| `STANOK_SKIP_SERVER_CHECK` | unset                   | `1` — skip the preflight `/props` check entirely |

## How it works (briefly)

1. `launch.sh run` (shim → Runner) passes the fail-closed gates in this order:
   shim check-dirty (rc=22, host side) -> label-guard (rc=15) ->
   ROLE-LEAK (rc=24) -> ticket (rc=13) -> dirty-tree (rc=22, uncommitted
   changes — start forbidden) -> lock (rc=21) -> ticket header (rc=13: a
   `module:` line or `reset: none` is required — the ticket-scoped
   invariant, W2.1) -> pre-flight `/props` of the server (rc=20;
   fail-closed also when the server `n_ctx` is below the required window).
   The dirty-tree gate is fail-closed: no destructive reset/clean — the
   operator commits before launch.
2. The Runner opens ONE Claude session (cwd = repo) inside the bwrap sandbox
   (`sandbox-run.sh`): settings from `.claude/settings.stanok.json`, tools
   Read/Write/Edit/Grep/Glob/run — `run` (MCP) is the ONLY shell
   (`scripts/run.sh test|smoke|list`); Bash is denied; subagents
   (Agent/Task) are denied.
3. Monolithic TDD in a single session: the model writes the test first
   (red), then the implementation (green), then docs. After every Write/Edit
   under `tests/`: verifier.sh (PostToolUse) runs the matching test through
   `scripts/run.sh` and injects the verdict (RED CONFIRMED / GREEN) into the
   session — the TDD red phase is harness-provided, not model discipline.
4. On verifier FAIL the Runner appends an in-session retry turn
   (`--local-retries`, default 2) with the failure block.
5. Final: `verifier: PASS/FAIL`, `probe_result: CLEAN-FIRST |
   PASS-AFTER-LOCAL-RETRY | VERIFY-FAIL | EARLY-ABORT`, Runner rc — typed
   `evidence/<label>/summary.json` (no regex parsing of stdout).

## Commits

The agent does NOT commit: Bash is denied (the `run` tool is the only shell)
and `.git` is mounted read-only inside the bwrap sandbox, so git is
unreachable from inside. The operator commits (outside the sandbox) — the
dirty-tree gate (rc=22) is the checkpoint: a run starts only on a clean tree.
