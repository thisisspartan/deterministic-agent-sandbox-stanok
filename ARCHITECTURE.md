# ARCHITECTURE — the one-page map of a stanok run

The call chain, the module map, the runner guarantees, and "where to change
what". Operational docs (setup, run commands, env table, triage) stay in
`README.md`; the machine's own rules are in `CLAUDE.md` (auto-loaded into
the machine session — do not move them here).

## Guarantees (runner-level; moved from the hub docstring — ARCH-REVIEW C, 2026-10-08)

1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache) — `session.py`.
2. Strict summary.json contract (probe_result, errors) for L1 — `summary.py`.
3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions — `verify.py`.
4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation — `session.py`.
5. Shielded Turn Watchdog: the turn timeout (default 1800s) is a terminal DoS circuit breaker — asyncio.shield() keeps the turn task alive past wait_for, so client.interrupt() runs cleanly and summary.json is written with the TURN-TIMEOUT code (rc=1) without the process dying on CancelledError — `session.py`.
6. Verifier-output compression: last-N raw tail, no pattern heuristics at all (REVIEW-KISS-CLI-FIRST §3.3; the last substring filter — CC-138) — `verify.py`.
7. Process cleanup: guaranteed at the container boundary via `docker stop -t 5` (client processes spawned with start_new_session=True are outside the host process group — the Reaper's os.killpg(0) does not reach them) — `cli.py`.

## The chain of one run

HOST (`launch.sh` -> `launcher/cli.py main()` -> `cli._launch_gates` — the
gate order lives in `_launch_gates`, one readable function; it is the
launch-level rc contract, the namespace is `ExitCode` in
`launcher/exitcodes.py`):

```
label guard (rc=15) -> role-leak (rc=24) -> ticket resolution (rc=13)
-> dirty-tree gate (rc=22) -> [--follow: detached self-run | sync]
-> ticket header + declared-path validation (rc=13)
-> server /props preflight (rc=20)
-> run_sandboxed -> sandbox.sandbox_argv -> docker run
```

The image preflight is NOT on this path (doctor-only, CC-106).

- Zone rule (cc217-impl incident + review, 2026-10-09): `ticket.declared_carveout`
  requires (a) NO component of a declared path (impl/test/docs/edit) to be a
  symlink — Docker resolves a bind source's realpath, so `src/link ->
  launcher/` would mount launcher/ rw (proven by
  `test_docker_bind_resolves_symlink_source`; SEC-01 alignment with run.sh) —
  and (b) the FIRST component of the RESOLVED repo-relative path (realpath,
  exact membership, not a prefix match) to be one of `sandbox.WRITABLE_ZONES`
  — the container mounts the repo `:ro` and derives rw carve-outs only inside
  the zones. An existing out-of-zone dir (`launcher/`) made an absent path
  declarable through the ancestor rule and the machine discovered mid-run that
  the write is physically impossible (`Edit(launcher/**)` denied in
  settings.stanok.json; Bash writes to launcher/ from the sandbox do not
  persist — per-call tmpfs makes them look successful). Refusal is at header
  parse (rc=13), before any container starts. The zone rule does not weaken
  CC-206 (`edit:` on a pre-existing protected file stays refused). Tests:
  `launcher/tests_harness/test_ticket_zone.py`.

- Zone-symlink ban (cc217 review follow-up, operator decision 2026-10-09):
  in the writable zones (src/tests/docs/scripts) symlinks do not exist. Two
  enforcement points, ONE scanner (`gates.zone_symlinks`):
  1. LAUNCH — `gates.zone_symlink_gate` in `cli._launch_gates` after the
     hidden-files gate: any symlink in a zone — file, directory, dangling, or
     the zone directory itself — refuses the launch (rc=13) with the path list
     and the fix (replace the symlink with a regular file/directory). It
     covers UNDECLARED links (the header rule inspects only declared paths)
     and links under tests/ (host_ro_paths would bind them :ro verbatim and
     Docker resolves them to their targets). An accidental operator-side
     symlink is an operator-side fix, not a ticket defect: the error names the
     path and the action. A SCAN failure raises and maps to rc=16 (ENV-FAIL):
     a broken filesystem is not the ticket's fault. Hard links need no scan:
     the base repo is :ro and each zone is a separate rw bind, so `ln()`
     across the zone boundary is EXDEV (proven by
     `test_docker_hardlink_across_mounts_fails`); a link inside one zone
     stays inside it.
  2. POST-TURN — `verify._check_zone_symlinks` from
     `session._post_turn_decision` (after `_check_contract_lock`, and the
     forced FAIL runs BEFORE `verify_gate` — the suite never executes on a
     tree already declared tampered): a symlink CREATED in a zone during the
     run is a contract_lock violation -> the existing forced-FAIL path
     (CONTRACT-FAIL, no retry). Compared against
     the session-start snapshot, NOT the ticket — a ticket never declares
     arbitrary links. Tests: `launcher/tests_harness/test_zone_symlink_ban.py`
     (the two former GAP tests in test_ticket_zone.py are green with the ban).

CONTAINER (the same `cli.main` re-runs inside the image):

```
gates re-run + lock (rc=21) -> session.run_continuous_session:
  per turn: session._execute_turn (the agent via the SDK)
  -> verify._check_contract_lock (SHA256 manifest diff)
  -> verify._check_zone_symlinks (new zone symlink -> contract_lock)
  -> verify.verify_gate: scripts/run.sh test --all
  -> on FAIL: a retry turn with the failure block (--local-retries)
```

- TDD red phase: the in-process PostToolUse hook `session._verifier_hook`.
- Circuit breaker: the loop-guard hook (N=5) -> `session._loop_trap_verdict`.
- Lock key (D2, plan 2026-10-08): `cli._lock_key` = the shared GIT COMMON DIR
  (`git rev-parse --git-common-dir`, abspath-normalized) — computed on the HOST,
  exported via `STANOK_LOCK_KEY` (the STANOK_* passthrough); the container never
  runs git. Two worktrees of one repo share the lock (second run gets rc=21);
  a missing key aborts the run — no silent md5(repo_root) fallback.

VERDICT:

```
summary.write_summary -> summary.json staged in LOG_DIR/<label>
(the container cannot write evidence/, CC-134; commit_sha is captured on the
HOST by cli._capture_start_commit before any launch and passed via the
STANOK_START_COMMIT env — the container never runs git, plan 2026-10-08)
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
| `launcher/stanok.py` | the entry shell ONLY (the three script call sites) — owns nothing (ARCH-REVIEW C) |
| `launcher/exitcodes.py` | the rc namespace (`ExitCode` — the summary.json `rc` contract) |
| `launcher/plan.py` | `SessionPlan` (the file-policy object, the single source — I1) |
| `launcher/logs.py` | logging (`log()`; the per-run sink `_stdout_log_f` assigned by `cli.cmd_run`) |
| `launcher/cli.py` | the gate order + launch-level rc codes; run/wait/status/stop |
| `launcher/gates.py` | fail-closed gates: root refusal, dirty tree, test config, hidden files, zone-symlink ban, server preflight |
| `launcher/ticket.py` | ticket header parse, declared-path validation, workspace prep |
| `launcher/sandbox.py` | the Docker boundary: mounts/carve-outs (CC-135/136), `:ro` re-binds, resource limits |
| `launcher/session.py` | the one Claude session: turns, TDD hook, retry prompt, loop-guard |
| `launcher/verify.py` | contract lock (protected files, zone symlinks) + test execution via `run.sh` (rc mapping, timeouts) |
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

**Follow-up (ARCH-REVIEW C, landed 2026-10-08): the hub is fully gutted.**
The three remaining hub contents moved to their own modules unchanged:
`ExitCode` -> `launcher/exitcodes.py`, `SessionPlan` -> `launcher/plan.py`
(the single-source-of-policy invariant I1 is untouched), `log()` + the sink
`_stdout_log_f` -> `launcher/logs.py` (still a module global by design: a
per-run handle assigned by `cli.cmd_run`, not configuration).
`launcher/stanok.py` is now the entry shell only — the one file the three
script call sites invoke (launch.sh, the container argv, the background
self-spawn via `stanok.__file__`). The transient double-instance quirk of
running the hub as a script (body executed in `__main__` AND imported as
`launcher.stanok`) is closed: the shell has no import-time side effects.
Harness green (243 passed / 2 skipped).

## Supply chain: image-requirements.lock + digest inputs (landed 2026-10-08, modernization batch 2)

**Decision (operator):** the image's package set is pinned by
`image-requirements.lock` — a requirements-format lock (pip-style, NOT uv's
TOML project lock; the name says what it is) generated with
`uv pip compile --python-version 3.11 --python-platform linux
--generate-hashes` from the two direct pins (claude-agent-sdk, pytest); the
Dockerfile installs `uv pip install --no-binary claude-agent-sdk -r
/opt/image-requirements.lock` (sdist as before — the wheel bundles a second
CLI). The `ARG CLAUDE_AGENT_SDK_VERSION` is gone: the lock is the pin.
`image-requirements.lock` is a digest input: `gates.DIGEST_INPUTS` is the
single declared list and setup.sh's `cat` line is a literal that
`test_image_digest_inputs.py` pins equal to it — the list, the order, and
that `_image_digest` follows them. The base image is pinned by manifest-list
digest (`FROM debian:bookworm-slim@sha256:…`, the same W7 pattern as the uv
COPY).

## Where to change what

- A new rc or gate -> `cli.py _launch_gates` (the order) + `exitcodes.py
  ExitCode` (the namespace) + this table.
- A new test stack -> `scripts/stacks/*.toml` only (run.sh and the
  launcher derive from it at runtime).
- Editing any digest input (`Dockerfile`, `scripts/run.sh`,
  `scripts/stacks/*.toml`, `image-requirements.lock` — `gates.DIGEST_INPUTS`) changes the
  image digest (`stanok.digest` = sha256 over that list) — doctor's
  `test_docker_image_digest_matches` fails until the image is rebuilt
  (CC-106: a stale image is a doctor failure, never a mid-run ENV-FAIL).
- A new summary.json outcome -> `summary.py decide`/`_status_fields`;
  `test_verdict_table.py` must pass unchanged.
- Agent behavior / retry semantics -> `session.py`.
- Mount or boundary rule -> `sandbox.py` + `ticket.py` path validation
  (the same rule derives both — CC-135).
