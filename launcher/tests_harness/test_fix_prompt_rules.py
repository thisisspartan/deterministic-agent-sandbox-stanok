"""verify_gate rc=124 classification + fix-prompt rule selection.

A hung test (run.sh rc=124) must be tagged TIMEOUT in _run_one_test and
must NOT receive the generic "fix src exclusively" fix-prompt block: that
wording is a retry-loop DoS (the model iterates on src/, the test hangs
again, verify_gate fails again with the same prompt).

Rule priority in _fix_prompt_rules: list-fail > timeout > no-tests > generic.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_fix_prompt_rules.py -q
"""
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402

from conftest import repo, write

STUB_HUNG = "#!/usr/bin/env bash\necho stub-hung\nexit 124\n"


def test_run_one_test_tags_rc124_as_timeout(repo, monkeypatch):
    write(repo / "scripts" / "run.sh", STUB_HUNG)
    write(repo / "tests" / "hang.test.js", "stub")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    res = stanok._run_one_test("tests/hang.test.js")
    assert res is not None
    assert res[1].startswith("TIMEOUT:")
    assert "rc=124" in res[1]


def test_fix_prompt_rules_timeout_branch():
    rules = stanok._fix_prompt_rules(
        [("tests/hang.test.js", "TIMEOUT: test hung (rc=124) — stub-hung")])
    assert "HUNG" in rules
    assert "NOT a red assertion" in rules
    # The generic "fix src exclusively" block must NOT be selected.
    assert "EXCLUSIVELY in the module implementations" not in rules


def test_fix_prompt_rules_priority_list_over_timeout():
    rules = stanok._fix_prompt_rules([
        ("(list)", "list failed: unclaimed test-like file"),
        ("tests/hang.test.js", "TIMEOUT: test hung (rc=124) — stub-hung"),
    ])
    assert "list" in rules
    assert "unclaimed" in rules
    assert "HUNG" not in rules


def test_fix_prompt_rules_generic_unchanged():
    rules = stanok._fix_prompt_rules(
        [("tests/a.test.js", "FAIL: assertion error")])
    assert "EXCLUSIVELY in the module implementations" in rules
    assert "HUNG" not in rules
