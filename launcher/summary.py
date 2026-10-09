"""summary — the verdict artifacts: summary.json, evidence publishing, rotation.

build_summary/write_summary (the typed contract, T3-4 summary routing),
write_env_fail_summary (T3-4/T3-6: docker cp failure or fresh-check infra
failure -> ENV-FAIL),
_publish_evidence (CC-134, I5 integrity check; T3-5 host-issued verdict
priority CONTRACT-FAIL > FRESH-FAIL > INTEGRITY-FAIL), _rotate_stale_summary,
the status-field table. Static
config arrives as the passed-in Config; the per-run evidence dir as the
passed-in RunState (C).
"""

import json
import os
import shutil
from launcher.exitcodes import ExitCode
from launcher.logs import log


def _publish_evidence(cfg, label: str, container_rc: int,
                      contract_violations: list[str] = (),
                      fresh_check: tuple | None = None) -> None:
    """Copy the container-written verdict from the rw LOG_DIR/<label> into the
    host-owned evidence/<label> (CC-134).

    Called in run_sandboxed's finally AFTER docker stop — the container has no
    rw view of evidence/, so the host is the only publisher. Missing files are
    skipped: an aborted launch publishes nothing rather than a fake verdict.

    I5 fail-closed integrity check (REVIEW-ISOLATION-2026-09-28 §6.2): the
    host's container_rc (docker exit code = the container-side launcher's
    exit code = the real run rc) is ground truth. A summary.json that claims
    PASS after a non-zero container exit, or whose rc field disagrees with
    the container exit, is a forged verdict from the PASS->publish TOCTOU
    window — force FAIL and record the violation.

    NO-OP exemption: a NO-OP run (probe_result == "NO-OP-PASS") intentionally
    returns rc=1 with verifier=PASS (the machine did no work; the artifacts
    pre-existed and the verifier really passed). That rc=1+PASS combination is
    legitimate, not a forgery, so the "claims PASS" check is skipped for it;
    the rc-field consistency check still applies.

    CONTRACT-FAIL exemption: a contract violation outranks the integrity
    label (spec priority CONTRACT-FAIL > FRESH-FAIL > INTEGRITY-FAIL) — the
    violation is recorded and the rc fixed, but probe_result stays
    CONTRACT-FAIL.

    Stage 3 (T3-2) `contract_violations`: the host's own recompute of the
    protected-files manifest (verify.host_contract_check against the pre-run
    snapshot). Non-empty means the tree the verdict was computed against was
    tampered with — the host forces verifier=FAIL + probe_result=CONTRACT-FAIL
    regardless of what the worker summary claims (the judge is not the
    defendant). This outranks the I5 check: the I5 block is skipped.

    Stage 3 (T3-5): the final verifier/rc/probe_result are issued by the HOST
    with the spec priority CONTRACT-FAIL > FRESH-FAIL > INTEGRITY-FAIL >
    worker override. `fresh_check=(rc, tail)` is verify.fresh_verify's result
    (the host's independent re-run in a fresh container, T3-3); a non-zero
    fresh rc forces verifier=FAIL + probe_result=FRESH-FAIL + rc=fresh rc,
    the tail appended to errors. fresh_check=None = not run (T3-5 does not
    wire it into run_sandboxed yet — T3-6 does). The worker's claims are
    preserved in worker_rc/worker_verifier — written ONLY when the host
    overrides the verdict (the clean path stays byte-identical). The I5
    detector compares worker_rc with the container exit, NOT the final rc:
    the host's own final write is never taken for a forgery."""
    src = os.path.join(cfg.log_dir, label)
    files = ("summary.json", "launcher.stdout.log")
    if not any(os.path.isfile(os.path.join(src, f)) for f in files):
        return
    dst = os.path.join(cfg.repo_root, "evidence", label)
    os.makedirs(dst, exist_ok=True)
    for name in files:
        s = os.path.join(src, name)
        if os.path.isfile(s):
            shutil.copyfile(s, os.path.join(dst, name))
    sum_dst = os.path.join(dst, "summary.json")
    if not os.path.isfile(sum_dst):
        return
    try:
        with open(sum_dst, encoding="utf-8") as f:
            summary = json.load(f)
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(summary, dict):
        return
    # Stage 3 (T3-5): the worker's claims are captured BEFORE any host write.
    # The I5 detector compares worker_rc with the container exit — never the
    # host's own final write: the host's rc=container_rc is not a forgery.
    worker_rc = summary.get("rc")
    worker_verifier = summary.get("verifier")
    if contract_violations:
        # Stage 3 (T3-2): the host's recompute outranks the worker's verdict
        # (spec priority CONTRACT-FAIL > everything): the tree was tampered
        # with after the pre-run snapshot — the verdict was computed against
        # modified protected files. Force the FAIL; the I5 block below cannot
        # add signal the host already has.
        summary["verifier"] = "FAIL"
        summary["rc"] = container_rc
        summary["probe_result"] = "CONTRACT-FAIL"
        summary["worker_rc"] = worker_rc
        summary["worker_verifier"] = worker_verifier
        summary.setdefault("contract_lock_violations", []).extend(
            contract_violations)
        summary["error"] = (
            "HOST CONTRACT-LOCK: the tree was tampered with after the "
            "pre-run snapshot — the verdict was computed against modified "
            "protected files")
        with open(sum_dst, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        log(f"CONTRACT-LOCK: {label}: host recompute: {contract_violations}")
        return
    if fresh_check is not None and fresh_check[0] != 0:
        # Stage 3 (T3-5): the host's independent fresh check (T3-3) failed —
        # the suite does not pass on the tree as the HOST sees it, whatever
        # the worker's summary claims. Spec priority: FRESH-FAIL outranks the
        # I5 check and the worker override. The final rc is the fresh
        # check's own exit code — the host's measurement, not the worker's.
        fresh_rc, tail = fresh_check
        summary["verifier"] = "FAIL"
        summary["rc"] = fresh_rc
        summary["probe_result"] = "FRESH-FAIL"
        summary["worker_rc"] = worker_rc
        summary["worker_verifier"] = worker_verifier
        summary.setdefault("errors", []).append(
            f"HOST FRESH-CHECK: the suite failed in a fresh container the "
            f"worker never touched (rc={fresh_rc}): {tail}")
        with open(sum_dst, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        log(f"FRESH-CHECK: {label}: fresh verify rc={fresh_rc} — "
            "verdict FRESH-FAIL")
        return
    violations = []
    # A NO-OP run intentionally returns rc=1 with verifier=PASS (the machine
    # did no work; the artifacts pre-existed and the verifier really passed).
    # The "claims PASS" check must not fire on that intentional combination —
    # only the rc-field consistency check below still applies.
    is_noop = summary.get("probe_result") == "NO-OP-PASS"
    if not is_noop and container_rc != 0 and worker_verifier == "PASS":
        violations.append(
            f"container exited rc={container_rc} but summary claims PASS")
    if worker_rc != container_rc:
        violations.append(
            f"summary rc={worker_rc!r} != container rc={container_rc}")
    if violations:
        # A forged verdict must not leave any PASS-shaped field behind:
        # override the whole verdict, not just the verifier flag.
        # CONTRACT-FAIL exemption (operator review 2026-10-09): the spec
        # priority is CONTRACT-FAIL > INTEGRITY-FAIL — a contract violation
        # is the defect class the supervisor must see. The violation is still
        # recorded and the container rc stays ground truth, but the verdict
        # CLASS is not downgraded.
        summary["verifier"] = "FAIL"
        summary["rc"] = container_rc
        summary["worker_rc"] = worker_rc
        summary["worker_verifier"] = worker_verifier
        if summary.get("probe_result") != "CONTRACT-FAIL":
            summary["probe_result"] = "INTEGRITY-FAIL"
        summary["integrity_violation"] = "; ".join(violations)
        with open(sum_dst, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        log(f"INTEGRITY: {label}: forged verdict rejected: "
            + "; ".join(violations))


def _rotate_stale_summary(cfg, label: str) -> None:
    """Rotate a stale summary.json left by an EARLIER run of the same label
    (a run aborted at a gate after writing its report, or a killed process).
    Without rotation, early_abort's write-if-absent guard would keep the OLD
    report and the supervisor would read a verdict from the previous run.
    Only rotate when no `.running` marker is present: a live run's evidence
    must not be touched."""
    evidence_dir, _ = cfg.label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    sum_path = os.path.join(evidence_dir, "summary.json")
    if os.path.isfile(sum_path) and not os.path.exists(marker):
        try:
            os.replace(sum_path, sum_path + ".prev")
        except OSError:
            pass


def _status_fields(rc: int, verifier: str, turns: int) -> str:
    """RC_TABLE — the derived fallback of decide(): probe_result from
    (rc, verifier, turns). A new outcome = one row here.
    Fail-closed: only rc==0 AND verifier=="PASS" is a pass; everything
    else is a defect (no PASS-on-FAIL).
    Never make this a pure rc->fields table: rc=1 is polysemous
    (NO-OP-PASS vs exhausted-retries) — the disambiguation is the
    session/host override, applied by decide(), not here."""
    if rc == 0 and verifier == "PASS":
        return "CLEAN-FIRST" if turns == 1 else "PASS-AFTER-LOCAL-RETRY"
    if rc == 16:
        # ENV-FAIL: the image lacks the test runner — an infrastructure
        # failure (rebuild the image), neither a defect nor a NO-OP.
        return "ENV-FAIL"
    return "VERIFY-FAIL"


def decide(job: dict) -> str:
    """probe_result with the priority made explicit (red-team review
    2026-10-08; override-vs-override priority added by the operator review
    2026-10-09): a non-empty contract_lock_violations list wins over every
    behavioral override — CONTRACT-FAIL describes the integrity of the verdict
    (the tree was tampered with), LOOP-TRAP/NO-OP-PASS only the model's
    behavior; probe_result is ONE key, so without this rule the later write
    would win by accident. Then the session/host override (NO-OP-PASS,
    LOOP-TRAP, CONTRACT-FAIL); otherwise the derived table. INTEGRITY-FAIL is
    NOT here — the host sets it after build_summary, in _publish_evidence.
    test_verdict_table.py pins this priority: any change here must pass it
    UNCHANGED (its jobs carry no violations)."""
    if job.get("contract_lock_violations"):
        return "CONTRACT-FAIL"
    override = job.get("probe_result")
    if override:
        return override
    return _status_fields(job.get("rc", 1), job.get("verifier", "FAIL"),
                          job.get("turns", 1))


def build_summary(cfg, job: dict, elapsed_s: int) -> dict:
    """Single source of the summary.json schema (shared by write_summary
    and early_abort)."""
    turns = job.get("turns", 1)
    verifier = job.get("verifier", "FAIL")
    rc = job.get("rc", 1)
    probe_result = decide(job)

    per_turn = job.get("turn_telemetry", [])
    inference_telemetry = {
        "per_turn": per_turn,
        "aggregate": {
            "turns": len(per_turn),
            "total_turn_elapsed_s": round(sum(t.get("elapsed_s", 0) for t in per_turn), 1),
            "tokens": job.get("tokens", {}),
            "cache_hit_rate": job.get("cache_hit_rate", "0.0%"),
        },
    }

    # Provenance (W2.6): the exact commit the run started from — captured on
    # the HOST (cli._capture_start_commit) before the container starts and
    # passed in via STANOK_START_COMMIT (the container never runs git: in a
    # worktree `.git` points outside the mounted tree, rev-parse fails there
    # — plan 2026-10-08, step 1). Missing env -> explicit None + WARN, never
    # a silent swallow.
    commit_sha = os.environ.get("STANOK_START_COMMIT") or None
    if commit_sha is None:
        log("WARN: commit provenance: STANOK_START_COMMIT not set — "
            "publishing commit_sha=None")

    return {
        "label": job.get("label"),
        "ticket": job.get("ticket"),
        "rc": rc,
        "verifier": verifier,
        "probe_result": probe_result,
        "turns": turns,
        "elapsed_s": elapsed_s,
        "session_id": job.get("session_id"),
        "commit_sha": commit_sha,
        "tokens": job.get("tokens", {}),
        "cache_hit_rate": job.get("cache_hit_rate", "0.0%"),
        "inference_telemetry": inference_telemetry,
        "contract_lock_violations": job.get("contract_lock_violations", []),
        "errors": [job["error"]] if job.get("error") else [],
        "failures": job.get("failures", []),
        "opik_traces": job.get("opik_traces"),
    }


def write_summary(cfg, job: dict, elapsed_s: int) -> None:
    """Writes the exact summary.json contract expected by the L1 Supervisor.

    Stage 3 (T3-4): the path is cfg.summary_dir(label) — inside the container
    the writable-layer path the host retrieves with `docker cp` after the
    container exits; on the host (no-sandbox) the evidence dir. The summary
    is no longer a file shared through a mount the worker can rewrite."""
    d = cfg.summary_dir(job["label"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, elapsed_s), f, ensure_ascii=False, indent=2)


def write_env_fail_summary(cfg, label: str, error: str) -> None:
    """Stage 3 (T3-4, generalized by T3-6): a host-side infrastructure
    failure — `docker cp` could not retrieve the worker's summary, or the
    fresh check could not run (EXEC_ERROR). The verdict cannot be issued:
    the host writes an ENV-FAIL summary (rc=16) with the error text directly
    into the evidence dir — not a verdict, call the human."""
    evidence_dir, _ = cfg.label_paths(label)
    os.makedirs(evidence_dir, exist_ok=True)
    job = {"label": label, "rc": int(ExitCode.ENV_FAIL), "verifier": "FAIL",
           "probe_result": "ENV-FAIL", "turns": 0, "error": error}
    with open(os.path.join(evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, 0), f, ensure_ascii=False, indent=2)

