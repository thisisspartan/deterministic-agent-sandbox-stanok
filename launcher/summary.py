"""summary — the verdict artifacts: summary.json, evidence publishing, rotation.

build_summary/write_summary (the typed contract, S1 summary routing:
container -> rw LOG_DIR/<label>),
write_env_fail_summary (T3-6: fresh-check infra failure -> ENV-FAIL),
_publish_evidence (CC-134; T3-5 host-issued verdict priority
CONTRACT-FAIL > FRESH-FAIL > the worker's claims — S2, PLAN-SIMPLIFY-2026-10-09:
the I5 rc cross-check, the worker_* fields and INTEGRITY-FAIL are removed),
_rotate_stale_summary,
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

    S2 (PLAN-SIMPLIFY-2026-10-09): the I5 rc cross-check, the worker_*
    fields and the INTEGRITY-FAIL value are REMOVED. The host's authority is
    its two independent checks only — the contract recompute and the fresh
    check; the worker's summary passes through untouched when neither fires.
    The verdict is a statement about the TREE (suite green + tree = declared),
    not about the worker's self-report: a pure forgery (claims PASS while the
    container exited non-zero) over a clean contract with a green fresh check
    is no longer caught — sanctioned gap.

    Stage 3 (T3-2) `contract_violations`: the host's own recompute of the
    protected-files manifest (verify.host_contract_check against the pre-run
    snapshot). Non-empty means the tree the verdict was computed against was
    tampered with — the host forces verifier=FAIL + probe_result=CONTRACT-FAIL
    regardless of what the worker summary claims (the judge is not the
    defendant).

    Stage 3 (T3-5): the final verifier/rc/probe_result are issued by the HOST
    with the priority CONTRACT-FAIL > FRESH-FAIL > the worker's claims.
    `fresh_check=(rc, tail)` is verify.fresh_verify's result (the host's
    independent re-run in a fresh container, T3-3); a non-zero fresh rc forces
    verifier=FAIL + probe_result=FRESH-FAIL + rc=fresh rc, the tail appended
    to errors. fresh_check=None = not run."""
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
    if contract_violations:
        # Stage 3 (T3-2): the host's recompute outranks the worker's verdict
        # (priority CONTRACT-FAIL > everything): the tree was tampered with
        # after the pre-run snapshot — the verdict was computed against
        # modified protected files. Force the FAIL.
        summary["verifier"] = "FAIL"
        # T3-9: a host-issued FAIL cannot carry a success rc — the rc
        # contract (exitcodes.py: 1 = contract violation) requires 1 when
        # the container claimed success; the container's non-zero exit
        # stays ground truth.
        summary["rc"] = container_rc or int(ExitCode.DEFECT)
        summary["probe_result"] = "CONTRACT-FAIL"
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
        # the worker's summary claims. Priority: FRESH-FAIL outranks the
        # worker's claims. The final rc is the fresh check's own exit code —
        # the host's measurement, not the worker's.
        fresh_rc, tail = fresh_check
        summary["verifier"] = "FAIL"
        summary["rc"] = fresh_rc
        summary["probe_result"] = "FRESH-FAIL"
        summary.setdefault("errors", []).append(
            f"HOST FRESH-CHECK: the suite failed in a fresh container the "
            f"worker never touched (rc={fresh_rc}): {tail}")
        with open(sum_dst, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        log(f"FRESH-CHECK: {label}: fresh verify rc={fresh_rc} — "
            "verdict FRESH-FAIL")


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
    LOOP-TRAP, CONTRACT-FAIL); otherwise the derived table.
    test_scenarios_verdict.py pins this priority end-to-end (S6): any
    change here must pass it UNCHANGED."""
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

    S1 (rollback of T3-4): the path is cfg.summary_dir(label) — inside the
    container the rw LOG_DIR/<label> mount (the host publishes it into
    evidence/<label> after the container exits); on the host (no-sandbox) the
    evidence dir."""
    d = cfg.summary_dir(job["label"])
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, elapsed_s), f, ensure_ascii=False, indent=2)


def write_env_fail_summary(cfg, label: str, error: str) -> None:
    """Stage 3 (T3-6): a host-side infrastructure failure — the fresh check
    could not run (EXEC_ERROR). The verdict cannot be issued: the host writes
    an ENV-FAIL summary (rc=16) with the error text directly into the
    evidence dir — not a verdict, call the human."""
    evidence_dir, _ = cfg.label_paths(label)
    os.makedirs(evidence_dir, exist_ok=True)
    job = {"label": label, "rc": int(ExitCode.ENV_FAIL), "verifier": "FAIL",
           "probe_result": "ENV-FAIL", "turns": 0, "error": error}
    with open(os.path.join(evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, 0), f, ensure_ascii=False, indent=2)

