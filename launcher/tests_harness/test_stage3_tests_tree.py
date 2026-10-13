"""Stage 3 T3-9 — the structural tests/ tree rule (operator decision 2026-10-09).

After the run the set of files under tests/ must equal the snapshot plus the
ticket's declared test files. Any other file is a CONTRACT-FAIL regardless of
its name. The hole (proven live on the public main): the worker creates
tests/colorsys.py; a reference test imports colorsys and gets the fake helper
instead of the stdlib module; the test passes against the fake. The name gate
(run.sh list, W12) only catches test-like names, the fresh check re-runs over
the same tree — the verdict was PASS. "New files are never violations"
(_compare_manifests) was the host-side half of the hole.

Both echelons share the ONE comparison (_compare_manifests): the worker-side
_check_contract_lock (already passes plan.declared_paths) and the host-side
host_contract_check. The two cannot drift.

The end-to-end halves (worker creates the file mid-run -> published
CONTRACT-FAIL / declared PASS stands) are pinned in test_scenarios_verdict.py
— scenario 3 (undeclared, both zones parametrized) and scenario 9 (declared
new test keeps PASS; the exemption only applies because host_launch_k8s
parsed the ticket's declared paths — the wiring is proven there). The unit
rules below are runtime-agnostic.

Tests:
  1  colorsys scenario: an undeclared new tests/colorsys.py after the
     snapshot -> host_contract_check reports UNDECLARED
  2  a declared new test file -> no violation
  3  new files OUTSIDE src/ and tests/ (docs/) are normal deliverables —
     not flagged. T3-10 moved the src/ half into test_stage3_src_tree.py:
     src/ is now IN the rule.
  4  the worker-side _check_contract_lock flags an undeclared new tests/ file
     with the same mechanism (declared exemption works)
  5  __pycache__ files are not flagged (interpreter cache, not contract)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_tests_tree.py -q
"""
from launcher import verify
from launcher.config import Config
from launcher.plan import SessionPlan


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


# --- 1: the colorsys hole -------------------------------------------------------

def test_undeclared_new_file_under_tests_is_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    # The substitution: a helper module that shadows the stdlib `colorsys`
    # a reference test imports. Not test-like -> W12 never sees it.
    (repo / "tests" / "colorsys.py").write_text("def rgb(*a):\n    return (0, 0, 0)\n",
                                                 encoding="utf-8")
    v = verify.host_contract_check(cfg, before, ())
    assert v == ["UNDECLARED: tests/colorsys.py"]


# --- 2: a declared new test is the allowed case ----------------------------------

def test_declared_new_test_file_is_not_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "new_test.py").write_text("def test_new():\n    pass\n",
                                                 encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ("tests/new_test.py",)) == []


# --- 3: the rule is scoped to src/ + tests/ (T3-10) ------------------------------

def test_new_files_outside_src_and_tests_are_not_flagged(tmp_path):
    # docs/ is a normal deliverable zone: a new undeclared docs/ file is not
    # a substitution. The src/ half of the scope is test_stage3_src_tree.py.
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "docs" / "note.md").write_text("notes\n", encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ()) == []


# --- 4: the worker-side echelon uses the same mechanism ---------------------------

def test_worker_side_lock_flags_undeclared_new_test(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify._tests_manifest(cfg)
    (repo / "tests" / "colorsys.py").write_text("def rgb(*a):\n    return (0, 0, 0)\n",
                                                 encoding="utf-8")
    job: dict = {}
    verify._check_contract_lock(cfg, before, job, 1, SessionPlan(declared_paths=()))
    assert job["contract_lock_violations"] == [
        "turn 1: UNDECLARED: tests/colorsys.py"]
    # the declared exemption is the same declared context the host gets
    job2: dict = {}
    verify._check_contract_lock(cfg, before, job2, 1,
                                SessionPlan(declared_paths=("tests/colorsys.py",)))
    assert "contract_lock_violations" not in job2


# --- 5: __pycache__ is not contract ------------------------------------------------

def test_pycache_file_under_tests_is_not_flagged(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    cache = repo / "tests" / "__pycache__"
    cache.mkdir()
    (cache / "colorsys.pyc").write_bytes(b"\x00\x00\x00\x00")
    assert verify.host_contract_check(cfg, before, ()) == []
