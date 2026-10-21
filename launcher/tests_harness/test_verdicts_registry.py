"""#314 (2026-10-21): launcher.verdicts — the single registry of the
published probe_result vocabulary. Tests:

1. Drift guard: no bare wire-value string constants in launcher/*.py code
   (docstrings and test files are exempt — the test layer pins wire values
   on the consumer side by design). A producer site must use Verdict.X.value.
2. decide() emits only registry values (derived table, override
   passthrough, contract-lock priority).
3. Registry x aggregate.classify cross-check: each documented (rc, verifier)
   pairing yields the documented outcome (PAIRINGS/EXPECTED below, mirrored
   from the verdicts.py docstring).
4. NO-OP real-pairing regression (#314 defect): evidence-shaped
   rc=1+PASS with probe NO-OP-PASS (the pairing session._post_turn_decision
   actually publishes, pinned by test_pass_blind.py:81) classifies NO-OP,
   not DEFECT.
5. Forward consistency: every ExitCode except DEFECT is in
   aggregate.INFRA_RCS; the only unexplained extra is 14 (documented legacy,
   not defined in exitcodes.py).
6. Wire-value stability: the registry value set is protocol — a rename fails
   here, and values serialize as plain str (Pod Python 3.11: a str-Enum in
   json.dumps must not change the wire form).
"""
import ast
import json
from pathlib import Path

from launcher import aggregate, summary
from launcher.exitcodes import ExitCode
from launcher.verdicts import Verdict

WIRE_VALUES = {v.value for v in Verdict}

# --- 1. drift guard: no bare wire literals at producer sites -----------------

LAUNCHER_DIR = Path(__file__).resolve().parent.parent


def _producer_files():
    """launcher/*.py (top level, not tests_harness/), except verdicts.py
    itself — the registry is the only allowed home of the wire strings."""
    return sorted(p for p in LAUNCHER_DIR.glob("*.py")
                  if p.name != "verdicts.py")


def _bare_wire_constants(path: Path) -> list[tuple[int, str]]:
    """ast.Constant str nodes equal to a wire value, excluding docstrings /
    bare expression statements (prose may name the vocabulary)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    prose = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            prose.add(id(node.value))
    return [(node.lineno, node.value)
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str) and node.value in WIRE_VALUES
            and id(node) not in prose]


def test_no_bare_wire_literals_in_producer_code():
    offenders = {f.name: _bare_wire_constants(f) for f in _producer_files()}
    offenders = {k: v for k, v in offenders.items() if v}
    assert offenders == {}, (
        f"bare probe_result wire literals at producer sites (use "
        f"Verdict.X.value instead): {offenders}")


def test_guard_detects_a_bare_literal_red() -> None:
    """Calibration of the guard itself: RED on a bad file, GREEN on the
    clean tree (rule: a new oracle is calibrated RED-on-bad first)."""
    red = _producer_files()[0]
    src = red.read_text(encoding="utf-8")
    try:
        red.write_text(src + '\njob = {"probe_result": "NO-OP-PASS"}\n',
                       encoding="utf-8")
        hits = _bare_wire_constants(red)
        assert any(v == "NO-OP-PASS" for _, v in hits)
    finally:
        red.write_text(src, encoding="utf-8")
    assert _bare_wire_constants(red) == []


# --- 2. decide() emits only registry values ----------------------------------

def test_decide_derived_table_emits_registry_values():
    assert summary.decide({"rc": 0, "verifier": "PASS", "turns": 1}) == \
        Verdict.CLEAN_FIRST.value
    assert summary.decide({"rc": 0, "verifier": "PASS", "turns": 2}) == \
        Verdict.PASS_AFTER_LOCAL_RETRY.value
    assert summary.decide({"rc": 16, "verifier": "FAIL", "turns": 1}) == \
        Verdict.ENV_FAIL.value
    assert summary.decide({"rc": 1, "verifier": "FAIL", "turns": 3}) == \
        Verdict.VERIFY_FAIL.value


def test_decide_override_passthrough_emits_registry_values():
    for probe in (Verdict.NO_OP_PASS, Verdict.LOOP_TRAP, Verdict.PASS_BLIND,
                  Verdict.CONTRACT_FAIL, Verdict.FRESH_FAIL):
        assert summary.decide({"rc": 1, "probe_result": probe.value}) == \
            probe.value


def test_decide_contract_lock_wins_over_every_override():
    job = {"rc": 0, "verifier": "PASS", "turns": 1,
           "probe_result": Verdict.NO_OP_PASS.value,
           "contract_lock_violations": ["tests/x_test.py"]}
    assert summary.decide(job) == Verdict.CONTRACT_FAIL.value


def test_session_and_host_producers_write_registry_values():
    """The producer sites (session overrides, host-forced FAILs, early
    aborts) emit exactly registry values — verified through the public
    surfaces that publish them."""
    # session._loop_trap_verdict pattern (verify._contract_lock_forced_fail
    # and cli._early_abort are exercised end-to-end by test_loop_trap.py /
    # test_scenarios_verdict.py; here the registry membership is asserted).
    job = {}
    import launcher.session as session
    rc = session._loop_trap_verdict(job, {"tool": "Bash", "hash": "h", "n": 5})
    assert rc == 1 and job["probe_result"] == Verdict.LOOP_TRAP.value
    # summary host-forced writes and ENV-FAIL summary carry registry values
    # via decide(): build a job the way write_env_fail_summary does.
    assert summary.decide({"rc": 16, "verifier": "FAIL", "turns": 0,
                           "probe_result": Verdict.ENV_FAIL.value}) == \
        Verdict.ENV_FAIL.value


# --- 3. registry x classify cross-check (documented pairings) ---------------

# (rc, verifier) as documented in launcher/verdicts.py (measured 2026-10-21;
# FRESH-FAIL: the fresh check's own non-zero exit code — 1 is its common
# value; EARLY-ABORT: an infrastructure ExitCode — 21 (lock) representative).
PAIRINGS = {
    Verdict.CLEAN_FIRST: (0, "PASS"),
    Verdict.PASS_AFTER_LOCAL_RETRY: (0, "PASS"),
    Verdict.VERIFY_FAIL: (1, "FAIL"),
    Verdict.ENV_FAIL: (int(ExitCode.ENV_FAIL), "FAIL"),
    Verdict.NO_OP_PASS: (1, "PASS"),
    Verdict.PASS_BLIND: (0, "PASS"),
    Verdict.LOOP_TRAP: (1, "FAIL"),
    Verdict.CONTRACT_FAIL: (1, "FAIL"),
    Verdict.FRESH_FAIL: (1, "FAIL"),
    Verdict.EARLY_ABORT: (int(ExitCode.LOCK), "FAIL"),
}

# Outcome mapping from the verdicts.py docstring: PASS / NO-OP / DEFECT /
# INFRA (PASS-BLIND keeps the PASS outcome — the subtype carries the
# demotion flag).
EXPECTED = {
    Verdict.CLEAN_FIRST: "PASS",
    Verdict.PASS_AFTER_LOCAL_RETRY: "PASS",
    Verdict.VERIFY_FAIL: "DEFECT",
    Verdict.ENV_FAIL: "INFRA",
    Verdict.NO_OP_PASS: "NO-OP",
    Verdict.PASS_BLIND: "PASS",
    Verdict.LOOP_TRAP: "DEFECT",
    Verdict.CONTRACT_FAIL: "DEFECT",
    Verdict.FRESH_FAIL: "DEFECT",
    Verdict.EARLY_ABORT: "INFRA",
}


def test_every_documented_pairing_classifies_to_the_documented_outcome():
    assert set(PAIRINGS) == set(Verdict) == set(EXPECTED), (
        "the pairing table must cover every registry member")
    for probe in Verdict:
        rc, verifier = PAIRINGS[probe]
        outcome, subtype = aggregate.classify(
            {"rc": rc, "verifier": verifier, "probe_result": probe.value})
        assert (outcome, subtype) == (EXPECTED[probe], probe.value), probe


# --- 4. NO-OP real-pairing regression (#314) --------------------------------

def test_noop_real_evidence_pairing_classifies_noop():
    """The pairing real evidence carries (rc=1 + verifier PASS,
    test_pass_blind.py:81 pins the rc): before #314 the NO-OP branch sat
    under rc==0 and this evidence classified ("DEFECT", "NO-OP-PASS") —
    the declared NO-OP outcome was unreachable from real summaries."""
    assert aggregate.classify(
        {"rc": 1, "verifier": "PASS", "probe_result": "NO-OP-PASS"}) == (
        "NO-OP", "NO-OP-PASS")
    assert aggregate.classify(
        {"rc": 1, "verifier": "PASS", "probe_result":
         Verdict.NO_OP_PASS.value})[:1] == ("NO-OP",)


# --- 5. forward consistency with exitcodes.py -------------------------------

def test_infrastructure_rcs_cover_every_exitcode_except_defect():
    infra_defined = {int(c) for c in ExitCode} - {int(ExitCode.DEFECT)}
    missing = infra_defined - set(aggregate.INFRA_RCS)
    assert not missing, f"ExitCode values absent from aggregate.INFRA_RCS: {missing}"
    extras = set(aggregate.INFRA_RCS) - {int(c) for c in ExitCode}
    # 14 is documented legacy (not defined in exitcodes.py); a NEW
    # unexplained code is a drift the test must catch.
    assert extras <= {14}, f"unexplained rc in aggregate.INFRA_RCS: {extras}"


# --- 6. wire-value stability -------------------------------------------------

def test_registry_values_are_the_published_protocol():
    assert WIRE_VALUES == {
        "CLEAN-FIRST", "PASS-AFTER-LOCAL-RETRY", "VERIFY-FAIL", "ENV-FAIL",
        "NO-OP-PASS", "PASS-BLIND", "LOOP-TRAP", "CONTRACT-FAIL",
        "FRESH-FAIL", "EARLY-ABORT",
    }


def test_values_serialize_as_plain_str_on_the_wire():
    # Pod Python 3.11: a str-Enum must not change json's output form —
    # summary.json stays plain strings (the Python version in the Pod is
    # irrelevant to the wire).
    payload = json.dumps({"probe_result": Verdict.NO_OP_PASS.value})
    assert payload == '{"probe_result": "NO-OP-PASS"}'
    for v in Verdict:
        assert isinstance(v.value, str) and type(v.value) is str
