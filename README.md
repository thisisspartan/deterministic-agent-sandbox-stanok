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
# `run` is optional: `./launch.sh <ticket.md> <label> ...` is equivalent.
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

## Structure

```
launcher/stanok.py            — THE single Runner (CLI run/status/wait/stop,
                                gates, background self-spawn, Job/Attempt,
                                typed summary.json)
launcher/sandbox.py           — the Docker boundary (R2, former sandbox-run.sh):
                                repo mounted read-only with per-ticket writable
                                carve-outs (T4/CC-135: derived from the declared
                                paths — an existing declared path binds itself,
                                an absent one its nearest existing ancestor dir),
                                and the pre-existing contract files (tests/**,
                                scripts/run.sh) re-bound :ro on top of a carve-out
                                dir (T4b/CC-136), so reference tests are
                                immutable at the fs layer, not only in the hook;
                                evidence/ is HOST-ONLY: read-only in the
                                container, the host publishes the verdict into it
                                (CC-134); .git read-only; cap-drop=ALL,
                                no-new-privileges, resource limits
launch.sh                     — thin shim: exec venv-python launcher/stanok.py
Dockerfile                    — the machine image (debian + toolchain +
                                uv + claude-agent-sdk + pytest + Node.js +
                                Claude Code CLI 2.1.88 + bubblewrap + socat
                                + jq)
hooks/                        — doctor (thin pytest wrapper, R5; the TDD
                                verifier is in-process in
                                launcher/stanok.py, R1)
launcher/tests_harness/       — the doctor checks as pytest (R5)
.claude/settings.stanok.json  — the machine config (allow/deny,
                                native sandbox + allowedDomains)
CLAUDE.md                     — the machine role (auto-loaded inside the repo)
setup.sh                      — environment deployment (.venv + docker image)
src/ tests/ docs/ scripts/    — the machine working directories (the zones the
                                hidden-file gate watches; T4 mounts only what
                                the ticket declares)
```

## Configuration (all via env)

| Variable             | Default                   | What it sets                     |
|----------------------|---------------------------|----------------------------------|
| `STANOK_SERVER_URL`  | `http://127.0.0.1:8080`   | llama-server                     |
| `STANOK_MODEL`       | `Qwen3.8-27B-MTP`         | local model                      |
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

## How it works (briefly)

1. `launch.sh` (thin shim → Runner) — the Runner passes the fail-closed
   gates in this order: label-guard (rc=15) -> ROLE-LEAK (rc=24) ->
   ticket (rc=13) -> dirty-tree (rc=22, uncommitted changes — start
   forbidden) -> then: `--follow` spawns a detached self-run (and blocks until
   terminal), or sync
   runs either in-process (host no-sandbox / container side — the lock
   (rc=21) is taken there) or as a supervised `docker run`
   (`launcher/sandbox.py`; the container-side Runner re-runs the gates and
   takes the lock). The image preflight (the image LABEL `stanok.digest`
   must equal sha256(Dockerfile + scripts/run.sh + scripts/stacks/*.toml —
   the STACKS registry, sorted by filename) and every stack's
   preflight command must succeed inside the image, `docker run --rm`)
   no longer blocks the launch path (CC-106) — it runs in doctor
   (`test_docker_image_digest_matches`): a stale image is a doctor failure,
   not a mid-run ENV-FAIL -> ticket header (rc=13: an `impl:`/`test:`/`docs:` line
   or `reset: none` is required — the ticket-scoped invariant, W2.1; literal
   paths are validated against the filesystem: relative, no `..`, no symlink
   out of the repo, and either existing or under an existing directory —
   T4/CC-135, the same rule that derives the container's rw carve-outs, so a
   path with no carve-out is refused before any container starts) -> pre-flight `/props` of the server (rc=20;
   fail-closed also when the server `n_ctx` is below the required window).
   The dirty-tree gate is fail-closed: no destructive reset/clean — the
   operator commits before launch.
2. The Runner opens ONE Claude session (cwd = repo) inside the Docker
   container (`launcher/sandbox.py`): the repo is `:ro` and exactly the
   declared paths are re-mounted `:rw` on top (an existing declared path binds
   itself; an absent one binds its nearest existing ancestor dir, since Docker
   creates a missing bind source as a root-owned directory — T4/CC-135), with
   the pre-existing contract files under such a dir re-bound `:ro` (a file bind
   over a dir bind wins — CC-136), so declaring a new test cannot make the
   existing ones writable; settings from `.claude/settings.stanok.json`,
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
   The contract_lock (pre-existing `tests/` + `scripts/run.sh`) is enforced
   at two points: the `:ro` file bind (the kernel refuses the write with
   EROFS — T4b/CC-136; the PreToolUse deny hook it replaced was removed by
   T5/CC-137) and the post-turn SHA256 manifest diff (the independent second
   echelon, which also catches deletion of a protected file).
4. On verifier FAIL the Runner appends an in-session retry turn
   (`--local-retries`, default 2) with the failure block.
5. Final: `verifier: PASS/FAIL`, `probe_result: CLEAN-FIRST |
   PASS-AFTER-LOCAL-RETRY | VERIFY-FAIL | EARLY-ABORT`, Runner rc — typed
   `evidence/<label>/summary.json` (no regex parsing of stdout). The
   container cannot write `evidence/` (read-only there, CC-134): it stages
   `summary.json` in `$STANOK_LOG_DIR/<label>` and the HOST publishes it into
   `evidence/<label>/` after the container exits.

## Architecture references

The security boundary, mount layout, integrity contours, the `run.sh`
contract, and the rc namespace are documented factually in:

- `specs/HANDOFF-ARCH-REVIEW.md` — component map, stack-coupling seams.
- `specs/SPEC-SESSION-PLAN-2026-09-24.md` — file-policy consumers (SessionPlan).
- `specs/REVIEW-KISS-CLI-FIRST-2026-09-24.md` — native vs hand-rolled inventory.
- `CLAUDE.supervisor.md` — verdict contract and stop conditions.

## Commits

The agent does NOT commit: `.git` is mounted read-only inside the container,
so git writes fail at the filesystem layer (reads — `git log`/`blame`/`diff`
— work). The operator commits (outside the container) — the dirty-tree gate
(rc=22) is the checkpoint: a run starts only on a clean tree.
