# ARCHITECTURE — the one-page map of a stanok run

The call chain, the module map, the runner guarantees, and "where to change
what". Operational docs (setup, run commands, env table, triage) stay in
`README.md`; the machine's own rules are in `CLAUDE.md` (auto-loaded into
the machine session — do not move them here).

## Runtime (CC-231 production cutover, 2026-10-10; CC-258 removed the
Docker fallback, 2026-10-13)

**k8s is the ONLY runtime** (`specs/RISK-ACCEPTANCES.md` RA-3 executed ahead
of schedule by CC-258): the host orchestrator `launcher/k8s.py` creates
kubectl Jobs in the local k3s cluster (worker Job + fresh-check Job,
NetworkPolicy-bounded). The dispatch is inline in `cli.main()`: an
in-container or `STANOK_NO_SANDBOX` run IS the runtime/test mode and never
dispatches; a host run reaches `k8s.host_launch_k8s`, and an explicit
`STANOK_RUNTIME=docker` is refused with ENV-FAIL («docker runtime
removed», rc=16) — never silently mapped to k8s. The machine image and the
host-issued verdict pipeline are unchanged.

Transport: the tracked tree travels as `git archive HEAD | gzip | base64`
(~240KB, under the ConfigMap size guard) plus the ticket, via a ConfigMap;
the Pod works on the transported copy (no host `.git` — it re-inits git only
to produce `changes.patch`); the Pod returns evidence + patch as a
nonce-marked base64 payload; the live tree is never touched during the run.
The host applies the patch to a scratch tree for the contract recompute and
lands it on the live tree ONLY on a clean verdict AND only on the tree the
run started from (B4 guard `k8s._live_tree_drift`, review 2026-10-17: HEAD
== STANOK_START_COMMIT + porcelain clean, re-checked immediately before the
apply; drift = rc=16 ENV-FAIL, patch not applied). Echelon 1 (`:ro` file
binds) is abolished (operator decision 2026-10-10): the contract recompute is
host-side on the scratch tree, same `_tests_manifest`/`_compare_manifests`
code path. The unified launch preflight (`k8s._preflight`, rc=16) runs
before any resource is created (disk, image staleness, Opik reachability,
cluster health + manifest contract, RuntimeClass, dangling resources —
operator spec 2026-10-12); cleanup deletes only resources this run provably
created (`create`-not-`apply`, P0 2026-10-11).

## Guarantees (runner-level; moved from the hub docstring — ARCH-REVIEW C, 2026-10-08)

1. Single Continuous Session (ClaudeSDKClient): retries inside ONE session (99% KV cache) — `session.py`.
2. Strict summary.json contract (probe_result, errors) for L1 — `summary.py`.
3. Adaptive Contract Lock: adaptation for creating tests from scratch and a ban on weakening assertions — `verify.py`.
4. Cumulative Token & Cache Telemetry: exact session_hit_rate calculation — `session.py`.
5. Shielded Turn Watchdog: the turn timeout (default 1800s) is a terminal DoS circuit breaker — asyncio.shield() keeps the turn task alive past wait_for, so client.interrupt() runs cleanly and summary.json is written with the TURN-TIMEOUT code (rc=1) without the process dying on CancelledError — `session.py`.
6. Verifier-output compression: last-N raw tail, no pattern heuristics at all (REVIEW-KISS-CLI-FIRST §3.3; the last substring filter — CC-138) — `verify.py`.
7. Process cleanup: guaranteed at the runtime boundary — Job deadline + the tracked-resource cleanup in `host_launch_k8s`'s finally (deletes only resources this run created) — `cli.py`, `k8s.py`.

## The chain of one run

HOST (`launch.sh` -> `launcher/cli.py main()` -> `cli._launch_gates` — the
gate order lives in `_launch_gates`, one readable function; it is the
launch-level rc contract, the namespace is `ExitCode` in
`launcher/exitcodes.py`):

```
label guard (rc=15) -> role-leak (rc=24) -> ticket resolution (rc=13)
-> dirty-tree gate (rc=22) -> hidden-files (rc=26) -> zone-symlink (rc=13)
-> test-config (rc=27)
-> [--follow: detached self-run (the parent confirms the `.running` marker;
   the child died before it: rc=17) | sync]
-> dispatch (inline in main(), CC-258):
   host run: STANOK_RUNTIME=docker -> ENV-FAIL (rc=16, «docker runtime
     removed»); else k8s.host_launch_k8s: ticket header gate (rc=13) ->
     unified preflight (rc=16) -> image-ref resolution (not pushed to the
     registry: rc=16) -> ConfigMap (tree + ticket) -> worker Job -> payload
     (evidence + changes.patch) -> patch gate -> scratch recompute -> fresh
     Job -> publish -> live apply
   in-container child / no-sandbox test mode: lock (rc=21) -> cmd_run:
     ticket header + declared-path validation (rc=13) -> server /props
     preflight (rc=20) -> the session (B1, review 2026-10-17: the
     workspace-prep step and rc=14 are gone — the parse-time create/edit
     refusal (rc=13) already guarantees a declared create path is new)
```

- Network policy. The worker Job is bounded by the NetworkPolicy
  `k8s/networkpolicy.yaml.tmpl` (rendered by `launcher/netpol.py`; only the
  model server and the Opik backend are reachable — the E2 policy: external
  internet and host services are closed); the fresh Job runs with no network
  (the `stanok: fresh` deny-all). Enforcement is the cluster itself: the
  rendered manifest is pinned by `launcher/tests_harness/test_k8s_manifests.py`
  and probed live by `infra/netpol-smoke.sh`. In-container
  `summary.opik_traces` is the literal "disabled" (`opik.opik_traces_field`)
  — the NetworkPolicy closes the host Opik by design. (The Docker-era bridge
  `stanok-net` + `gates.network_preflight` probe was removed with the Docker
  path, CC-258.)

- Zone rule (cc217-impl incident + review, 2026-10-09): `ticket.declared_carveout`
  requires (a) NO component of a declared path (impl/test/docs/edit) to be a
  symlink — a link hands its TARGET the zone's access (`src/link ->
  launcher/`; the Docker-era bind-realpath proof
  `test_docker_bind_resolves_symlink_source` stays as the threat proof;
  SEC-01 alignment with run.sh) — and (b) the FIRST component of the RESOLVED
  repo-relative path (realpath, exact membership, not a prefix match) to be
  one of `zones.WRITABLE_ZONES` (src/tests/docs/scripts) — the only
  directories the machine may write (`Edit(launcher/**)` denied in
  settings.stanok.json). An existing out-of-zone dir (`launcher/`) made an
  absent path declarable through the ancestor rule and the machine discovered
  mid-run that the write is physically impossible. Refusal is at header parse
  (rc=13), before any cluster call. The zone rule does not weaken CC-206
  (`edit:` on a pre-existing protected file stays refused). Tests:
  `launcher/tests_harness/test_ticket_zone.py`.

- Zone-symlink ban (cc217 review follow-up, operator decision 2026-10-09):
  in the writable zones (src/tests/docs/scripts) symlinks do not exist. ONE
  enforcement point, ONE scanner (`gates.zone_symlinks`) — S3
  (PLAN-SIMPLIFY-2026-10-09) removed the post-turn scan, the launch ban
  remains:
  1. LAUNCH — `gates.zone_symlink_gate` in `cli._launch_gates` after the
     hidden-files gate: any symlink in a zone — file, directory, dangling, or
     the zone directory itself — refuses the launch (rc=13) with the path list
     and the fix (replace the symlink with a regular file/directory). It
     covers UNDECLARED links (the header rule inspects only declared paths)
     and links under tests/ (the protected-file location — a link there hides
     its target from the protected-file rules). An accidental operator-side
     symlink is an operator-side fix, not a ticket defect: the error names the
     path and the action. A SCAN failure raises and maps to rc=16 (ENV-FAIL):
     a broken filesystem is not the ticket's fault. Hard links need no scan:
     a link inside one zone stays inside it; a new file anywhere else under
     tests//src/ is caught by the structural rules (T3-9/T3-10) — the former
     Docker-mount EXDEV proof (`test_docker_hardlink_across_mounts_fails`)
     was removed with the Docker path, CC-258.
  A mid-run created symlink is no longer scanned post-turn (S3): a new FILE
  under tests/ or src/ (symlinked files included — os.walk lists them) is
  caught by the structural rules (T3-9/T3-10, worker + host echelons);
  directory links and links under docs//scripts/ are not — accepted gap, the
  launch ban covers the session-start state. Tests:
  `launcher/tests_harness/test_zone_symlink_ban.py` (the two former GAP
  tests in test_ticket_zone.py are green with the ban).

IN THE POD (`launcher/pod_runner.py` reconstructs the tree from the transport,
re-inits its own git, rewrites the Opik tracing endpoint in the extracted
settings, then re-enters the same `cli.main` under STANOK_IN_CONTAINER=1):

```
gates re-run + lock (rc=21) -> session.run_continuous_session:
  per turn: session._execute_turn (the agent via the SDK)
  -> verify._check_contract_lock (SHA256 manifest diff)
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

VERDICT (Stage 3, SPEC-VERDICT-INTEGRITY-2026-10-08):

```
POD: summary.write_summary -> summary.json into the Pod's LOG_DIR/<label>
(S1, 2026-10-09: rollback of T3-4 — the worker writes where
cfg.label_paths already routes every other writer; commit_sha is captured on
the HOST by cli._capture_start_commit before any launch and passed via the
STANOK_START_COMMIT env — the Pod never reads the host git, plan 2026-10-08)
-> evidence + changes.patch return as ONE nonce-marked payload block
(pod_runner; CC-230: the host accepts exactly one nonce-matching block,
zero/two/unclosed = aborted)

HOST (k8s.host_launch_k8s, one finally): verify.contract_snapshot (pre-run,
host process MEMORY only) -> worker Job -> wait (Job completion = ground
truth) -> payload parse (no payload block = aborted run: nothing published,
status `missing`) -> verify.host_contract_check (recompute vs the snapshot
against the scratch tree = transported tree + `git apply` of the Pod's patch,
same `_compare_manifests` code path) -> k8s._fresh_job (fresh Job on the
scratch tree, T3-3; runs ONLY when the payload was retrieved AND the contract
is intact — spec §1.6) -> summary._publish_evidence (the HOST issues the
final verdict, Authority below; publishes nothing when the files are absent)
-> live-apply gates (A5+B4, review 2026-10-17): third identity re-check
(k8s.patch_identity_ok — the BYTES) + k8s._live_tree_drift (the TARGET:
HEAD == STANOK_START_COMMIT, porcelain clean; drift = rc=16 ENV-FAIL, the
patch is NOT applied, changes.patch stays in live_dir, temporary) -> patch
lands on the live tree ONLY on a clean verdict on an unchanged tree ->
tracked-resource cleanup (`create`-not-`apply`) -> marker removal

-> evidence/<label>/summary.json is read exactly once by the supervisor
(CLAUDE.supervisor.md §3)
```

`probe_result` values: `CLEAN-FIRST | PASS-AFTER-LOCAL-RETRY | VERIFY-FAIL |
EARLY-ABORT | NO-OP-PASS | ENV-FAIL | LOOP-TRAP | CONTRACT-FAIL |
FRESH-FAIL` — derived by `summary.decide` (priority, operator
review 2026-10-09: non-empty `contract_lock_violations` wins over every
behavioral override — verdict integrity beats model behavior, and probe_result
is one key so the rule must be explicit, not write-order luck; then the
override; then the table); CONTRACT-FAIL is set by `verify._contract_lock_forced_fail`
in-container (first echelon, an override like NO-OP-PASS/LOOP-TRAP — without
it a contract violation reads as VERIFY-FAIL) and by the HOST recompute
(Authority below); FRESH-FAIL and the host CONTRACT-FAIL/ENV-FAIL are issued
only by `_publish_evidence` — never by the container; pinned by
`launcher/tests_harness/test_scenarios_verdict.py` (the verdict scenarios —
S6, PLAN-SIMPLIFY-2026-10-09: the publish priority CONTRACT-FAIL >
FRESH-FAIL > the worker's claims is pinned end-to-end there; the former
unit bearers `test_contract_fail_probe.py` and `test_verdict_fresh.py`
were removed in S6).

**Authority of the verdict (Stage 3, SPEC-VERDICT-INTEGRITY-2026-10-08;
closes the trust boundary opened by `b7ae392`).** The final
`rc`/`verifier`/`probe_result` are ISSUED BY THE HOST in `_publish_evidence`
(T3-5/T3-6) — never trusted from the worker's summary (spec §1.1). Two
independent host checks, both against state the worker cannot rewrite:

1. **Contract recompute (T3-1/T3-2).** `verify.contract_snapshot` snapshots
   the protected files (`_protected_files`, the one source) BEFORE the worker
   starts, kept in host process MEMORY only (a LOG_DIR file could be forged);
   `verify.host_contract_check` recomputes after the worker exits (against
   the scratch tree — transported tree + `git apply` of the Pod's patch; the
   live tree is untouched during the run).
   Non-empty violations force `verifier=FAIL` + `probe_result=CONTRACT-FAIL`
   regardless of the worker's claims — the judge is not the defendant. The
   fresh check is SKIPPED when the contract is violated (spec §1.6: a fresh
   run over a tampered tree is uninformative).
   T3-9 (structural tests/ rule, operator 2026-10-09): the comparison also
   detects after-only files — after the run the set of files under `tests/`
   must equal the snapshot plus the ticket's DECLARED test files; any other
   file is an `UNDECLARED: <path>` violation regardless of its name (the
   substitution hole: `tests/colorsys.py` shadows the stdlib a reference test
   imports, the test passes against the fake; the W12 name gate sees only
   test-like names and the fresh check re-runs the same tree — this is the
   structural half). T3-10 (operator, same day): the same hole exists on the
   import path's other side — `src/` is on sys.path (`pythonpath=src`), so a
   new `src/colorsys.py` shadows the stdlib just as well; the after-only
   scope is `tests/` + `src/`. The asymmetry is deliberate: the
   MODIFIED/DELETED half stays scoped to the protected files — existing
   `src/` files are the machine's normal implementation surface, and `src/`
   is in the snapshot (`_src_files`) only for the after-only half; it must
   NOT enter `_protected_files` (that list is the protected-file contract —
   src/ is the machine's implementation surface and must stay writable). New files
   elsewhere (a bootstrap scripts/run.sh, docs/) are ticket output. Both
   echelons share the one `_compare_manifests` with the declared context:
   worker-side `_check_contract_lock` (plan.declared_paths) and host-side
   `host_contract_check` (the ticket's declared list, threaded through
   `host_launch_k8s`). A host-issued CONTRACT-FAIL never exits rc=0:
   `_publish_evidence` writes `rc = container_rc or DEFECT` and
   `host_launch_k8s` aligns the exit rc (the T3-6 exit-equals-verdict
   principle). Pinned by `test_stage3_tests_tree.py` +
   `test_stage3_src_tree.py`.
2. **Fresh check (T3-3/T3-6).** `k8s._fresh_job`: a NEW Job on the scratch
   tree the worker Pod never touched (no model endpoint, deny-all network)
   re-runs `run.sh list` + `test --all` on the final tree. Runs only when the payload was retrieved
   AND the contract is intact. A fresh suite failure overrides the worker's
   claim: `probe_result=FRESH-FAIL`, `rc=rc_fresh`; the run's exit rc is set
   to the published verdict's rc (the process exit must not contradict the
   summary the supervisor reads). A fresh INFRASTRUCTURE failure (EXEC_ERROR
   tail) is rc=16 ENV-FAIL — not a verdict, call the human (stop-condition);
   the host-backstop TIMEOUT flows as FRESH-FAIL (run.sh self-limits per
   file, so a host overrun is a pathological tree, not an infra refusal).

Priority at publish (spec §3, S2-simplified per PLAN-SIMPLIFY-2026-10-09):
**CONTRACT-FAIL > FRESH-FAIL > the worker's claims**. The host's authority
is its two independent checks only; the worker's summary passes through
untouched when neither fires (the clean path stays byte-identical).
Sanctioned gap: a pure forgery (claims PASS while the session actually
failed) over a clean contract with a green fresh check is no longer
caught — the verdict is a statement about the TREE (suite green + tree =
declared), not about the worker's self-report. An unavailable fresh check writes an ENV-FAIL summary
(`write_env_fail_summary`, rc=16) directly into evidence/ — the verdict
cannot be PASS without the artifacts it is built from. No payload at all
(worker died before writing) publishes nothing: `status` reports `missing`
(S1). Pinned by
`test_stage3_host_snapshot.py` (T3-1), `test_stage3_host_recompute.py` (T3-2)
and `test_scenarios_verdict.py` (the forged clean summary over a tampered
tree -> CONTRACT-FAIL; fresh gating: FRESH-FAIL, fresh skipped on
CONTRACT-FAIL, a green fresh check never fabricates a PASS — S6 removed the
former unit bearers `test_stage3_fresh_wiring.py`, `test_verdict_fresh.py`
and `test_contract_fail_probe.py`; the Docker-era bearers
`test_stage3_worker_lifecycle.py` and `test_stage3_fresh_verify.py` were
removed with the Docker dispatcher, CC-258; the fresh Job manifest itself is
pinned by `test_k8s_manifests.py`).

**What PASS means (the boundary of the verdict, operator 2026-10-09).** The verdict is a
statement about the TREE, not about the correctness of the code: `verifier=PASS` means the
reference test suite is green on the final tree (`run.sh test --all` in the fresh Job)
and the tree matches the ticket's declared contract. It does NOT mean the implementation is
correct — the model may hardcode expected values or fit the implementation to the tests.
Closing that gap is the ticket's acceptance criteria (a human concern), not a mechanism the
launcher can provide. The end-to-end scenario tests (`test_scenarios_verdict.py`) assert only
the observable verdict (rc / verifier / probe_result / contract_lock_violations) and never
promise code correctness.

## Module map — the owner of each contract

| File | Owns |
|---|---|
| `launcher/config.py` | static configuration (`Config`, `from_env`) + per-run mutable state (`RunState`) |
| `launcher/stanok.py` | the entry shell ONLY (the script call sites: launch.sh, the Pod runner's session call, the background self-spawn) — owns nothing (ARCH-REVIEW C) |
| `launcher/exitcodes.py` | the rc namespace (`ExitCode` — the summary.json `rc` contract) |
| `launcher/plan.py` | `SessionPlan` (the file-policy object, the single source — I1) |
| `launcher/zones.py` | `WRITABLE_ZONES` — the single zone list (the declaration allow-list; NOT a mount set — CC-258) |
| `launcher/logs.py` | logging (`log()`; the per-run sink `_stdout_log_f` assigned by `cli.cmd_run`) |
| `launcher/cli.py` | the gate order + launch-level rc codes; run/wait/status/stop |
| `launcher/gates.py` | fail-closed gates: root refusal, dirty tree, test config, hidden files, zone-symlink ban, server preflight |
| `launcher/ticket.py` | ticket header parse, declared-path validation |
| `launcher/k8s.py` | the ONLY runtime (CC-258): kubectl Jobs (worker + fresh), ConfigMap transport (`pack_tree`/payload nonce rules), patch gate + `patch_sha256`, image provenance stamp (`image_digest` — the Pod's containerStatuses imageID, host-stamped, None when unavailable), scratch recompute, unified launch preflight (`_preflight`: disk/image/Opik/cluster/RuntimeClass/dangling, rc=16), tracked-resource cleanup (`create`-not-`apply` ownership proof) |
| `launcher/netpol.py` | NetworkPolicy template rendering (addresses from config/env, never hardcoded) |
| `launcher/pod_runner.py` | the in-Pod runner: tree reconstruction from the transport, the Pod's git base commit, the settings tracing rewrite (CC-225), the in-container session call, the evidence payload (one nonce-marked block) |
| `launcher/session.py` | the one Claude session: turns, TDD hook, retry prompt, loop-guard |
| `launcher/verify.py` | contract lock (protected files) + test execution via `run.sh` (rc mapping, timeouts); host trust boundary: `contract_snapshot`/`host_contract_check` (T3-1/T3-2) + structural tests/+src/ rule (T3-9/T3-10) |
| `launcher/summary.py` | the summary.json schema (`decide`/`_status_fields`), host-issued verdict priority + `write_env_fail_summary` (T3-5/T3-6), evidence publishing, rotation |
| `launcher/opik.py` | trace-count check (telemetry only); `opik_traces_field` — "disabled" in-container (the NetworkPolicy closes host Opik by design) |
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
script call sites invoke (launch.sh, the Pod runner's session call, the
background self-spawn via `stanok.__file__`). The transient double-instance quirk of
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
  `test_scenarios_verdict.py` must pass unchanged.
- Agent behavior / retry semantics -> `session.py`.
- Zone or boundary rule -> `zones.py` (`WRITABLE_ZONES`, the declaration
  allow-list) + `ticket.py` path validation + the `k8s/` manifests +
  `netpol.py` (CC-258: the Docker mount layer is gone; the same rule
  derives the declaration and the Pod mounts).
