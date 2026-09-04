# stanok — a Claude Code machine on a local model

An autonomous "machine": takes a text ticket, solves it with a TDD cycle
(coder → tester → reviewer) under deterministic hooks, runs
`node tests/*.test.js`, and outputs the result to `evidence/<label>/summary.json`.

This is infrastructure. The project code (`src/`, `tests/`, `docs/`) and the tickets
live in the parent repo (see the README one level up). This repo is a
pluggable git submodule for any project.

## Requirements

- Python 3.12+, Node.js (test runs), claude-code (the machine binary)
- A local llama-server, Anthropic-compatible (`STANOK_SERVER_URL`)
- The parent repo must NOT contain a `CLAUDE.md` above this repo
  (the control-room role is set via `--append-system-prompt-file`,
  otherwise the machine auto-loads the parent CLAUDE.md — role leak)

## Setup

```bash
./setup.sh                                   # .venv + claude-agent-sdk
DOCTOR_EXPECT_NO_CLOUD=1 bash hooks/doctor.sh  # expected: 12 ok, 0 fail
```

## Running

```bash
./launch.sh run <ticket.md> <label> [--background|--direct]
# `run` is optional: `./launch.sh <ticket.md> <label> [--background|--direct]` is equivalent.
# The ticket is resolved against three bases (project root -> machine root -> as given),
# so the canonical call from the project root is: `./stanok/launch.sh tickets/x.md <label>`.
# The shim cd's into the project root itself: the call works from any cwd; --background with
# a nonexistent ticket fails immediately (rc=13) instead of spawning a dead detach.
./launch.sh status <label>      # JSON: running/done/interrupted/missing
./launch.sh stop <label>        # interrupt the run (TERM by pid from .running)
./launch.sh watch <label>       # live view of events.jsonl + stdout
```

- `--background` — detach to the background (observe: `tail -f /tmp/stanok-logs/<label>.launch.log`)
- `--direct` — headless directly, ticket path relative to the repo

## Structure

```
launcher/stanok.py            — THE single Runner (CLI run/status/stop/watch,
                                gates, Job/Attempt, typed summary.json)
launch.sh                     — thin shim: exec venv-python launcher/stanok.py
hooks/                        — deterministic gates (path-guard,
                                test-lock, malware-scan, verifier, …)
.claude/agents/               — coder/reviewer/tester roles
.claude/settings.stanok.json  — the machine sandbox (allow/deny, hooks)
CLAUDE.md                     — the machine role (auto-loaded inside the repo)
setup.sh                      — environment deployment (.venv)
src/ tests/ docs/             — the machine working directories (empty at start)
```

## Configuration (all via env)

| Variable           | Default                       | What it sets                |
|--------------------|-------------------------------|-----------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`  | llama-server              |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`            | local model          |
| `STANOK_PROXY`       | `http://127.0.0.1:8118`  | proxy for web tooling    |
| `STANOK_CLAUDE_BIN`  | `claude` (from PATH)           | claude-code binary        |
| `STANOK_PY`          | `<repo>/.venv/bin/python`    | python for the Runner         |
| `STANOK_REPO`        | `<repo>/stanok`              | machine root (override)|
| `STANOK_EVIDENCE`    | live dir (`/tmp/stanok-logs`) | malware-scan flags        |
| `STANOK_CLOUD_CREDS` | `~/.cloud-creds`             | cloud reviewer secret |

## How it works (briefly)

1. `launch.sh run` (shim → Runner) passes the fail-closed gates: ROLE-LEAK
   (rc=24), lock (rc=21), dirty-tree (rc=22, uncommitted changes — start
   forbidden), pre-flight `/props` of the server (rc=20). Only on a clean tree
   it resets the repo to a clean state (`git reset --hard` + `git clean -fdq`)
   and runs the doctor invariants.
2. The Runner opens a Claude session (cwd = repo) on the DEFAULT SDK transport
   (no `_internal`): sandbox settings from `.claude/settings.stanok.json`,
   only Read/Write/Edit/Grep/Glob/Agent, Bash forbidden, hooks on every
   Write/Edit. can_use_tool: SAFE auto-allow, CRITICAL → Telegram (DecisionProvider).
3. The model (coder) writes test → implementation → documentation, spawns
   `tester`/`reviewer` subagents. After each Write/Edit the hooks scan the
   code (malware-scan) and check "code ↔ test" (verifier). Job/Attempt:
   attempt → verify → local retries (STANOK_LOCAL_RETRIES=1) → cloud FAIL-only
   (by default the cloud is SUPPRESSED; explicit `--cloud` enables the external reviewer).
4. Final: `VERIFIER: PASS/FAIL`, `PROBE-RESULT: …`, Runner rc — typed
   `evidence/<label>/summary.json` (no regex parsing of stdout).
