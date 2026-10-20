"""summary — the verdict artifacts: summary.json, failures.log, evidence
publishing, rotation.

CC-237 (schema v2, operator decision 2026-10-11): summary.json is TYPED —
scalars and structured fields only, no free text. The allowlist:
  label, ticket, rc, verifier, probe_result, turns, elapsed_s, session_id,
  commit_sha, tokens, cache_hit_rate, inference_telemetry, tool_activity,
  loop_trap, test_fit, acceptance, compactions, opik_traces  (+ patch_sha256,
  image_digest,
  host-stamped in k8s mode — k8s.py: the Pod's containerStatuses imageID,
  None when unavailable).
  test_fit = {"edits_after_green": int>=0, "new_tests_after_green": int>=0}
  — CC-247 proxy counters (no gate); malformed -> zeros.
  acceptance = {"mode": "provided"|"none"|"undeclared", "paths": [str]}
  — G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): the ticket's acceptance-
  contract state (no gate); malformed -> {"mode": "undeclared", "paths": []}.
  loop_trap = {"tool": str, "hash": str, "n": int} | None — the typed
  circuit-breaker record (the protocol reads it as LOOP-TRAP).
All free text of a run (the error string, verify_gate failures, contract-lock
violations, host-issued CONTRACT-FAIL/FRESH-FAIL explanations) moves to
failures.log — one line per failure, plain text. test_summary_schema.py pins
the allowlist and the types.

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
from collections.abc import Sequence  # read-only parameter type: callers pass a list, the default is () — the function only unpacks/logs it
from launcher.exitcodes import ExitCode
from launcher.logs import log


def _publish_evidence(cfg, label: str, container_rc: int,
                      contract_violations: Sequence[str] = (),
                      fresh_check: tuple | None = None) -> None:
    """Copy the container-written verdict from the rw LOG_DIR/<label> into the
    host-owned evidence/<label> (CC-134).

    Called by the host supervision (k8s.host_launch_k8s) after the container
    has exited — the container has no rw view of evidence/, so the host is
    the only publisher. Missing files are skipped: an aborted launch
    publishes nothing rather than a fake verdict.

    S2 (PLAN-SIMPLIFY-2026-10-09): the I5 rc cross-check, the worker_*
    fields and the INTEGRITY-FAIL value are REMOVED from THIS function. The
    host's authority is its two independent checks only — the contract
    recompute and the fresh check; the worker's summary passes through
    untouched when neither fires. The verdict is a statement about the TREE
    (suite green + tree = declared), not about the worker's self-report.
    The S2 "sanctioned gap" (a pure forgery — claims PASS while the session
    exited non-zero) is CLOSED in the k8s mode by the internal_rc contract
    (external review 2026-10-16): pod_runner ships the in-Pod session's own
    exit code in internal_rc.txt and the host compares it against
    summary.json's "rc" before ever publishing — a contradiction is
    verdict-substitution, an infrastructure defect (k8s.host_launch_k8s,
    "Verdict cross-check", rc=16). An image predating the contract ships no
    internal_rc.txt: no check (doc-pass 2026-10-20; the old "no longer
    caught" text predated the cross-check).

    Stage 3 (T3-2) `contract_violations`: the host's own recompute of the
    protected-files manifest (verify.host_contract_check against the pre-run
    snapshot). Non-empty means the tree the verdict was computed against was
    tampered with — the host forces verifier=FAIL + probe_result=CONTRACT-FAIL
    regardless of what the worker summary claims (the judge is not the
    defendant).

    Stage 3 (T3-5): the final verifier/rc/probe_result are issued by the HOST
    with the priority CONTRACT-FAIL > FRESH-FAIL > the worker's claims.
    `fresh_check=(rc, tail)` is the host's independent fresh check result
    (the k8s deny-all Job, T3-3; the Docker-era verify.fresh_verify is gone
    with the Docker path, CC-258); a non-zero fresh rc forces
    verifier=FAIL + probe_result=FRESH-FAIL + rc=fresh rc, the tail appended
    to errors. fresh_check=None = not run."""
    src = os.path.join(cfg.log_dir, label)
    files = ("summary.json", "launcher.stdout.log", "failures.log")
    # The gate stays summary.json-only: a run that died before writing its
    # verdict publishes nothing (status "missing" — an aborted run, not a
    # verdict); a stray failures.log must not half-publish it.
    if not os.path.isfile(os.path.join(src, "summary.json")):
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
        # CC-237 (schema v2): the free text goes to failures.log, not to
        # summary.json — the typed fields (verifier/rc/probe_result) are
        # forced here, the explanation is appended to the log.
        _append_failures(dst, [
            "HOST CONTRACT-LOCK: the tree was tampered with after the "
            "pre-run snapshot — the verdict was computed against modified "
            "protected files", *contract_violations])
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
        # CC-237 (schema v2): the explanation goes to failures.log.
        _append_failures(dst, [
            f"HOST FRESH-CHECK: the suite failed in a fresh container the "
            f"worker never touched (rc={fresh_rc}): {tail}"])
        with open(sum_dst, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        log(f"FRESH-CHECK: {label}: fresh verify rc={fresh_rc} — "
            "verdict FRESH-FAIL")


def _loop_trap_field(job: dict):
    """CC-237 (schema v2): the typed circuit-breaker record —
    {"tool": str, "hash": str, "n": int} | None. The marker file may carry
    extra keys (ts) or malformed values; anything that is not exactly the
    typed triple publishes None (the protocol reads None as "no trap")."""
    trap = job.get("loop_trap")
    if not isinstance(trap, dict):
        return None
    tool, hash_, n = trap.get("tool"), trap.get("hash"), trap.get("n")
    if (isinstance(tool, str) and isinstance(hash_, str)
            and isinstance(n, int) and not isinstance(n, bool)):
        return {"tool": tool, "hash": hash_, "n": n}
    return None


def _acceptance_field(job: dict) -> dict:
    """G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): the typed acceptance-
    contract record — {"mode": "provided"|"none"|"undeclared",
    "paths": [str]}. mode=provided requires a non-empty paths list; mode=none
    requires an empty one. Anything malformed publishes the default
    {"mode": "undeclared", "paths": []} — the protocol reads undeclared as
    "no independent acceptance evidence was declared", never as presence."""
    default = {"mode": "undeclared", "paths": []}
    acc = job.get("acceptance")
    if not isinstance(acc, dict):
        return default
    mode, paths = acc.get("mode"), acc.get("paths")
    if mode not in ("provided", "none", "undeclared"):
        return default
    if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths):
        return default
    if (mode == "provided") != bool(paths):
        return default
    return {"mode": mode, "paths": list(paths)}


def _test_fit_field(job: dict) -> dict:
    """CC-247: the typed test-fit counters —
    {"edits_after_green": int>=0, "new_tests_after_green": int>=0}. Proxy
    metric only: no gate, no text. Anything malformed (negative, bool, str,
    missing key, not a dict) publishes zeros — the protocol reads zeros as
    "no signal"."""
    zeros = {"edits_after_green": 0, "new_tests_after_green": 0}
    fit = job.get("test_fit")
    if not isinstance(fit, dict):
        return zeros
    out = {}
    for key in ("edits_after_green", "new_tests_after_green"):
        v = fit.get(key)
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            return zeros  # a partial/malformed record is not a signal
        out[key] = v
    return out


def _compactions_field(job: dict) -> list:
    """P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20): the typed
    compact_boundary record — [{"turn": int>=1, "trigger": str,
    "pre_tokens": int>=0}]. The token totals deliberately exclude
    compaction API calls; without this field an autocompact was invisible
    in the verdict (cc304: ~83 s of summarisation, zero trace in
    summary.json). Metric only: no gate, no text. Missing/not-a-list
    publishes [] ("no signal"); an individually malformed entry is
    dropped, valid entries survive."""
    raw = job.get("compactions")
    if not isinstance(raw, list):
        return []
    out = []
    for e in raw:
        if not isinstance(e, dict):
            continue
        turn, pre, trigger = e.get("turn"), e.get("pre_tokens"), e.get("trigger")
        bad = (
            not isinstance(turn, int) or isinstance(turn, bool) or turn < 1
            or not isinstance(pre, int) or isinstance(pre, bool) or pre < 0
            or not isinstance(trigger, str)
        )
        if not bad:
            out.append({"turn": turn, "trigger": trigger, "pre_tokens": pre})
    return out


def _failure_lines(job: dict) -> list[str]:
    """CC-237 (schema v2): every free-text failure of a run as plain lines —
    the error string, verify_gate failures (verify.py entries are
    (name, msg) tuples or plain strings), contract-lock violations.
    summary.json stays typed; failures.log carries the text."""
    lines = []
    if job.get("error"):
        lines.append(str(job["error"]))
    for f in job.get("failures", []):
        if isinstance(f, (tuple, list)) and len(f) == 2:
            lines.append(f"{f[0]}: {f[1]}")
        else:
            lines.append(str(f))
    lines.extend(str(v) for v in job.get("contract_lock_violations", []))
    return lines


def _write_failures(directory: str, lines: list[str]) -> None:
    """Write failures.log — one line per failure, plain text. No lines ->
    no file: a clean run has no failures.log (the publish gate skips
    missing files)."""
    if not lines:
        return
    with open(os.path.join(directory, "failures.log"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _append_failures(directory: str, lines: list[str]) -> None:
    """Append host-issued failure lines to failures.log (create if absent) —
    used by _publish_evidence for CONTRACT-LOCK / FRESH-CHECK."""
    if not lines:
        return
    with open(os.path.join(directory, "failures.log"), "a", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")


def _rotate_stale_summary(cfg, label: str) -> None:
    """Rotate a stale summary.json / failures.log left by an EARLIER run of
    the same label (a run aborted at a gate after writing its report, or a
    killed process). Without rotation, early_abort's write-if-absent guard
    would keep the OLD report and the supervisor would read a verdict from
    the previous run; a stale failures.log would receive the next run's
    host-appended lines (CC-237). Only rotate when no `.running` marker is
    present: a live run's evidence must not be touched."""
    evidence_dir, _ = cfg.label_paths(label)
    marker = os.path.join(evidence_dir, ".running")
    if os.path.exists(marker):
        return
    for name in ("summary.json", "failures.log"):
        p = os.path.join(evidence_dir, name)
        if os.path.isfile(p):
            try:
                os.replace(p, p + ".prev")
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
        # CC-234: the agent's own tooling activity — bash_ok==0 with a
        # verifier PASS is a PASS-BLIND verdict, not a clean acceptance.
        "tool_activity": job.get("tool_activity", {"bash_total": 0, "bash_ok": 0}),
        # CC-237 (schema v2): the typed circuit-breaker record; free text
        # (error / verify failures / contract violations) goes to
        # failures.log via _write_failures, never into summary.json.
        "loop_trap": _loop_trap_field(job),
        # CC-247: the test-fit proxy counters (typed, no gate) — test-file
        # edits after the first observed green vs new test files after it.
        "test_fit": _test_fit_field(job),
        # G4: the acceptance-contract state (typed, no gate) — whether the
        # final PASS was backed by trusted pre-existing acceptance checks.
        "acceptance": _acceptance_field(job),
        # P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20): the typed
        # compact_boundary record (no gate) — makes autocompact visible in
        # the verdict; token totals stay untouched (they already exclude it).
        "compactions": _compactions_field(job),
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
    # CC-237 (schema v2): the run's free text goes to failures.log.
    _write_failures(d, _failure_lines(job))


def write_env_fail_summary(cfg, label: str, error: str) -> None:
    """Stage 3 (T3-6): a host-side infrastructure failure — the fresh check
    could not run (EXEC_ERROR). The verdict cannot be issued: the host writes
    an ENV-FAIL summary (rc=16) into the evidence dir, the error text in
    failures.log (CC-237) — not a verdict, call the human."""
    evidence_dir, _ = cfg.label_paths(label)
    os.makedirs(evidence_dir, exist_ok=True)
    job = {"label": label, "rc": int(ExitCode.ENV_FAIL), "verifier": "FAIL",
           "probe_result": "ENV-FAIL", "turns": 0, "error": error}
    with open(os.path.join(evidence_dir, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(build_summary(cfg, job, 0), f, ensure_ascii=False, indent=2)
    _write_failures(evidence_dir, [error])

