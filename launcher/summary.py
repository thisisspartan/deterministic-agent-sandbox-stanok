"""summary — the verdict artifacts: summary.json, evidence publishing, rotation.

build_summary/write_summary (the typed contract), _publish_evidence (CC-134,
I5 integrity check), _rotate_stale_summary, the status-field table. Static
config arrives as the passed-in Config; the per-run evidence dir as the
passed-in RunState (C).
"""

import json
import os
import shutil
import subprocess
from launcher.logs import log


def _publish_evidence(cfg, label: str, container_rc: int) -> None:
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
    the rc-field consistency check still applies."""
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
    violations = []
    # A NO-OP run intentionally returns rc=1 with verifier=PASS (the machine
    # did no work; the artifacts pre-existed and the verifier really passed).
    # The "claims PASS" check must not fire on that intentional combination —
    # only the rc-field consistency check below still applies.
    is_noop = summary.get("probe_result") == "NO-OP-PASS"
    if not is_noop and container_rc != 0 and summary.get("verifier") == "PASS":
        violations.append(
            f"container exited rc={container_rc} but summary claims PASS")
    if summary.get("rc") != container_rc:
        violations.append(
            f"summary rc={summary.get('rc')!r} != container rc={container_rc}")
    if violations:
        # A forged verdict must not leave any PASS-shaped field behind:
        # override the whole verdict, not just the verifier flag.
        summary["verifier"] = "FAIL"
        summary["rc"] = container_rc
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
    2026-10-08): the session/host override (NO-OP-PASS, LOOP-TRAP) wins;
    otherwise the derived table. INTEGRITY-FAIL is NOT here — the host sets
    it after build_summary, in _publish_evidence. test_verdict_table.py
    pins this priority: any change here must pass it UNCHANGED."""
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

    # Provenance (W2.6): the exact commit the run started from.
    commit_sha = None
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cfg.repo_root,
                             capture_output=True, text=True, timeout=10)
        if out.returncode == 0 and out.stdout.strip():
            commit_sha = out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass

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


def write_summary(cfg, run_state, job: dict, elapsed_s: int) -> None:
    """Writes the exact summary.json contract expected by the L1 Supervisor."""
    with open(os.path.join(run_state.evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, elapsed_s), f, ensure_ascii=False, indent=2)

