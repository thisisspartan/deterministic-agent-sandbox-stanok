"""BL-8 (2026-10-16): the empty-answer turn loop — pinned contract, no prod change.

Question (operator, after BL-6-C: 3/10 identical probes returned an empty
content at finish=length): what does the next turn receive if the model's
answer is empty? Verified by reading the code first: TurnResult has NO answer
field (session.py:252-285) — the model's text is only streamed to the jsonl
log, never used in the verdict pipeline; _fix_prompt(failures, turn)
(session.py:578-595) is built ONLY from verify_gate failure blocks +
contract_lock rules. So an empty answer cannot reach the next prompt at all.

What these tests pin (the boundedness the question was really about):
  1. a zero-tool-call turn with a failing suite continues with a NON-EMPTY
     diagnosis-shaped fix prompt derived from the failures — not from the
     model's output;
  2. the loop is bounded by max_turns, not by the LOOP-TRAP (the trap only
     fires on 5 identical tool calls; a zero-tool-call turn never trips it):
     at turn == max_turns the decision returns ("", exhausted) and the run
     ends VERIFY-FAIL (session.py:686-687, 989-991).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_empty_answer_loop.py -q
"""
from launcher import session
from launcher.session import TurnResult


def _stub_gates(monkeypatch, failures):
    monkeypatch.setattr(session, "_check_contract_lock", lambda *a: None)
    monkeypatch.setattr(session, "_observability_warnings", lambda *a: None)
    monkeypatch.setattr(session, "_contract_lock_forced_fail",
                        lambda job, turn: None)
    monkeypatch.setattr(session, "verify_gate",
                        lambda cfg, plan: (False, failures, False))


def _empty_answer_result():
    # finish=length with empty content: no Write/Edit/Bash tool_use at all —
    # the turn is clean (error==""), it simply did nothing.
    return TurnResult(usage={}, live_window={}, writes=0, error="",
                      loop_trap=None, bash_total=0, bash_ok=0)


def test_empty_answer_turn_gets_diagnosis_prompt_not_an_empty_replay(monkeypatch):
    _stub_gates(monkeypatch, [("suite", "FAILED tests/x_test.py::test_x")])
    job = {"label": "lbl"}
    rc, nxt = session._post_turn_decision(
        None, job, 1, 3, None, _empty_answer_result(), {}, 0, 0)
    assert rc is None  # continue — the turn budget is not exhausted
    assert nxt != ""
    # the prompt is diagnosis-shaped: built from the failures, never from
    # any model text (there is no model text in the pipeline to begin with)
    assert '<verification_result status="FAIL"' in nxt
    assert 'FAILED tests/x_test.py::test_x' in nxt
    assert "<contract_lock>" in nxt
    assert "verifier" not in job  # the FAIL branch records failures only
    assert job["failures"] == [("suite", "FAILED tests/x_test.py::test_x")]


def test_zero_tool_call_loop_is_bounded_by_max_turns_not_by_loop_trap(monkeypatch):
    # The LOOP-TRAP cannot fire here (no identical tool calls — no tool
    # calls at all); the bound is max_turns: at the last allowed turn the
    # decision returns (None, "") and run_continuous_session finishes rc=1.
    _stub_gates(monkeypatch, [("suite", "FAILED tests/x_test.py::test_x")])
    job = {"label": "lbl"}
    rc, nxt = session._post_turn_decision(
        None, job, 3, 3, None, _empty_answer_result(), {}, 0, 0)
    assert rc is None and nxt == ""  # Context Inertia Guard: no prompt left
    # run_continuous_session then sets verifier/turns and returns 1 (:989-991)
    assert "verifier" not in job
