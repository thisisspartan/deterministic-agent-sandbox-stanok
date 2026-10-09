"""verify — the external verifier: run.sh invocation, output tail, contract_lock.

verify_gate / _run_suite / _tail_output (raw tail, CC-138), the protected-file
manifest and the contract_lock second echelon (W2.5/P2). The tail limits and
repo root come from the passed-in Config (C).
"""

import hashlib
import os
import subprocess
from launcher import gates, sandbox
from launcher.logs import log


# ==================================================================================
# Compression of verifier errors (_tail_output: raw last-N tail)
# ==================================================================================
def _tail_output(cfg, raw_text: str) -> str:
    """Compress verifier output for the fix prompt: keep the LAST lines (a test
    failure is reported at the tail).

    No pattern heuristics at all: neither the old JS/TAP-weighted priority
    regex (HANDOFF-ARCH-REVIEW §3 #9) nor a noise-line filter remains — a raw
    tail cannot pick the wrong window or hide a line the model needs
    (REVIEW-KISS-CLI-FIRST §3.3; the last `node_modules/` filter was the §1#1
    leftover, CC-138).
    """
    lines = raw_text.strip().splitlines()

    if len(lines) > cfg.max_test_lines:
        start = len(lines) - cfg.max_test_lines
        lines = [f"... [{start} lines skipped above] ..."] + lines[start:]
    res = "\n".join(lines)

    b_res = res.encode("utf-8")
    if len(b_res) > cfg.max_test_bytes:
        res = (
            b_res[:cfg.max_test_bytes].decode("utf-8", errors="ignore")
            + "\n... [output truncated at the byte limit] ..."
        )
    return res


def _run_suite(cfg, failures: list[tuple[str, str]], tests: list[str]) -> None:
    """D4 (CC-149): run the whole suite in ONE `test --all` call. The suite
    runs every list-discovered file sequentially with per-file timeouts and
    `=== <file> ===` headers; rc maps:
      0   -> all pass (no failures appended)
      1   -> a test failed (or unclaimed file) -> one (suite) failure w/ output
      2   -> run.sh REFUSED `--all` -> FAIL (strict contract, PLAN-HYGIENE
             2026-10-08: `test --all` support is mandatory; the pre-CC-149
             per-file fallback was removed — an entrypoint without suite mode
             is a defect, not something to work around)
      6   -> ENV-FAIL (runner unavailable) -> tagged for fail-closed rc=16
      124 -> a file hit the 60 s timeout (suite stopped) -> tagged TIMEOUT

    Per-file attribution: the combined output carries `=== <file> ===`
    headers, so the fix-prompt diff shows which file failed; the model can
    re-run `test <file>` to localize.
    """
    try:
        sp = subprocess.run(["bash", "scripts/run.sh", "test", "--all"],
                            cwd=cfg.repo_root, capture_output=True, text=True,
                            timeout=len(tests) * 60 + 60)
    except subprocess.TimeoutExpired:
        failures.append(("(suite)",
                         "TIMEOUT: suite execution exceeded the runner limit"))
        return
    except Exception as e:
        failures.append(("(suite)", f"EXEC_ERROR: {e}"))
        return
    rc = sp.returncode
    raw = (sp.stderr or "") + "\n" + (sp.stdout or "")
    if rc == 0:
        return
    if rc == 6:
        failures.append(("(suite)", "ENV-FAIL: " + _tail_output(cfg, raw)))
        return
    if rc == 124:
        failures.append(("(suite)",
                         "TIMEOUT: suite hit the per-file 60 s timeout "
                         "(rc=124) — " + _tail_output(cfg, raw)))
        return
    # rc == 1 (a test failed / unclaimed file), rc == 2 (run.sh refused
    # `test --all` — strict contract) or any other non-zero rc:
    # surface the suite output so the fix prompt can localize the failure.
    failures.append(("(suite)", _tail_output(cfg, raw)))


def verify_gate(cfg, plan: "SessionPlan") -> tuple[bool, list[tuple[str, str]], bool]:
    """Verdict = positive contract on the ticket's declared paths (W2.3)
    + every test the project's runner declares (D3).

    Discovery goes through the project entrypoint too (run.sh list), so the
    machine no longer hardcodes the *.test.js convention. Test execution is
    ONE whole-suite call per turn (`run.sh test --all`, D4/CC-149); see
    `_run_suite` for the rc mapping — an entrypoint that refuses `--all`
    (rc=2) fails the run (strict contract, PLAN-HYGIENE 2026-10-08).
    Returns (ok, failures, env_fail): env_fail is True when any failure is
    an ENV-FAIL (run.sh rc=6, runner unavailable) — an environment defect
    the model cannot fix from src/, so the caller must stop fail-closed
    (rc=16) instead of sending a fix prompt.
    """
    failures: list[tuple[str, str]] = []
    # Positive contract: every artifact the ticket declares must exist.
    # Closes the hole where a model that skipped docs/<m>.md still passed.
    for rel in plan.declared_paths:
        if not os.path.exists(os.path.join(cfg.repo_root, rel)):
            failures.append((rel, f"MISSING: declared by the ticket but not created: {rel}"))

    try:
        lp = subprocess.run(["bash", "scripts/run.sh", "list"],
                            cwd=cfg.repo_root, capture_output=True, text=True, timeout=30)
    except Exception as e:
        return (False, [("(no tests)", f"run.sh list failed: {e}")], False)
    tests = [ln.strip() for ln in (lp.stdout or "").splitlines() if ln.strip()]
    if not tests:
        if lp.returncode != 0:
            # `list` failed and printed no tests (no tests/ dir, or only
            # unclaimed files): the reason is on stderr — surface it instead
            # of the generic "no tests" message.
            failures.append(("(list)", _tail_output(cfg, lp.stderr)))
            return (False, failures, False)
        if failures:
            return (False, failures, False)
        return (False, [("(no tests)", "The project runner declares no tests")], False)
    if lp.returncode != 0:
        # W12: `list` fails closed (rc=1) on an unclaimed test-like file while
        # still printing the claimed tests on stdout. The unrun test must not
        # pass the gate silently: record the listing failure, then still run
        # the claimed tests (their failures add signal to the fix prompt).
        failures.append(("(list)", _tail_output(cfg, lp.stderr)))

    _run_suite(cfg, failures, tests)
    failures.sort(key=lambda x: x[0])
    env_fail = any(msg.startswith("ENV-FAIL:") for _, msg in failures)
    return (len(failures) == 0, failures, env_fail)


def fresh_verify(cfg) -> tuple[int, str]:
    """Stage 3 (T3-3): run the fresh verification container (sandbox.
    fresh_verify_argv — whole repo :ro, --network=none, no unconfined) and
    return (rc, tail): the host's independent re-run of the suite, the
    verdict input the T3-6 wiring consumes (FRESH-FAIL when rc != 0).

    The host timeout is a BACKSTOP only — run.sh self-limits per file
    (rc=124). docker_stop covers the killed-client case: a docker CLI killed
    by the timeout leaves the container running (--rm removes it only on a
    normal exit)."""
    name, argv = sandbox.fresh_verify_argv(cfg.repo_root, cfg.docker_image)
    try:
        sp = subprocess.run(argv, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired:
        sandbox.docker_stop(name)
        return (124, "TIMEOUT: the fresh verification exceeded the host limit")
    except Exception as e:
        return (1, f"EXEC_ERROR: {e}")
    return (sp.returncode,
            _tail_output(cfg, (sp.stderr or "") + "\n" + (sp.stdout or "")))


def _fix_prompt_rules(failures: list[tuple[str, str]]) -> str:
    """Select the fix-prompt rule block for a verify_gate failure set.

    Priority: list-fail > timeout > no-tests > generic. A hung test
    (TIMEOUT) must not get the generic "fix src exclusively" rules: that
    wording is a retry-loop DoS (the model iterates on src/, the test
    hangs again, verify_gate fails again with the same prompt).
    """
    has_list_fail = any(name == "(list)" for name, _ in failures)
    has_timeout_fail = any(msg.startswith("TIMEOUT:") for _, msg in failures)
    has_no_tests = any(name == "(no tests)" for name, _ in failures)
    if has_list_fail:
        return (
            "1. The project runner's `list` command failed: tests/ contains a "
            "test-like file that no registry line in scripts/run.sh claims.\n"
            "2. Delete the unclaimed file or move it to tests/fixtures/ (or "
            "tests/data/). It is CATEGORICALLY FORBIDDEN to add a registry "
            "line to scripts/run.sh to claim it, and to weaken or modify the "
            "tests in tests/.\n"
            "3. Then re-check with `bash scripts/run.sh list` — it must exit 0."
        )
    if has_timeout_fail:
        return (
            "1. A test HUNG (rc=124, runner timeout) — this is NOT a red "
            "assertion; do not iterate on src/ to make it green.\n"
            "2. Locate and remove the hang (infinite loop / blocking call) in the test or in the implementation.\n"
            "3. Then re-check with `bash scripts/run.sh test <path>` — it must finish well under the runner timeout."
        )
    if has_no_tests:
        return (
            "1. There are no test files in the tests/ directory! Create the "
            "reference tests strictly per the ticket specification.\n"
            "2. Then implement the corresponding working module code in the src/ directory."
        )
    return (
        "1. The tests in tests/ are the reference specification of the ticket. "
        "It is CATEGORICALLY FORBIDDEN to delete, modify, or weaken "
        "assertions in tests/.\n"
        "2. Fixes are made EXCLUSIVELY in the module implementations in the src/ directory.\n"
        "3. Study the diff and stack above, localize the error in src/ and eliminate the root cause of the bug."
    )


def _protected_files(cfg) -> list[str]:
    """The pre-existing contract files — the ONE source for "protected"
    (CC-136): tests/**, scripts/run.sh and scripts/stacks/*.toml. Both the
    contract_lock manifest and the host's :ro bind list (host_ro_paths) read
    this list, so the two cannot drift.

    Only PRE-EXISTING files: a missing scripts/run.sh (a new project's first
    ticket) is free to create. __pycache__/ is skipped: .pyc files are
    interpreter cache artifacts, not contract files — locking them makes a
    routine `rm -rf __pycache__` (or their regeneration) a false
    DELETED/MODIFIED violation (w12-verify)."""
    protected: list[str] = []
    tests_dir = os.path.join(cfg.repo_root, "tests")
    if os.path.isdir(tests_dir):
        for root, dirs, files in os.walk(tests_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                protected.append(os.path.relpath(os.path.join(root, name), cfg.repo_root))
    if os.path.isfile(os.path.join(cfg.repo_root, "scripts", "run.sh")):
        protected.append("scripts/run.sh")
    # B1 (PLAN-AUDIT-2026-10-08): run.sh derives its STACKS registry
    # (test_runner, test_glob, verdict_config) from these manifests at every
    # invocation, and scripts/ is a machine RW zone whenever a ticket declares
    # a path under it. A manifest left writable lets the machine swap
    # test_runner for `true` and get a PASS with no test ever run.
    stacks_dir = os.path.join(cfg.repo_root, "scripts", "stacks")
    if os.path.isdir(stacks_dir):
        for name in sorted(os.listdir(stacks_dir)):
            if name.endswith(".toml"):
                protected.append(os.path.relpath(
                    os.path.join(stacks_dir, name), cfg.repo_root))
    return protected


def _src_files(cfg) -> list[str]:
    """T3-10 (operator 2026-10-09): the src/ file listing for the after-only
    half of the structural rule. NOT protected files: existing src/ files are
    the machine's normal implementation surface (MODIFIED/DELETED stays scoped
    to _protected_files), and src/ must NOT enter _protected_files — that list
    is also the host's :ro bind list (host_ro_paths), and binding src/ :ro
    would make the machine unable to implement anything. The hole this closes
    (proven live on the public code): a new src/colorsys.py shadows the stdlib
    `colorsys` a reference test imports (src is on sys.path via
    pythonpath=src); the test passes against the fake, W12 only sees test-like
    names, the fresh check re-runs the same tree. __pycache__ is skipped for
    the same reason as in _protected_files."""
    src_dir = os.path.join(cfg.repo_root, "src")
    listing: list[str] = []
    if os.path.isdir(src_dir):
        for root, dirs, files in os.walk(src_dir):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for name in files:
                listing.append(os.path.relpath(os.path.join(root, name),
                                               cfg.repo_root))
    return listing


def contract_snapshot(cfg) -> dict[str, str]:
    """Stage 3 (T3-1): the HOST-side entry point for the pre-run contract
    snapshot — the same manifest as _tests_manifest (the one protected-files
    source, CC-136), exposed publicly so run_sandboxed can take it BEFORE
    `docker run` and keep it in the host process memory. Memory, not a file:
    a file in LOG_DIR lives in the container's rw mount and the worker could
    rewrite it (trust boundary, SPEC-VERDICT-INTEGRITY §1). T3-2 recomputes
    after the container exits and compares."""
    return _tests_manifest(cfg)


def _tests_manifest(cfg) -> dict[str, str]:
    """Snapshot {rel_path: sha256} of the protected files (contract_lock,
    W2.5 + P2) — see _protected_files for which files and why — plus the
    src/ listing (T3-10): src/ entries exist in the snapshot ONLY for the
    after-only UNDECLARED half of the structural rule; _compare_manifests
    skips them in the MODIFIED/DELETED loop (existing src/ files are the
    machine's implementation surface)."""
    manifest: dict[str, str] = {}
    for rel in _protected_files(cfg) + _src_files(cfg):
        try:
            with open(os.path.join(cfg.repo_root, rel), "rb") as f:
                manifest[rel] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            manifest[rel] = "unreadable"
    return manifest


def _compare_manifests(before: dict[str, str], after: dict[str, str],
                       declared) -> list[str]:
    """The ONE comparison of two protected-file manifests (T3-2): a
    pre-existing protected file that is DELETED or MODIFIED is a violation.
    T3-9 (structural tests/ rule, operator 2026-10-09): after the run the
    set of files under tests/ must equal the snapshot plus the declared test
    files — any other file is an UNDECLARED violation regardless of its
    name. The substitution hole (live on the public main): a helper module
    tests/colorsys.py shadows the stdlib `colorsys` a reference test imports,
    the test passes against the fake; the name gate (run.sh list, W12) only
    sees test-like names, so this is the structural half. T3-10 (operator,
    same day): the same hole exists on the other side of the import path —
    src/ is on sys.path (pythonpath=src), so the after-only scope is
    tests/ + src/: any new undeclared file there is a substitution. The
    asymmetry is deliberate: the MODIFIED/DELETED half stays scoped to the
    protected files — existing src/ files are the machine's normal
    implementation surface (the src/ entries in the snapshot exist only for
    the after-only half, see _src_files). New files elsewhere (a bootstrap
    scripts/run.sh, docs/) are ticket output, not substitutions. Used by the
    worker-side _check_contract_lock and by the host-side host_contract_check
    with the same declared context — the two cannot drift."""
    violations = []
    for rel, digest in before.items():
        if rel in declared or rel.startswith("src/"):
            # T3-10: src/ entries are in the snapshot for the after-only
            # half only; editing/deleting an existing src/ file is normal
            # implementation work, not a contract violation.
            continue
        if rel not in after:
            violations.append(f"DELETED: {rel}")
        elif after[rel] != digest:
            violations.append(f"MODIFIED: {rel}")
    for rel in after:
        if rel in before or rel in declared:
            continue
        if rel.startswith("tests/") or rel.startswith("src/"):
            violations.append(f"UNDECLARED: {rel}")
    return violations


def host_contract_check(cfg, before: dict[str, str], declared) -> list[str]:
    """Stage 3 (T3-2): the host recomputes the protected-files manifest AFTER
    the container exits and compares it with the pre-run snapshot (T3-1).
    Any violation means the tree the verdict was computed against was
    tampered with — the caller forces CONTRACT-FAIL regardless of the worker
    summary (trust boundary, SPEC-VERDICT-INTEGRITY §1). No job/turn
    context; a PRE-EXISTING protected file has no exemption (CC-206 rejects
    tickets that edit one, so an exemption would only hide tampering).
    T3-9/T3-10: `declared` is the ticket's declared-path list — the only
    allowed addition to tests/ or src/; without it a ticket's declared new
    tests would be indistinguishable from a substitution."""
    return _compare_manifests(before, _tests_manifest(cfg), declared)


def _check_contract_lock(cfg, before: dict[str, str], job: dict, turn: int,
                         plan: "SessionPlan") -> None:
    """After each turn: a pre-existing protected file (tests/, scripts/run.sh)
    that was MODIFIED or DELETED is a contract_lock violation (replaces the
    chmod a-w freeze, W2.5). A new file under tests/ or src/ that the ticket
    did not declare is an UNDECLARED violation (T3-9/T3-10, structural tree
    rule); a declared new test or impl file is allowed (a ticket may declare
    several). A declared
    path is exempt (runner-update ticket, P2;
    behavior-identical to the old scripts/run.sh exemption, since the
    manifest is snapshotted AFTER quarantine and a declared path is
    therefore never in the manifest)."""
    after = _tests_manifest(cfg)
    violations = _compare_manifests(before, after, plan.declared_paths)
    if violations:
        job.setdefault("contract_lock_violations", []).extend(
            f"turn {turn}: {v}" for v in violations
        )
        log(f"  [CONTRACT-LOCK] turn {turn}: {violations}")


def _check_zone_symlinks(cfg, before: list[str], job: dict, turn: int) -> None:
    """Post-turn half of the zone-symlink ban (operator decision 2026-10-09):
    a symlink CREATED in a writable zone during the run is a contract_lock
    violation -> the existing forced-FAIL path (no retry, cumulative).
    Compared against the session-start snapshot (gates.zone_symlinks), NOT
    the ticket — a ticket never declares arbitrary links. The launch gate
    guarantees an empty baseline; the snapshot makes the rule independent of
    it too: a link that predates the session is not a NEW one. Fail-closed:
    a scan error is itself a violation."""
    try:
        after = gates.zone_symlinks(cfg)
    except OSError as e:
        job.setdefault("contract_lock_violations", []).append(
            f"turn {turn}: ZONE-SYMLINK-SCAN-FAILED: {e}")
        log(f"  [ZONE-SYMLINK] turn {turn}: scan failed: {e} — fail-closed")
        return
    new = [rel for rel in after if rel not in set(before)]
    if new:
        job.setdefault("contract_lock_violations", []).extend(
            f"turn {turn}: NEW-SYMLINK: {rel}" for rel in new
        )
        log(f"  [ZONE-SYMLINK] turn {turn}: {new}")


def _contract_lock_forced_fail(job: dict, turn: int) -> int | None:
    """Fail-closed on contract_lock violations (W2.5 + P2): a non-empty
    cumulative violations list means the machine MODIFIED/DELETED a
    pre-existing protected file (tests/, scripts/run.sh) after the manifest
    snapshot — a verify_gate PASS was computed against tampered tests and is
    not a PASS. No retry: the list is cumulative and can never be cleared
    inside the session, so a fix prompt cannot succeed; the supervisor
    relaunches with a refined ticket. Sets probe_result "CONTRACT-FAIL" (an
    override, see test_contract_fail_probe.py) so the summary distinguishes a
    contract violation from a test failure. Returns the run rc (1) or None
    when clean."""
    violations = job.get("contract_lock_violations") or []
    if not violations:
        return None
    # probe_result override (operator review 2026-10-09), by the NO-OP-PASS /
    # LOOP-TRAP pattern: without it decide() falls through to the table and
    # the summary says VERIFY-FAIL — a contract violation would be
    # indistinguishable from a test failure. The table is unchanged.
    job["probe_result"] = "CONTRACT-FAIL"
    job["verifier"] = "FAIL"
    job["error"] = ("CONTRACT-LOCK: the machine modified or deleted protected "
                   "files (tests/, scripts/run.sh) or created a symlink in a "
                   "writable zone after the manifest snapshot — the verdict was "
                   "computed against tampered tests")
    job.setdefault("failures", []).extend(
        ("(contract_lock)", v) for v in violations
    )
    job["turns"] = turn
    log("CONTRACT-LOCK: fail-closed (no retry — violations are cumulative)")
    return 1


