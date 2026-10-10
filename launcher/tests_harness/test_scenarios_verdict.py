"""S6a — end-to-end scenarios of the verdict path (PLAN-SIMPLIFY-2026-10-09).

The verdict path that survives the simplification: the host snapshots the
contract before the run and recomputes it after; the host runs the fresh check
in a clean container; the host publishes the verdict. These scenarios test ONLY
the observable verdict — the published evidence/<label>/summary.json and the
run's exit rc — never an internal mechanism.

Discipline (operator, 2026-10-09):
  - green on the CURRENT code, and they must stay green after S1 (T3-4
    rollback to --rm), S2 (I5 / worker_* / INTEGRITY-FAIL removal) and S5
    (bwrap removal): only fields that survive the simplification are asserted;
  - they NEVER read worker_rc / worker_verifier / INTEGRITY-FAIL — S2 removes
    them and the verdict does not depend on them;
  - they assert the verdict, not code correctness (ARCHITECTURE.md "What PASS
    means"): a green scenario means the tree passed the host's checks, nothing
    more.

Scenarios:
  1 honest PASS: clean tree, clean worker summary, fresh green -> published
    PASS byte-identical, fresh ran;
  2 retry after failure: the worker's local retry ended PASS-AFTER-LOCAL-RETRY,
    tree intact, fresh green -> published PASS, the worker's flow preserved;
  3 contract violation: an undeclared new file under src/ or tests/ mid-run
    -> CONTRACT-FAIL, fresh skipped (both zones, one rule);
  4 fresh check failure: the worker claims a clean PASS but the host's fresh
    container fails the suite -> FRESH-FAIL, rc = the fresh check's rc;
  5 infrastructure failure: the fresh check cannot run (EXEC_ERROR) -> rc=16
    ENV-FAIL summary — not a verdict, call the human;
  6 forged summary over a tampered tree: the worker weakened an existing
    protected test mid-run and its summary claims a clean PASS -> the host
    recompute forces CONTRACT-FAIL; a host-issued verdict never exits 0;
  7 honest worker FAIL, fresh green: the host's fresh check passes over the
    final tree -> the honest FAIL is published unchanged; a green fresh check
    never fabricates a PASS (the host only downgrades, never upgrades).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_scenarios_verdict.py -q
"""
import argparse
import json
import os

import pytest

from launcher import cli, sandbox, verify
from launcher.config import Config

CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1,
                "contract_lock_violations": [], "errors": [], "failures": []}

RETRY_WORKER = dict(CLEAN_WORKER, probe_result="PASS-AFTER-LOCAL-RETRY",
                    turns=2, failures=["turn 1: test_add failed"])

HONEST_FAIL_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 1,
                      "verifier": "FAIL", "probe_result": "VERIFY-FAIL",
                      "turns": 1, "contract_lock_violations": [], "errors": [],
                      "failures": ["test_x failed"]}


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    assert 1 == 1\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


def _mock_run(tmp_path, monkeypatch, *, during_run=None,
              worker_summary=CLEAN_WORKER, fresh_result=(0, ""),
              container_rc=0):
    """run_sandboxed with the docker cycle mocked; the REAL contract snapshot,
    recompute and publish run. during_run: callable(repo) the fake worker runs
    mid-run. fresh_result: what verify.fresh_verify returns. Returns
    (repo, cfg, calls, args)."""
    repo, cfg = _repo(tmp_path)
    calls = []

    class FakePopen:
        def __init__(self, argv, **kw):
            pass

        def wait(self):
            calls.append("wait")
            if during_run is not None:
                during_run(repo)
            # S1: the worker writes its summary into the rw LOG_DIR mount
            d = os.path.join(cfg.log_dir, "lbl")
            os.makedirs(d, exist_ok=True)
            with open(os.path.join(d, "summary.json"), "w",
                      encoding="utf-8") as f:
                json.dump(worker_summary, f)
            return container_rc

    def spy_argv(*a, **k):
        calls.append("run")
        return ("stanok-test", ["docker", "run", "img"])

    def spy_fresh(c):
        calls.append("fresh")
        return fresh_result

    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: None)
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    monkeypatch.setattr(verify, "fresh_verify", spy_fresh)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kw: FakePopen(argv))
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: calls.append("stop"))
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, args


# --- 1: honest PASS ---------------------------------------------------------------

def test_scenario_honest_pass(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 0
    dst = _published(repo)
    assert dst == dict(CLEAN_WORKER, rc=0)  # clean path: the host does not touch it
    assert "fresh" in calls


# --- 2: retry after failure -------------------------------------------------------

def test_scenario_retry_after_failure_publishes_pass(tmp_path, monkeypatch):
    # The worker's in-session local retry (red turn -> fix) is the worker's
    # feedback loop, not the verdict. The observable contract: a clean final
    # tree + green fresh check publishes the worker's flow unchanged.
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       worker_summary=RETRY_WORKER)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 0
    dst = _published(repo)
    assert dst["verifier"] == "PASS"
    assert dst["probe_result"] == "PASS-AFTER-LOCAL-RETRY"
    assert dst["rc"] == 0
    assert "fresh" in calls


# --- 3: contract violation (one rule, both zones) ----------------------------------

def _create_colorsys(rel):
    def run(r):
        (r / rel).write_text("def rgb(*a):\n    return (0, 0, 0)\n",
                             encoding="utf-8")
    return run


@pytest.mark.parametrize("rel", ["src/colorsys.py", "tests/colorsys.py"])
def test_scenario_undeclared_new_file_both_zones(tmp_path, monkeypatch, rel):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       during_run=_create_colorsys(rel))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1  # a host-issued FAIL never exits 0
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any(f"UNDECLARED: {rel}" in x for x in dst["contract_lock_violations"])
    assert "fresh" not in calls  # a fresh run over a tampered tree is uninformative


# --- 4: fresh check failure ---------------------------------------------------------

def test_scenario_fresh_check_failure(tmp_path, monkeypatch):
    # The worker claims a clean PASS on an intact tree, but the suite fails in
    # the host's fresh container the worker never touched.
    repo, cfg, calls, args = _mock_run(
        tmp_path, monkeypatch,
        fresh_result=(1, "FAILED tests/t_test.py::test_x - assert False"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1  # the exit equals the published verdict's rc
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "FRESH-FAIL"
    assert dst["rc"] == 1
    assert any("FRESH-CHECK" in e for e in dst["errors"])


# --- 5: infrastructure failure ------------------------------------------------------

def test_scenario_infra_failure_fresh_unavailable(tmp_path, monkeypatch):
    # The fresh check cannot run at all: the verdict cannot be issued —
    # rc=16 ENV-FAIL, not a verdict (call the human).
    repo, cfg, calls, args = _mock_run(
        tmp_path, monkeypatch,
        fresh_result=(2, "EXEC_ERROR: fresh container failed to start"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 16
    dst = _published(repo)
    assert dst["probe_result"] == "ENV-FAIL"
    assert dst["rc"] == 16
    assert any("fresh check unavailable" in e for e in dst["errors"])


# --- 6: forged summary over a tampered tree ------------------------------------------

def test_scenario_forged_pass_over_tampered_tree(tmp_path, monkeypatch):
    # The classic forgery: the worker weakens an existing protected test
    # mid-run (its own suite now passes) and its summary claims a clean PASS.
    # The host recompute sees the MODIFIED protected file — the forged PASS
    # does not survive.
    def weaken(r):
        (r / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                                encoding="utf-8")
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch, during_run=weaken)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1
    dst = _published(repo)
    assert dst["verifier"] == "FAIL"
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert any("tests/t_test.py" in x for x in dst["contract_lock_violations"])
    assert "fresh" not in calls


# --- 7: honest worker FAIL, fresh green ---------------------------------------------

def test_scenario_honest_fail_not_fabricated(tmp_path, monkeypatch):
    # The host's authority is exactly two checks, both downgrades: a green
    # fresh check over the final tree does NOT flip the worker's honest FAIL
    # into a PASS — the honest verdict is published unchanged.
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       container_rc=1,
                                       worker_summary=dict(HONEST_FAIL_WORKER))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert "fresh" in calls  # the fresh check is not gated on the worker's claims
    assert rc == 1  # the exit equals the published verdict's rc
    dst = _published(repo)
    assert dst == dict(HONEST_FAIL_WORKER, rc=1)  # unchanged: no fabrication
