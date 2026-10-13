"""Stage 3 T3-10 — the structural src/ tree rule (operator decision 2026-10-09).

T3-9 scoped the structural rule to tests/ only; the operator proved the other
half of the substitution hole live on the public code: a new src/colorsys.py
shadows the stdlib `colorsys` a reference test imports (src is on sys.path via
pythonpath=src), the test passes against the fake, and host_contract_check
returned [] because the after-only scan was scoped to tests/. T3-10 (spec):
"declared paths are exact files; any new undeclared file in src/ or tests/
gives CONTRACT-FAIL".

The asymmetry that must NOT collapse: existing src/ files are the machine's
normal implementation surface — MODIFIED/DELETED stays scoped to the protected
files (tests/, scripts/run.sh, scripts/stacks/*.toml); src/ enters the
snapshot ONLY for the after-only UNDECLARED half. _protected_files does NOT
gain src/ — making src/ read-only would make the machine unable to implement
anything.

The end-to-end half of test 1 (the worker creates the file mid-run and
claims PASS -> published CONTRACT-FAIL, fresh skipped) is pinned in
test_scenarios_verdict.py scenario 3 — parametrized over BOTH zones. The
unit rules below are runtime-agnostic.

Tests:
  1  colorsys scenario (src/ half): an undeclared new src/colorsys.py after
     the snapshot -> host_contract_check reports UNDECLARED
  2  a declared new src/ file (the ticket's impl:) -> no violation
  3  an existing src/ file MODIFIED or DELETED -> NOT a violation (normal
     implementation work; the asymmetry guard against over-tightening)
  4  the worker-side _check_contract_lock flags an undeclared new src/ file
     with the same mechanism
  5  __pycache__ under src/ is not flagged (interpreter cache, not contract)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_src_tree.py -q
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
    return repo, Config(repo_root=str(repo))


# --- 1: the colorsys hole, src/ half ---------------------------------------------

def test_undeclared_new_file_under_src_is_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    # The substitution the name gate cannot see: src/colorsys.py shadows the
    # stdlib `colorsys` (src is on sys.path via pythonpath=src). Not
    # test-like -> W12 never sees it; the fresh check re-runs the same tree.
    (repo / "src" / "colorsys.py").write_text("def rgb(*a):\n    return (0, 0, 0)\n",
                                              encoding="utf-8")
    v = verify.host_contract_check(cfg, before, ())
    assert v == ["UNDECLARED: src/colorsys.py"]


# --- 2: a declared new src/ file is the allowed case -----------------------------

def test_declared_new_src_file_is_not_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "src" / "seq.py").write_text("def next_after(n, x):\n    return None\n",
                                         encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ("src/seq.py",)) == []


# --- 3: the asymmetry — existing src/ files are the implementation surface ------

def test_existing_src_file_modified_is_not_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    before = verify.contract_snapshot(cfg)
    # Normal implementation work: the machine edits its own src/ files.
    # MODIFIED/DELETED stays scoped to the protected files (T3-9 boundary).
    (repo / "src" / "mod.py").write_text("x = 2\n", encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ()) == []


def test_existing_src_file_deleted_is_not_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "mod.py").write_text("x = 1\n", encoding="utf-8")
    before = verify.contract_snapshot(cfg)
    (repo / "src" / "mod.py").unlink()
    assert verify.host_contract_check(cfg, before, ()) == []


# --- 4: the worker-side echelon uses the same mechanism ---------------------------

def test_worker_side_lock_flags_undeclared_new_src_file(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify._tests_manifest(cfg)
    (repo / "src" / "colorsys.py").write_text("def rgb(*a):\n    return (0, 0, 0)\n",
                                              encoding="utf-8")
    job: dict = {}
    verify._check_contract_lock(cfg, before, job, 1, SessionPlan(declared_paths=()))
    assert job["contract_lock_violations"] == [
        "turn 1: UNDECLARED: src/colorsys.py"]
    # the declared exemption is the same declared context the host gets
    job2: dict = {}
    verify._check_contract_lock(cfg, before, job2, 1,
                                SessionPlan(declared_paths=("src/colorsys.py",)))
    assert "contract_lock_violations" not in job2


# --- 5: __pycache__ under src/ is not contract ------------------------------------

def test_pycache_file_under_src_is_not_flagged(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    cache = repo / "src" / "__pycache__"
    cache.mkdir()
    (cache / "colorsys.pyc").write_bytes(b"\x00\x00\x00\x00")
    assert verify.host_contract_check(cfg, before, ()) == []
