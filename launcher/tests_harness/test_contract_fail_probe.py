"""CONTRACT-FAIL as a probe_result value (operator review 2026-10-09).

The gap: _contract_lock_forced_fail set verifier=FAIL + rc=1 but no
probe_result, so decide() fell through to the table and the summary said
VERIFY-FAIL — a contract violation was indistinguishable from a test
failure, and the acceptance ("live negative expects CONTRACT-FAIL") could
not be met.

The mechanism (by the NO-OP-PASS / LOOP-TRAP pattern — an override, the
decide() table is UNCHANGED):
  1. _contract_lock_forced_fail sets job["probe_result"] = "CONTRACT-FAIL".
  2. Override priority (operator review 2026-10-09): probe_result is ONE key,
     so without an explicit rule the later write wins. decide() states the
     rule: non-empty contract_lock_violations -> CONTRACT-FAIL, outranking
     every behavioral override (LOOP-TRAP, NO-OP-PASS) regardless of write
     order — CONTRACT-FAIL describes verdict integrity, LOOP-TRAP only model
     behavior.

Tests:
  1  _contract_lock_forced_fail sets probe_result CONTRACT-FAIL
  2  clean run: no probe_result set
  3  build_summary keeps the override (not VERIFY-FAIL)
  4  wiring: _post_turn_decision with a new zone symlink -> rc=1 AND
     probe_result CONTRACT-FAIL (the end-to-end path)
  5  priority: contract_lock_violations outrank a LOOP-TRAP override written
     FIRST (operator review 2026-10-09: integrity of the verdict beats model
     behavior)
  6  priority: same when LOOP-TRAP is written SECOND (_loop_trap_verdict
     overwrites the probe_result key — decide()'s rule, not the write order,
     decides)
  7  trust boundary (GAP closed by stage 3, T3-1/T3-2): the host snapshots
     the protected files before the run and recomputes after it
     (verify.contract_snapshot + host_contract_check — the run_sandboxed call
     site); a forged clean summary (rc=0, PASS, empty violations) over a
     tampered tree is rejected: _publish_evidence forces CONTRACT-FAIL.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_contract_fail_probe.py -q
"""
import json

from launcher import session, summary, verify
from launcher.config import Config
from launcher.gates import zone_symlinks
from launcher.plan import SessionPlan


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "launcher").mkdir()
    (repo / "launcher" / "target.txt").write_text("regular file\n")
    return repo, Config(repo_root=str(repo))


# --- 1-2: the override is set by the forced-FAIL path ---------------------------

def test_forced_fail_sets_probe_result_contract_fail():
    job = {"contract_lock_violations": ["turn 1: MODIFIED: tests/t_test.py"]}
    assert verify._contract_lock_forced_fail(job, 1) == 1
    assert job["probe_result"] == "CONTRACT-FAIL"
    assert job["verifier"] == "FAIL"


def test_forced_fail_clean_sets_nothing():
    job = {"verifier": "PASS"}
    assert verify._contract_lock_forced_fail(job, 2) is None
    assert "probe_result" not in job


# --- 3: decide()/build_summary keep the override (the table is unchanged) ------

def test_build_summary_keeps_contract_fail_override():
    job = {"rc": 1, "verifier": "FAIL", "turns": 2,
           "probe_result": "CONTRACT-FAIL",
           "contract_lock_violations": ["turn 2: NEW-SYMLINK: src/link"]}
    assert summary.build_summary(Config(), job, 0)["probe_result"] == "CONTRACT-FAIL"


# --- 4: wiring — the live-negative path end to end ------------------------------

def test_post_turn_decision_sets_contract_fail_probe_result(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    before = zone_symlinks(cfg)
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    # verify_gate must never run on a tampered tree — the stub is a guard.
    monkeypatch.setattr(session, "verify_gate", lambda cfg, plan: (True, [], False))
    plan = SessionPlan(declared_paths=(), edit_paths=())
    result = session.TurnResult(usage={}, live_window={}, writes=1, error="",
                                loop_trap=None)
    job = {"turn_telemetry": [{"input_tokens": 100}]}
    rc, _ = session._post_turn_decision(
        cfg, job, 1, 3, plan, result, {}, before, 100, 100)
    assert rc == 1
    assert job["probe_result"] == "CONTRACT-FAIL"
    assert job["verifier"] == "FAIL"
    # The published summary would carry CONTRACT-FAIL, not VERIFY-FAIL.
    assert summary.build_summary(cfg, job, 0)["probe_result"] == "CONTRACT-FAIL"


# --- 5-6: the host must not downgrade CONTRACT-FAIL -----------------------------

def _publish_tree(tmp_path, label, summary_dict):
    repo = tmp_path / "repo"
    logdir = tmp_path / "logs"
    live = logdir / label
    live.mkdir(parents=True)
    (live / "summary.json").write_text(json.dumps(summary_dict), encoding="utf-8")
    return repo, logdir


def _published(repo, label):
    return json.loads(
        (repo / "evidence" / label / "summary.json").read_text(encoding="utf-8"))


# --- 5-6: override priority — violations beat LOOP-TRAP in BOTH write orders ----

_LOOP = {"tool": "Bash", "hash": "abc", "n": 5}


def test_contract_fail_outranks_loop_trap_written_first():
    # LOOP-TRAP written first (the hook path), violations present.
    job = {"rc": 1, "verifier": "FAIL", "turns": 1, "probe_result": "LOOP-TRAP",
           "loop_trap": _LOOP,
           "contract_lock_violations": ["turn 1: NEW-SYMLINK: src/link"]}
    assert summary.build_summary(Config(), job, 0)["probe_result"] == "CONTRACT-FAIL"


def test_contract_fail_outranks_loop_trap_written_second():
    # CONTRACT-FAIL set first, then _loop_trap_verdict overwrites the single
    # probe_result key with LOOP-TRAP — decide()'s rule, not the write order,
    # decides. The loop_trap detail field is kept alongside the verdict.
    job = {"rc": 1, "verifier": "FAIL", "turns": 1,
           "probe_result": "CONTRACT-FAIL",
           "contract_lock_violations": ["turn 1: MODIFIED: tests/t_test.py"]}
    assert session._loop_trap_verdict(job, _LOOP) == 1
    assert job["probe_result"] == "LOOP-TRAP"  # the key was overwritten...
    s = summary.build_summary(Config(), job, 0)
    assert s["probe_result"] == "CONTRACT-FAIL"  # ...the verdict is not
    assert job["loop_trap"] == _LOOP  # the loop detail survives alongside
    assert s["contract_lock_violations"] == ["turn 1: MODIFIED: tests/t_test.py"]


# --- 7: the trust boundary — GAP closed by stage 3 (T3-1/T3-2/T3-6) ------------
# The gap (operator review 2026-10-09): the host trusted the container's
# summary — a worker that rewrote summary.json after the run (rc=0, PASS,
# empty violations) over a tree where a protected file was actually modified
# was published untouched. Stage 3 closed it: run_sandboxed snapshots the
# protected files BEFORE `docker run` (T3-1, host process memory only),
# recomputes after the container exits (T3-2, host_contract_check) and hands
# the violations to _publish_evidence, which forces CONTRACT-FAIL regardless
# of the worker's claims. The end-to-end path through run_sandboxed is
# pinned in test_stage3_fresh_wiring.py::test_fresh_skipped_when_contract_
# violated; this test pins the unit boundary of the host call site.

def test_host_detects_forged_clean_summary_over_tampered_tree(tmp_path):
    repo, logdir = _publish_tree(tmp_path, "lbl", {
        "rc": 0, "verifier": "PASS", "probe_result": "CLEAN-FIRST",
        "contract_lock_violations": []})
    cfg = Config(repo_root=str(repo), log_dir=str(logdir))
    # T3-1: the pre-run snapshot — the protected file must EXIST at snapshot
    # time (a new file is only allowed if declared: _compare_manifests, T3-9).
    (repo / "tests").mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                              encoding="utf-8")
    before = verify.contract_snapshot(cfg)
    # The worker tampers with the tree and claims a clean first-pass run.
    (repo / "tests" / "t_test.py").write_text("tampered after snapshot\n",
                                              encoding="utf-8")
    # T3-2: the host's independent recompute (the run_sandboxed call site).
    violations = verify.host_contract_check(cfg, before, ())
    assert violations == ["MODIFIED: tests/t_test.py"]
    summary._publish_evidence(cfg, "lbl", 0, violations)
    dst = _published(repo, "lbl")
    # The forged verdict is rejected: the host's recompute outranks the
    # worker's claims (spec priority CONTRACT-FAIL > everything).
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert dst["contract_lock_violations"] == ["MODIFIED: tests/t_test.py"]
