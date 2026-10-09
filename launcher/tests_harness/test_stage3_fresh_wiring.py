"""Stage 3 T3-6 — wiring fresh_verify into run_sandboxed (SPEC-VERDICT-INTEGRITY §1.1, §3).

The host order pinned (plan 2026-10-08): snapshot -> docker run (no --rm) ->
wait -> stop -> cp -> rm -f -> contract recompute -> fresh check ->
_publish_evidence. Rules the wiring must enforce:
  - the fresh check runs ONLY when the summary was retrieved (cp ok) AND the
    contract is intact — a tampered tree makes a fresh run over it
    uninformative (spec §1.6: "контракт нарушен → fresh-прогон по
    испорченному дереву неинформативен"); it is NOT gated on the worker's
    claims (the host's check is unconditional authority, §1.1);
  - a fresh infra failure (tail "EXEC_ERROR:") is rc=16 ENV-FAIL — not a
    verdict (call the human), never FRESH-FAIL;
  - a fresh suite failure overrides the worker's claim at publish:
    probe_result FRESH-FAIL, rc = fresh rc, worker claims preserved (§3, R4);
  - the run's exit rc equals the published verdict's rc — the process exit
    must not contradict the summary the supervisor reads.

Tests:
  1  call order: snapshot < run < wait < cp < rm < contract recompute <
     fresh check < publish
  2  fresh FAIL at worker PASS -> end-to-end FRESH-FAIL: published rc=fresh
     rc + worker claims preserved + run rc = fresh rc (R4)
  3  fresh PASS clean path -> summary unchanged (no worker_* fields), run rc
     = container rc
  4  contract violations -> fresh NOT run (uninformative), CONTRACT-FAIL
     published
  5  cp failure -> fresh NOT run; ENV-FAIL (T3-4 behavior preserved)
  6  fresh infra failure (EXEC_ERROR) -> rc=16 ENV-FAIL summary, NOT
     FRESH-FAIL; run rc=16
  7  fresh runs after an honest worker FAIL (not gated on worker_verifier);
     a fresh PASS does not fabricate a PASS — the honest verdict stands

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_fresh_wiring.py -q
"""
import argparse
import json

from launcher import cli, sandbox, summary, verify
from launcher.config import Config

CLEAN_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
                "probe_result": "CLEAN-FIRST", "turns": 1,
                "contract_lock_violations": [], "errors": [], "failures": []}

HONEST_FAIL_WORKER = {"label": "lbl", "ticket": "t.md", "rc": 1,
                      "verifier": "FAIL", "probe_result": "VERIFY-FAIL",
                      "turns": 1, "contract_lock_violations": [], "errors": [],
                      "failures": []}


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


def _mock_run(tmp_path, monkeypatch, *, container_rc=0, cp_result=(0, ""),
              fresh_result=(0, ""), worker_summary=None, tamper_after_run=False):
    """run_sandboxed with the docker cycle mocked; the REAL contract snapshot
    and recompute run — the boundary under test is the wiring (order, gating,
    verdict routing), not the contract math (pinned in T3-1/T3-2 tests).
    Returns (repo, cfg, calls, args)."""
    repo, cfg = _repo(tmp_path)
    calls = []
    if worker_summary is None:
        worker_summary = dict(CLEAN_WORKER, rc=container_rc)

    real_snapshot = verify.contract_snapshot
    real_contract_check = verify.host_contract_check

    class FakePopen:
        def __init__(self, argv, **kw):
            pass

        def wait(self):
            calls.append("wait")
            if tamper_after_run:
                # simulate the worker rewriting a protected file mid-run
                (repo / "tests" / "t_test.py").write_text("tampered\n",
                                                          encoding="utf-8")
            return container_rc

    def spy_snapshot(c):
        calls.append("snapshot")
        return real_snapshot(c)

    def spy_argv(*a, **k):
        calls.append("run")
        return ("stanok-test", ["docker", "run", "img"])

    def spy_cp(name, cpath, hpath):
        calls.append("cp")
        rc, err = cp_result
        if rc == 0:
            import os
            os.makedirs(os.path.dirname(hpath), exist_ok=True)
            with open(hpath, "w", encoding="utf-8") as f:
                json.dump(worker_summary, f)
        return (rc, err)

    def spy_contract(c, before, declared):
        calls.append("contract")
        return real_contract_check(c, before, declared)

    def spy_fresh(c):
        calls.append("fresh")
        return fresh_result

    def spy_publish(c, label, rc, violations=(), fresh_check=None):
        calls.append("publish")
        return summary._publish_evidence(c, label, rc, violations, fresh_check)

    monkeypatch.setattr(verify, "contract_snapshot", spy_snapshot)
    monkeypatch.setattr(verify, "host_contract_check", spy_contract)
    monkeypatch.setattr(verify, "fresh_verify", spy_fresh)
    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: None)
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kw: FakePopen(argv))
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: calls.append("stop"))
    monkeypatch.setattr(sandbox, "docker_cp", spy_cp)
    monkeypatch.setattr(sandbox, "docker_rm_force", lambda name: calls.append("rm"))
    monkeypatch.setattr(cli, "_publish_evidence", spy_publish)
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, args


def _published(repo):
    return json.loads((repo / "evidence" / "lbl" / "summary.json")
                      .read_text(encoding="utf-8"))


# --- 1: the host order -----------------------------------------------------------

def test_host_order_snapshot_run_cp_rm_contract_fresh_publish(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch)
    assert cli.run_sandboxed(cfg, args, (), (), ()) == 0
    for step in ("snapshot", "run", "wait", "cp", "rm", "contract", "fresh",
                 "publish"):
        assert step in calls, calls
    idx = {s: calls.index(s) for s in ("snapshot", "run", "wait", "cp", "rm",
                                       "contract", "fresh", "publish")}
    # the snapshot precedes the container (T3-1 boundary, re-pinned here);
    # the contract recompute and the fresh check sit between the container's
    # removal and the publish — the verdict is issued from the host's view
    assert (idx["snapshot"] < idx["run"] < idx["wait"] < idx["cp"] <
            idx["rm"] < idx["contract"] < idx["fresh"] < idx["publish"])


# --- 2: fresh FAIL end-to-end (R4) -----------------------------------------------

def test_fresh_fail_end_to_end(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(
        tmp_path, monkeypatch,
        fresh_result=(1, "FAILED tests/t_test.py::test_x - 1 == 2"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    # the run's exit equals the published verdict (host-issued, §1.1)
    assert rc == 1
    dst = _published(repo)
    assert dst["probe_result"] == "FRESH-FAIL"
    assert dst["verifier"] == "FAIL"
    assert dst["rc"] == 1  # the fresh rc, not the container's 0
    assert dst["worker_rc"] == 0 and dst["worker_verifier"] == "PASS"
    assert any("1 == 2" in e for e in dst["errors"])


# --- 3: fresh PASS clean path stays byte-identical -------------------------------

def test_fresh_pass_clean_path_unchanged(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch)
    assert cli.run_sandboxed(cfg, args, (), (), ()) == 0
    dst = _published(repo)
    assert dst == dict(CLEAN_WORKER, rc=0)
    assert "worker_rc" not in dst and "worker_verifier" not in dst


# --- 4: contract violated -> the fresh run is uninformative, skipped -------------

def test_fresh_skipped_when_contract_violated(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       tamper_after_run=True)
    cli.run_sandboxed(cfg, args, (), (), ())
    assert "contract" in calls and "publish" in calls
    assert "fresh" not in calls  # §1.6: never run a fresh check over a
    # tampered tree — the tree the verdict would certify is already broken
    dst = _published(repo)
    assert dst["probe_result"] == "CONTRACT-FAIL"
    assert "MODIFIED: tests/t_test.py" in dst["contract_lock_violations"]


# --- 5: summary not retrieved -> no fresh check, ENV-FAIL (T3-4 preserved) ------

def test_fresh_skipped_when_summary_not_retrieved(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       cp_result=(1, "Error: No such file"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 16
    assert "fresh" not in calls
    dst = _published(repo)
    assert dst["probe_result"] == "ENV-FAIL"


# --- 6: fresh infra failure -> ENV-FAIL, never FRESH-FAIL -----------------------

def test_fresh_infra_failure_is_env_fail_not_fresh_fail(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(
        tmp_path, monkeypatch,
        fresh_result=(1, "EXEC_ERROR: docker: command not found"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 16  # infrastructure failure: not a verdict, call the human
    dst = _published(repo)
    assert dst["probe_result"] == "ENV-FAIL"
    assert dst["rc"] == 16
    assert any("EXEC_ERROR" in e for e in dst["errors"])


# --- 7: the fresh check is not gated on the worker's claims ----------------------

def test_fresh_runs_after_honest_worker_fail(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       container_rc=1,
                                       worker_summary=dict(HONEST_FAIL_WORKER),
                                       fresh_result=(0, ""))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert "fresh" in calls  # unconditional authority: no worker_verifier gate
    assert rc == 1
    dst = _published(repo)
    # a fresh PASS does not fabricate a PASS: the worker's honest FAIL stands
    assert dst["probe_result"] == "VERIFY-FAIL"
    assert dst["rc"] == 1
    assert "worker_rc" not in dst  # no host override happened
