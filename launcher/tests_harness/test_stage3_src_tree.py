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
snapshot ONLY for the after-only UNDECLARED half. _protected_files (the :ro
bind list, host_ro_paths) does NOT gain src/ — binding src/ :ro would make
the machine unable to implement anything.

Tests:
  1  colorsys scenario (src/ half): an undeclared new src/colorsys.py after
     the snapshot -> host_contract_check reports UNDECLARED; end-to-end through
     run_sandboxed (the worker creates the file mid-run and claims PASS) ->
     published CONTRACT-FAIL, fresh check skipped
  2  a declared new src/ file (the ticket's impl:) -> no violation
  3  an existing src/ file MODIFIED or DELETED -> NOT a violation (normal
     implementation work; the asymmetry guard against over-tightening)
  4  the worker-side _check_contract_lock flags an undeclared new src/ file
     with the same mechanism
  5  __pycache__ under src/ is not flagged (interpreter cache, not contract)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_src_tree.py -q
"""
import argparse
import json

from launcher import cli, sandbox, summary, verify
from launcher.config import Config
from launcher.plan import SessionPlan

CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1,
                "contract_lock_violations": [], "errors": [], "failures": []}


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


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


def _mock_run(tmp_path, monkeypatch, *, create_during_run=None):
    """run_sandboxed with the docker cycle mocked; the REAL contract snapshot
    and recompute run. create_during_run: a rel path the fake worker writes
    under src/ mid-run (the substitution). Returns (repo, cfg, calls, args)."""
    repo, cfg = _repo(tmp_path)
    calls = []

    class FakePopen:
        def __init__(self, argv, **kw):
            pass

        def wait(self):
            calls.append("wait")
            if create_during_run is not None:
                (repo / create_during_run).write_text(
                    "def rgb(*a):\n    return (0, 0, 0)\n", encoding="utf-8")
            return 0

    def spy_argv(*a, **k):
        calls.append("run")
        return ("stanok-test", ["docker", "run", "img"])

    def spy_cp(name, cpath, hpath):
        calls.append("cp")
        import os
        os.makedirs(os.path.dirname(hpath), exist_ok=True)
        with open(hpath, "w", encoding="utf-8") as f:
            json.dump(CLEAN_WORKER, f)
        return (0, "")

    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: None)
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    monkeypatch.setattr(verify, "fresh_verify", lambda c: calls.append("fresh") or (0, ""))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kw: FakePopen(argv))
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: calls.append("stop"))
    monkeypatch.setattr(sandbox, "docker_cp", spy_cp)
    monkeypatch.setattr(sandbox, "docker_rm_force", lambda name: calls.append("rm"))
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, args


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


def test_src_colorsys_substitution_end_to_end_is_contract_fail(tmp_path, monkeypatch):
    # The live scenario: the worker creates src/colorsys.py mid-run and its
    # summary claims a clean PASS. Today that publishes PASS; the structural
    # rule must publish CONTRACT-FAIL.
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       create_during_run="src/colorsys.py")
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any("UNDECLARED: src/colorsys.py" in x
               for x in dst["contract_lock_violations"])
    assert "fresh" not in calls  # §1.6: a fresh run over a tampered tree


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
