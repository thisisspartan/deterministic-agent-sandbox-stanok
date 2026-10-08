"""Characterization table for the verdict derivation (red-team review
2026-10-08, item 2).

Pins the CURRENT probe_result of build_summary() for every branch, including
the documented probe_result override — summary.py states the override already
broke a pure rc->fields table and forbids "restoring" one. This test
describes real behavior, not expectations: a future decide() refactor is
correct only if this table passes UNCHANGED and the docstring is updated in
the same diff.
"""
from launcher import summary
from launcher.config import Config


def _probe(job):
    # build_summary needs a Config only for the provenance git call; the
    # verdict table itself is cfg-independent.
    return summary.build_summary(Config(), job, 0)["probe_result"]


def test_clean_first():
    assert _probe({"rc": 0, "verifier": "PASS", "turns": 1}) == "CLEAN-FIRST"


def test_pass_after_local_retry():
    assert _probe({"rc": 0, "verifier": "PASS", "turns": 2}) == "PASS-AFTER-LOCAL-RETRY"


def test_verify_fail_on_rc1():
    assert _probe({"rc": 1, "verifier": "FAIL", "turns": 3}) == "VERIFY-FAIL"


def test_fail_closed_rc0_without_pass():
    assert _probe({"rc": 0, "verifier": "FAIL", "turns": 1}) == "VERIFY-FAIL"


def test_fail_closed_no_pass_on_fail_rc():
    # rc=1 with verifier PASS is still a defect (no PASS-on-FAIL)
    assert _probe({"rc": 1, "verifier": "PASS", "turns": 1}) == "VERIFY-FAIL"


def test_env_fail():
    assert _probe({"rc": 16, "verifier": "FAIL", "turns": 1}) == "ENV-FAIL"


def test_noop_pass_override():
    # rc=1 is polysemous: disambiguated by probe_result, not rc
    assert _probe({"rc": 1, "verifier": "PASS", "turns": 1,
                   "probe_result": "NO-OP-PASS"}) == "NO-OP-PASS"


def test_loop_trap_override():
    assert _probe({"rc": 1, "verifier": "FAIL", "turns": 1,
                   "probe_result": "LOOP-TRAP"}) == "LOOP-TRAP"


def test_integrity_fail_override():
    assert _probe({"rc": 1, "verifier": "FAIL", "turns": 1,
                   "probe_result": "INTEGRITY-FAIL"}) == "INTEGRITY-FAIL"
