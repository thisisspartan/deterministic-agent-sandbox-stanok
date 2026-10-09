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
host_contract_check — T3-9 wires the ticket's declared paths through
run_sandboxed so the host can distinguish a declared new test from a
substitution. The two cannot drift.

Tests:
  1  colorsys scenario: an undeclared new tests/colorsys.py after the
     snapshot -> host_contract_check reports UNDECLARED; end-to-end through
     run_sandboxed (the worker creates the file mid-run and claims PASS) ->
     published CONTRACT-FAIL, fresh check skipped
  2  a declared new test file -> no violation; end-to-end the PASS stands
  3  new files OUTSIDE tests/ (src/, docs/) are normal deliverables — not
     flagged
  4  the worker-side _check_contract_lock flags an undeclared new tests/ file
     with the same mechanism (declared exemption works)
  5  __pycache__ files are not flagged (interpreter cache, not contract)
  6  wiring: _host_launch forwards the ticket's declared paths to
     run_sandboxed (the host half of the declared context)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_tests_tree.py -q
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
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


def _mock_run(tmp_path, monkeypatch, *, create_during_run=None):
    """run_sandboxed with the docker cycle mocked; the REAL contract snapshot
    and recompute run. create_during_run: a rel path the fake worker writes
    under tests/ mid-run (the substitution). Returns (repo, cfg, calls, args)."""
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


def test_colorsys_substitution_end_to_end_is_contract_fail(tmp_path, monkeypatch):
    # The live scenario: the worker creates tests/colorsys.py mid-run and its
    # summary claims a clean PASS. Today that publishes PASS; the structural
    # rule must publish CONTRACT-FAIL.
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       create_during_run="tests/colorsys.py")
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any("UNDECLARED: tests/colorsys.py" in x
               for x in dst["contract_lock_violations"])
    assert "fresh" not in calls  # §1.6: a fresh run over a tampered tree


# --- 2: a declared new test is the allowed case ----------------------------------

def test_declared_new_test_file_is_not_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "new_test.py").write_text("def test_new():\n    pass\n",
                                                 encoding="utf-8")
    assert verify.host_contract_check(cfg, before, ("tests/new_test.py",)) == []


def test_declared_new_test_end_to_end_keeps_pass(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       create_during_run="tests/new_test.py")
    rc = cli.run_sandboxed(cfg, args, (), (), ("tests/new_test.py",))
    assert rc == 0
    dst = _published(repo)
    assert dst == dict(CLEAN_WORKER, rc=0)  # byte-identical: no host override
    assert "fresh" in calls  # the fresh check ran over an intact tree


# --- 3: the rule is scoped to tests/ ----------------------------------------------

def test_new_files_outside_tests_are_not_flagged(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "src" / "helper.py").write_text("x = 1\n", encoding="utf-8")
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


# --- 6: the host wiring — declared reaches run_sandboxed ---------------------------

def test_host_launch_forwards_declared_to_run_sandboxed(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    ticket_file = tmp_path / "ticket.md"
    ticket_file.write_text("test: tests/colorsys.py\n", encoding="utf-8")
    captured = {}

    def spy_run(cfg_, args, rw, ro, declared):
        captured["declared"] = declared
        return 0

    monkeypatch.setattr(cli, "run_sandboxed", spy_run)
    monkeypatch.setattr(cli.shutil, "which", lambda name: "/usr/bin/docker")
    args = argparse.Namespace(label="lbl", ticket="ticket.md",
                             ticket_path=str(ticket_file),
                             local_retries=cfg.default_retries, extra=[])
    assert cli._host_launch(cfg, args, str(tmp_path / ".running")) == 0
    assert captured["declared"] == ("tests/colorsys.py",)
