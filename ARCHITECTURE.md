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
| `launcher/stanok.py` | hub: constants, mutable run state, `ExitCode` (the rc namespace), `SessionPlan`, PEP 562 facade |
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

## Coupling: hub + facade + mutable globals (current design)

Modules read config and state through the hub (`stanok.REPO_ROOT`,
`stanok.LOG_DIR`, timeouts — ~50 references in `launcher/`), and the hub
exposes submodule names lazily via PEP 562 `__getattr__`, so
`import stanok` stays the single entry point. Tests patch the hub
(`monkeypatch.setattr(stanok, ...)` — ~105 sites). Consequence: a
function's dependencies are not visible in its signature, and name
resolution goes through the facade.

**Decision (operator, 2026-10-08): C accepted** — replace the hub globals
with an explicit `Config` passed from `cli.main` and remove the facade.
One pass: the old names are deleted from the hub, so a missed reference
fails loudly on the first harness run; the acceptance criterion is the
harness green. Until C lands, the facade is the documented resolution
path.

## Where to change what

- A new rc or gate -> `cli.py main()` (the order) + `stanok.py ExitCode`
  (the namespace) + this table.
- A new test stack -> `scripts/stacks/*.toml` only (run.sh and the
  launcher derive from it at runtime).
- Editing `scripts/run.sh` or `scripts/stacks/*.toml` changes the image
  digest (`stanok.digest` = sha256 of Dockerfile + those files) — doctor's
  `test_docker_image_digest_matches` fails until the image is rebuilt
  (CC-106: a stale image is a doctor failure, never a mid-run ENV-FAIL).
- A new summary.json outcome -> `summary.py decide`/`_status_fields`;
  `test_verdict_table.py` must pass unchanged.
- Agent behavior / retry semantics -> `session.py`.
- Mount or boundary rule -> `sandbox.py` + `ticket.py` path validation
  (the same rule derives both — CC-135).
