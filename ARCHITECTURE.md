# ARCHITECTURE — the one-page map of a stanok run

The call chain, the module map, and "where to change what". Operational
docs (setup, run commands, env table, triage) stay in `README.md`; the
machine's own rules are in `CLAUDE.md` (auto-loaded into the machine
session — do not move them here).

## The chain of one run

HOST (`launch.sh` -> `launcher/cli.py main()` — the gate order is the
launch-level rc contract, the namespace is `ExitCode` in `stanok.py`):

```
label guard (rc=15) -> role-leak (rc=24) -> ticket resolution (rc=13)
-> dirty-tree gate (rc=22) -> [--follow: detached self-run | sync]
-> ticket header + declared-path validation (rc=13)
-> server /props preflight (rc=20)
-> run_sandboxed -> sandbox.sandbox_argv -> docker run
```

The image preflight is NOT on this path (doctor-only, CC-106).

CONTAINER (the same `cli.main` re-runs inside the image):

```
gates re-run + lock (rc=21) -> session.run_continuous_session:
  per turn: session._execute_turn (the agent via the SDK)
  -> verify._check_contract_lock (SHA256 manifest diff)
  -> verify.verify_gate: scripts/run.sh test --all
  -> on FAIL: a retry turn with the failure block (--local-retries)
```

- TDD red phase: the in-process PostToolUse hook `session._verifier_hook`.
- Circuit breaker: the loop-guard hook (N=5) -> `session._loop_trap_verdict`.

VERDICT:

```
summary.write_summary -> summary.json staged in LOG_DIR/<label>
(the container cannot write evidence/, CC-134)
-> host summary._publish_evidence: the I5 check (the container exit is
ground truth) may overwrite the verdict to INTEGRITY-FAIL
-> evidence/<label>/summary.json is read exactly once by the supervisor
(CLAUDE.supervisor.md §3)
```

`probe_result` values: `CLEAN-FIRST | PASS-AFTER-LOCAL-RETRY | VERIFY-FAIL |
EARLY-ABORT | NO-OP-PASS | ENV-FAIL | LOOP-TRAP | INTEGRITY-FAIL` — derived
by `summary.decide` (override first, then the table); pinned by
`launcher/tests_harness/test_verdict_table.py`.

## Module map — the owner of each contract

| File | Owns |
|---|---|
| `launcher/config.py` | static configuration (`Config`, `from_env`) + per-run mutable state (`RunState`) |
| `launcher/stanok.py` | the rc namespace (`ExitCode`), `SessionPlan` (the file-policy object), logging |
| `launcher/cli.py` | the gate order + launch-level rc codes; run/wait/status/stop |
| `launcher/gates.py` | fail-closed gates: root refusal, dirty tree, test config, hidden files, server preflight |
| `launcher/ticket.py` | ticket header parse, declared-path validation, workspace prep |
| `launcher/sandbox.py` | the Docker boundary: mounts/carve-outs (CC-135/136), `:ro` re-binds, resource limits |
| `launcher/session.py` | the one Claude session: turns, TDD hook, retry prompt, loop-guard |
| `launcher/verify.py` | contract lock + test execution via `run.sh` (rc mapping, timeouts) |
| `launcher/summary.py` | the summary.json schema (`decide`/`_status_fields`), evidence publishing, rotation |
| `launcher/opik.py` | trace-count check (telemetry only) |
| `scripts/run.sh` + `scripts/stacks/*.toml` | the run.sh contract + the stack registry (single source) |
| `CLAUDE.md` | the machine role (auto-loaded in the machine session) |
| `../CLAUDE.supervisor.md` | the supervisor protocol: verdict reading, stop conditions |

## Coupling: explicit Config, no facade (C, landed 2026-10-08)

**Decision (operator, 2026-10-08): C accepted and landed.** The hub globals
(`stanok.REPO_ROOT`, `stanok.LOG_DIR`, timeouts) and the PEP 562 facade are
gone. Static configuration is `config.Config` (frozen dataclass, `from_env`
replicates the former hub env logic), built once in `cli.main` and passed
explicitly to every gate/verify/session/summary function — a function's
dependencies are visible in its signature. Per-run mutable state is
`config.RunState` (evidence_dir/live_dir/marker_path), threaded through the
call chain. The hub keeps only what is genuinely global: the rc namespace
(`ExitCode`), `SessionPlan`, and the logging sink (a per-run file handle
opened by `cli.cmd_run`, not configuration). Tests construct
`Config(repo_root=..., log_dir=...)` directly instead of patching hub
globals. Acceptance criterion met: the harness is green (235 passed /
2 skipped) with the old names deleted from the hub — a missed reference
failed loudly on the first run and was fixed.

## Supply chain: uv.lock + digest inputs (landed 2026-10-08, modernization batch 2)

**Decision (operator):** the image's package set is pinned by `uv.lock` —
generated with `uv pip compile --python-version 3.11 --python-platform linux
--generate-hashes` from the two direct pins (claude-agent-sdk, pytest); the
Dockerfile installs `uv pip install --no-binary claude-agent-sdk -r
/opt/uv.lock` (sdist as before — the wheel bundles a second CLI). The
`ARG CLAUDE_AGENT_SDK_VERSION` is gone: the lock is the pin. `uv.lock` is a
digest input: `gates.DIGEST_INPUTS` is the single declared list and setup.sh's
`cat` line must match it — `test_image_digest_inputs.py` pins the list, the
order, and that `_image_digest` follows them. The base image is pinned by
manifest-list digest (`FROM debian:bookworm-slim@sha256:…`, the same W7
pattern as the uv COPY).

## Where to change what

- A new rc or gate -> `cli.py main()` (the order) + `stanok.py ExitCode`
  (the namespace) + this table.
- A new test stack -> `scripts/stacks/*.toml` only (run.sh and the
  launcher derive from it at runtime).
- Editing any digest input (`Dockerfile`, `scripts/run.sh`,
  `scripts/stacks/*.toml`, `uv.lock` — `gates.DIGEST_INPUTS`) changes the
  image digest (`stanok.digest` = sha256 over that list) — doctor's
  `test_docker_image_digest_matches` fails until the image is rebuilt
  (CC-106: a stale image is a doctor failure, never a mid-run ENV-FAIL).
- A new summary.json outcome -> `summary.py decide`/`_status_fields`;
  `test_verdict_table.py` must pass unchanged.
- Agent behavior / retry semantics -> `session.py`.
- Mount or boundary rule -> `sandbox.py` + `ticket.py` path validation
  (the same rule derives both — CC-135).
