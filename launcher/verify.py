"""verify — the external verifier: run.sh invocation, output tail, contract_lock.

verify_gate / _run_suite / _tail_output (raw tail, CC-138), the protected-file
manifest and the contract_lock second echelon (W2.5/P2). The tail limits and
repo root come from the passed-in Config (C).
"""

import hashlib
import os
import subprocess
from stanok import log


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


def _tests_manifest(cfg) -> dict[str, str]:
    """Snapshot {rel_path: sha256} of the protected files (contract_lock,
    W2.5 + P2) — see _protected_files for which files and why."""
    manifest: dict[str, str] = {}
    for rel in _protected_files(cfg):
        try:
            with open(os.path.join(cfg.repo_root, rel), "rb") as f:
                manifest[rel] = hashlib.sha256(f.read()).hexdigest()
        except OSError:
            manifest[rel] = "unreadable"
    return manifest


def _check_contract_lock(cfg, before: dict[str, str], job: dict, turn: int,
                         plan: "SessionPlan") -> None:
    """After each turn: a pre-existing protected file (tests/, scripts/run.sh)
    that was MODIFIED or DELETED is a contract_lock violation (replaces the
    chmod a-w freeze, W2.5). New files are allowed (a ticket may declare
    several). A declared path is exempt (runner-update ticket, P2;
    behavior-identical to the old scripts/run.sh exemption, since the
    manifest is snapshotted AFTER quarantine and a declared path is
    therefore never in the manifest)."""
    after = _tests_manifest(cfg)
    violations = []
    for rel, digest in before.items():
        if rel in plan.declared_paths:
            continue
        if rel not in after:
            violations.append(f"DELETED: {rel}")
        elif after[rel] != digest:
            violations.append(f"MODIFIED: {rel}")
    if violations:
        job.setdefault("contract_lock_violations", []).extend(
            f"turn {turn}: {v}" for v in violations
        )
        log(f"  [CONTRACT-LOCK] turn {turn}: {violations}")


def _contract_lock_forced_fail(job: dict, turn: int) -> int | None:
    """Fail-closed on contract_lock violations (W2.5 + P2): a non-empty
    cumulative violations list means the machine MODIFIED/DELETED a
    pre-existing protected file (tests/, scripts/run.sh) after the manifest
    snapshot — a verify_gate PASS was computed against tampered tests and is
    not a PASS. No retry: the list is cumulative and can never be cleared
    inside the session, so a fix prompt cannot succeed; the supervisor
    relaunches with a refined ticket. Returns the run rc (1) or None when
    clean."""
    violations = job.get("contract_lock_violations") or []
    if not violations:
        return None
    job["verifier"] = "FAIL"
    job["error"] = ("CONTRACT-LOCK: the machine modified or deleted protected "
                   "files (tests/, scripts/run.sh) after the manifest snapshot "
                   "— the verdict was computed against tampered tests")
    job.setdefault("failures", []).extend(
        ("(contract_lock)", v) for v in violations
    )
    job["turns"] = turn
    log("CONTRACT-LOCK: fail-closed (no retry — violations are cumulative)")
    return 1


