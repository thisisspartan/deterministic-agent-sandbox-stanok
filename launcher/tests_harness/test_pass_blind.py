"""CC-234 (operator spec 2026-10-11): the Bash-success metric + PASS-BLIND.

Incident cc231/cc233: the agent's Bash was dead in the Pod, yet the
in-process verifier hook greened the suite and the run published
CLEAN-FIRST. Rule: a verifier PASS with ZERO successful Bash calls by the
agent is NOT a clean acceptance — probe_result is demoted to PASS-BLIND
(rc/verifier stay as measured; decide() carries the override).

These tests drive _post_turn_decision with the gate/lock helpers stubbed —
the demotion logic only, no containers.
"""
from launcher import session, summary
from launcher.session import TurnResult


def _stub_gates(monkeypatch, verify_ok=True):
    monkeypatch.setattr(session, "_check_contract_lock", lambda *a: None)
    monkeypatch.setattr(session, "_observability_warnings", lambda *a: None)
    monkeypatch.setattr(session, "_contract_lock_forced_fail",
                        lambda job, turn: None)
    monkeypatch.setattr(session, "verify_gate",
                        lambda cfg, plan: (verify_ok, [], False))


def _result(bash_total, bash_ok, writes=1):
    return TurnResult(usage={}, live_window={}, writes=writes, error="",
                      loop_trap=None, bash_total=bash_total, bash_ok=bash_ok)


def _run_turn(job, result):
    """The real flow: telemetry aggregates tool_activity, then the decision."""
    total = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    session._record_turn_telemetry(job, total, result, 1, 1.0)


def test_pass_with_zero_bash_ok_is_demoted_pass_blind(monkeypatch):
    _stub_gates(monkeypatch)
    job = {"label": "lbl"}
    _run_turn(job, _result(bash_total=3, bash_ok=0))
    rc, nxt = session._post_turn_decision(
        None, job, 1, 1, None, _result(bash_total=3, bash_ok=0), {}, 0, 0)
    assert rc == 0 and nxt == ""  # the measured verdict stays as measured
    assert job["verifier"] == "PASS"
    assert job["probe_result"] == "PASS-BLIND"
    assert summary.decide(job) == "PASS-BLIND"  # the override wins in the summary


def test_pass_with_never_attempted_bash_is_also_blind(monkeypatch):
    # bash_total==0: the agent never ran the entrypoint itself — same class.
    _stub_gates(monkeypatch)
    job = {"label": "lbl"}
    _run_turn(job, _result(bash_total=0, bash_ok=0))
    rc, _ = session._post_turn_decision(
        None, job, 1, 1, None, _result(bash_total=0, bash_ok=0), {}, 0, 0)
    assert rc == 0
    assert job["probe_result"] == "PASS-BLIND"


def test_pass_with_successful_bash_stays_clean_first(monkeypatch):
    _stub_gates(monkeypatch)
    job = {"label": "lbl"}
    _run_turn(job, _result(bash_total=3, bash_ok=2))
    rc, _ = session._post_turn_decision(
        None, job, 1, 1, None, _result(bash_total=3, bash_ok=2), {}, 0, 0)
    assert rc == 0
    assert "probe_result" not in job  # no override -> the derived table
    job["rc"] = 0  # what cli does with the returned rc
    assert summary.decide(job) == "CLEAN-FIRST"


def test_no_op_assert_unchanged_and_precedes_blind(monkeypatch):
    # W2.4 order preserved: turn-1 PASS with zero Write/Edit = NO-OP-PASS,
    # even when Bash is also dead.
    _stub_gates(monkeypatch)
    job = {"label": "lbl"}
    _run_turn(job, _result(bash_total=0, bash_ok=0, writes=0))
    rc, _ = session._post_turn_decision(
        None, job, 1, 1, None,
        _result(bash_total=0, bash_ok=0, writes=0), {}, 0, 0)
    assert rc == 1
    assert job["probe_result"] == "NO-OP-PASS"


def test_record_turn_telemetry_aggregates_tool_activity():
    job = {"label": "lbl"}
    total = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    session._record_turn_telemetry(job, total, _result(bash_total=3, bash_ok=1),
                                  1, 1.0)
    session._record_turn_telemetry(job, total, _result(bash_total=2, bash_ok=2),
                                  2, 1.0)
    assert job["tool_activity"] == {"bash_total": 5, "bash_ok": 3}
    per_turn = job["turn_telemetry"]
    assert per_turn[0]["bash_total"] == 3 and per_turn[0]["bash_ok"] == 1
    assert per_turn[1]["bash_total"] == 2 and per_turn[1]["bash_ok"] == 2


def test_build_summary_publishes_tool_activity():
    from launcher.config import Config
    job = {"label": "lbl", "rc": 0, "verifier": "PASS", "turns": 1,
           "probe_result": "PASS-BLIND",
           "tool_activity": {"bash_total": 4, "bash_ok": 0}}
    s = summary.build_summary(Config(repo_root="/unused"), job, 1)
    assert s["probe_result"] == "PASS-BLIND"
    assert s["tool_activity"] == {"bash_total": 4, "bash_ok": 0}
    # a run without a session (gate-aborted) still carries the field shape
    s2 = summary.build_summary(Config(repo_root="/unused"),
                               {"label": "x", "rc": 1, "verifier": "FAIL"}, 0)
    assert s2["tool_activity"] == {"bash_total": 0, "bash_ok": 0}
