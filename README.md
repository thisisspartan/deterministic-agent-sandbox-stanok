# stanok — a Claude Code machine on a local model

An autonomous "machine": takes a text ticket, solves it in a single TDD session
(monolithic — no subagents) under deterministic hooks and a container boundary —
a Kubernetes Job on the local k3s cluster is the ONLY runtime (CC-231 cutover;
the Docker path was removed by CC-258, closing `specs/RISK-ACCEPTANCES.md` RA-3
ahead of schedule),
runs tests through the project's own `scripts/run.sh`, and outputs the result
to `evidence/<label>/summary.json`.

This is infrastructure. The project code (`src/`, `tests/`, `docs/`) and the tickets
live in the parent repo (see the README one level up). This repo is a
pluggable git submodule for any project.

## Requirements

- k3s + `kubectl` (the default machine boundary: worker/fresh Jobs run the
  machine image, which bakes in Node.js + Claude Code CLI 2.1.88 — hermetic;
  the tree reaches the Pod as a transport copy, no host bind-mounts).
  The baked CLI is the pinned PATCHED build (`CLI_JS_SHA` in `setup.sh`): it
  reads `STANOK_TEMP` as the request temperature — the patch contract is
  documented in the parent repo's `patches/PATCHES.md`).
  k8s is the only runtime (CC-258); an explicit `STANOK_RUNTIME=docker` is
  refused with ENV-FAIL (rc=16).
  Whatever runtime the project's `scripts/run.sh` uses
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
./launch.sh run <ticket.md> <label> [--follow] [--local-retries N] [-- extra...]
# The ticket is resolved against three bases (project root -> machine root -> as given),
# so the canonical call from the project root is: `./stanok/launch.sh tickets/x.md <label>`.
# The shim cd's into the machine root (the directory containing launch.sh):
# the call works from any cwd; --follow with a nonexistent ticket fails
# immediately (rc=13) instead of spawning a dead detach.
./launch.sh status <label>      # JSON: running/dead/done/missing
./launch.sh wait <label> [--timeout N]  # block until terminal, print the status JSON (CC-140)
./launch.sh stop <label>        # interrupt the run (TERM by pid from .running)
```

- Runtime: **k8s is the only runtime** (`launcher/k8s.py`: kubectl Jobs — worker
  Job + fresh-check Job, NetworkPolicy-bounded). An explicit
  `STANOK_RUNTIME=docker` is refused with ENV-FAIL (rc=16, «docker runtime
  removed», CC-258).
- `--follow` — the SOLE background flag: detach to the background, then block
  until the run is terminal and print its status. One `run --follow` call is
  both the launch and the verdict notification the supervisor waits on
  (CC-140/BL-1). Observe a detached launch: `tail -f /tmp/stanok-logs/<label>.launch.log`
- `--local-retries N` — in-session retry turns on verifier FAIL (default 2)
- `wait` / `run --follow` exit semantics: `0` on ANY terminal state (done/dead/missing —
  including a completed-but-failed run), `124` at the 45-min cap. The verdict is read
  from `evidence/<label>/summary.json`, never from the exit code (decision 2026-10-08:
  documented as the current contract, not changed; `test_wait_follow` tests this semantics).

## Triage and environment notes (verified)

- Triage order on a failed run: `evidence/<label>/summary.json` (`rc`, `verifier`,
  `failures`/`errors`) -> the rc namespace (`ExitCode` docstring in `launcher/exitcodes.py`,
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
launcher/                     — the Runner: stanok.py (entry shell) +
                                functional modules cli/gates/ticket/zones/k8s/
                                netpol/pod_runner/session/verify/summary/opik/
                                config/exitcodes/plan/logs + tests_harness/
                                (the doctor checks as pytest)
hooks/doctor.sh               — thin pytest wrapper
.claude/settings.stanok.json  — the machine config (allow/deny tool
                                permissions; the network boundary is the
                                NetworkPolicy, not settings — CC-258)
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
| `STANOK_PY`          | `<repo>/.venv/bin/python` | python for the Runner (host-side; the Pod session uses the image python) |
| `STANOK_REPO`        | `<repo>/stanok`           | machine root (override)          |
| `STANOK_LOG_DIR`     | `/tmp/stanok-logs`        | session logs + Pod-side verdict staging (published to `evidence/<label>/` by the host) |
| `STANOK_LOCAL_RETRIES` | `2`                     | in-session retry turns on verifier FAIL |
| `STANOK_REQUIRED_WINDOW` | env (`P0-launch.sh`, = `$TOK`) | preflight: minimal server `n_ctx` (rc=20 if less) |
| `STANOK_SKIP_SERVER_CHECK` | unset                   | `1` — skip the preflight `/props` check entirely |
| `STANOK_OPIK_URL`      | `http://localhost:8080` | Opik backend (trace-count check) |
| `STANOK_RUNTIME`     | `k8s`                     | runtime switch; `docker` is refused with ENV-FAIL (rc=16) — k8s is the only runtime (CC-258) |
| `STANOK_DOCKER_IMAGE`| `stanok-machine:latest`   | the machine image (worker/fresh Jobs run it; resolved by digest via the registry) |
| `STANOK_OPIK_HOST_IP`  | `192.168.122.156`     | Opik backend published host address (netpol template, 2.4) |
| `STANOK_OPIK_BACKEND_IP` | `172.25.0.250`      | Opik backend container address, post-DNAT (netpol template, 2.4) |

Network (default k8s runtime): the worker Job is bounded by the NetworkPolicy
`k8s/networkpolicy.yaml.tmpl` — the template carries no addresses; they come
from configuration (`launcher/config.py` defaults, env overrides
`STANOK_OPIK_HOST_IP`/`STANOK_OPIK_BACKEND_IP`, MODEL_IP from
`STANOK_SERVER_URL`) and are rendered by `launcher/netpol.py`
(`python3 -m launcher.netpol`). Only the model server and the Opik backend are
reachable; the fresh-check Job runs with no network at all. Re-verified by
`infra/netpol-smoke.sh`, which renders, applies and probes exactly the rendered
manifest; the cluster is preflighted before every run (`_preflight_cluster`,
rc=16 refusal). The Docker-era bridge `stanok-net` + iptables chain STANOK-NET
(S4) belonged to the Docker path, removed with it (CC-258); its installer
scripts (`infra/stanok-net.{sh,service}`) were removed 2026-10-10 — the chain
is operator-managed host infrastructure.

**Mechanism defaults, not a deployment.** The table above describes how the
Runner resolves configuration, not any specific deployment: the inference host
and the Opik IPs come from the operator's environment (`MODEL_IP` is derived
from `STANOK_SERVER_URL` at render time); no concrete cluster address is
pinned in this repo. The supervisor layer (ticket-level retries,
stop-conditions) is described in the parent repo's `CLAUDE.supervisor.md`,
not here. External audits of this repo must fix a SHA (pin or HEAD) and check
GitHub API contents + raw files at that SHA — not HTML pages or cached
snippets of different dates.

## How it works

The full chain (host gates -> container session -> verdict publishing), the
ownership map, the coupling design and the change guide are in
**`ARCHITECTURE.md`** — the single source for the architecture description.
In one line (k8s mode): the Runner passes fail-closed gates (cluster
preflight included), transports the tracked tree (`git archive HEAD`) plus the
ticket to a worker Job via a ConfigMap, opens ONE Claude session in the Pod
working on the transported copy, the TDD red phase is harness-provided by the
in-process verifier hook, on verifier FAIL the Runner appends an in-session
retry turn (`--local-retries`); the Pod returns its evidence and a
`changes.patch`, and the host issues the final verdict — recomputing the
protected-files contract on the scratch tree (transported tree + `git apply`)
and re-running the suite in a fresh no-network Job — before publishing to
`evidence/<label>/summary.json`; the patch lands on the live tree only on a
clean verdict.

## Commits

The agent does NOT commit. The Pod has no `.git` from the host at all (the
tree is a transported copy; the Pod re-inits its own git only to produce
`changes.patch`, which the patch gate validates — a `.git` component in the
patch is refused). The operator commits (outside the machine) — the dirty-tree
gate (rc=22) is the checkpoint: a run starts only on a clean tree.
