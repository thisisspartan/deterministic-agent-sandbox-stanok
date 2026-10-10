"""Worker container lifecycle (S1 rollback of T3-4, PLAN-SIMPLIFY-2026-10-09).

The worker container runs WITH `--rm`: the worker writes its summary.json
directly into the rw LOG_DIR/<label> mount (config.summary_dir) — the host
never retrieves anything from the container layer: no `docker cp`, no
`docker rm -f`. The host still calls docker_stop in the finally: the trap for
the abnormal paths (signal/timeout); with `--rm` a normal exit has already
removed the container, so there the stop is a harmless no-op.
Reaper: at the start of a host run, STOPPED containers with the
`stanok-{repo}-` prefix (crash leftovers of runs whose docker CLI died before
the daemon could remove them) are removed; running containers are not touched.
A run whose worker never wrote a summary publishes NOTHING: `launch.sh status`
reports `missing` = an aborted run (supervisor protocol §3.3) — not a verdict.

Tests 1-2: worker argv has `--rm`; summary routing (container = the LOG_DIR
mount vs host = the evidence dir).
Tests 3-5: mocked host cycle — no summary -> nothing published, status
`missing`; reaper removes only stopped prefixed containers; a successful cycle
calls stop but never cp/rm and preserves the container rc.
Test 6: real docker (skipped when docker is absent) — a sandbox_argv container
is GONE after its exit (`--rm` does the removal, no host-side rm needed).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_worker_lifecycle.py -q
"""
import argparse
import json
import os
import shutil
import subprocess

import pytest

from launcher import cli, sandbox, summary, verify
from launcher.config import Config, RunState

IMAGE = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")


# --- 1: the worker container is auto-removed ------------------------------------

def test_worker_argv_has_rm(tmp_path):
    _, argv = sandbox.sandbox_argv(str(tmp_path / "repo"), str(tmp_path / "logs"),
                                   "img", ["python3", "x"])
    assert "--rm" in argv
    # the container is still named: the reaper's filter and the stop-trap
    # in the finally address it by name
    assert "--name" in argv


# --- 2: summary routing ---------------------------------------------------------

def test_summary_dir_routing(tmp_path, monkeypatch):
    cfg = Config(repo_root=str(tmp_path / "repo"), log_dir=str(tmp_path / "logs"))
    # container: the rw LOG_DIR mount — the worker's summary lands where the
    # host's publish source is (S1 rollback: no container-internal path)
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    assert cfg.summary_dir("lbl") == os.path.join(str(tmp_path / "logs"), "lbl")
    # host: the evidence dir (the host is the publisher)
    monkeypatch.delenv("STANOK_IN_CONTAINER")
    assert cfg.summary_dir("lbl") == str(tmp_path / "repo" / "evidence" / "lbl")


def test_write_summary_follows_routing(tmp_path, monkeypatch):
    cfg = Config(repo_root=str(tmp_path / "repo"), log_dir=str(tmp_path / "logs"))
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    run_state = RunState(evidence_dir=str(tmp_path / "ev"),
                         live_dir=str(tmp_path / "live"),
                         marker_path=str(tmp_path / "ev" / ".running"))
    job = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
           "turns": 1}
    summary.write_summary(cfg, job, 1)
    s = json.loads((tmp_path / "logs" / "lbl" / "summary.json")
                   .read_text(encoding="utf-8"))
    assert s["probe_result"] == "CLEAN-FIRST"
    # the host-owned evidence/ is NOT the container's summary target
    assert not os.path.exists(str(tmp_path / "ev" / "summary.json"))


# --- 3-5: mocked host cycle -----------------------------------------------------

def _mock_run(tmp_path, monkeypatch, container_rc=0, write_summary=True):
    """run_sandboxed with docker mocked. The fake worker writes its summary
    into LOG_DIR/<label> (the rw mount — what the real container does with
    `--rm`). write_summary=False simulates a worker that died before writing.
    Returns (repo, cfg, calls, args)."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    logdir = tmp_path / "logs"
    logdir.mkdir()
    cfg = Config(repo_root=str(repo), log_dir=str(logdir))
    calls = []

    def spy_argv(*a, **k):
        calls.append("sandbox_argv")
        return ("stanok-test", ["docker", "run", "img"])

    class FakePopen:
        def __init__(self, argv, **kw):
            pass

        def wait(self):
            calls.append("wait")
            if write_summary:
                d = logdir / "lbl"
                d.mkdir(exist_ok=True)
                with open(d / "summary.json", "w", encoding="utf-8") as f:
                    json.dump({"label": "lbl", "ticket": "t.md",
                               "rc": container_rc, "verifier": "PASS",
                               "probe_result": "CLEAN-FIRST", "turns": 1,
                               "contract_lock_violations": [],
                               "errors": [], "failures": []}, f)
            return container_rc

    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: calls.append("reap"))
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    # T3-6: run_sandboxed now runs the fresh check — mocked PASS here; the
    # observable verdict path is pinned in test_scenarios_verdict.py
    # (S6 removed the wiring unit test).
    monkeypatch.setattr(verify, "fresh_verify", lambda cfg: (0, ""))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kw: FakePopen(argv))
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: calls.append("stop"))
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a, **kw: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, args


def test_missing_summary_publishes_nothing(tmp_path, monkeypatch):
    """S1: with `--rm` there is no cp to fail — a worker that never wrote a
    summary publishes NOTHING (no fake verdict, no ENV-FAIL): the run is an
    aborted run, `status` reports `missing` (supervisor protocol §3.3)."""
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       container_rc=1, write_summary=False)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 1  # the container rc is the run rc
    assert not (repo / "evidence" / "lbl" / "summary.json").exists()
    st = cli._status_dict(cfg, "lbl")
    assert st["state"] == "missing"


def test_reaper_removes_only_stopped_prefixed(monkeypatch, tmp_path):
    calls = []

    class R:
        def __init__(self, out=""):
            self.returncode = 0
            self.stdout = out
            self.stderr = ""

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        if "ps" in cmd:
            return R("aaa111\nbbb222\n")
        return R()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    sandbox.reap_stopped(str(tmp_path / "myrepo"))
    ps = calls[0]
    assert ps[:2] == ["docker", "ps"]
    # Operator condition 1 (2026-10-09): the filter is narrowed to THIS repo's
    # name prefix `stanok-{basename}-` — a foreign repo's stopped containers
    # are not this run's leftovers. The trailing dash prevents substring bleed
    # (a repo named "repo" must not match "stanok-repoA-...").
    assert "name=stanok-myrepo-" in ps
    assert "name=stanok-" not in ps      # the generic prefix is gone
    assert "status=exited" in ps         # stopped only — running untouched
    assert "-q" in ps
    rm = calls[1]
    assert rm[:2] == ["docker", "rm"]
    assert set(rm[2:]) == {"aaa111", "bbb222"}


def test_reaper_noop_when_nothing_stopped(monkeypatch, tmp_path):
    calls = []

    class R:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_run(cmd, **kw):
        calls.append(list(cmd))
        return R()

    monkeypatch.setattr(sandbox.subprocess, "run", fake_run)
    sandbox.reap_stopped(str(tmp_path / "myrepo"))
    assert len(calls) == 1 and "ps" in calls[0]  # no `docker rm` without ids


def _docker_rm(*names):
    subprocess.run(["docker", "rm", "-f", *names],
                   capture_output=True, text=True, timeout=60)


def _container_exists(name: str) -> bool:
    ps = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
                        capture_output=True, text=True, timeout=30)
    return ps.stdout.strip() != ""


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_reaper_leaves_foreign_repo_container(tmp_path):
    """Operator condition 1, real docker: a STOPPED container of ANOTHER repo
    (a worktree run, a different checkout) is not this run's leftover. Two
    stopped containers with different repo prefixes; reap_stopped(<repo>)
    removes only the `stanok-repo-` one. The pair `repo`/`repoA` also pins
    the trailing dash: docker's name filter is a substring match, so a
    dashless `stanok-repo` would bleed into `stanok-repoA-`."""
    pid = os.getpid()
    mine = f"stanok-repo-{pid}"
    foreign = f"stanok-repoA-{pid}"
    try:
        for n in (mine, foreign):
            p = subprocess.run(["docker", "run", "-d", "--name", n, IMAGE, "true"],
                               capture_output=True, text=True, timeout=120)
            assert p.returncode == 0, p.stderr
        # both must be STOPPED before the reaper runs
        w = subprocess.run(["docker", "wait", mine, foreign],
                           capture_output=True, text=True, timeout=120)
        assert w.returncode == 0, w.stderr
        # the repo basename must match the container prefix: `repo` here,
        # so the filter is `stanok-repo-` — mine matches, foreign bleeds?
        # No: `stanok-repo-` is not a substring of `stanok-repoA-...`.
        sandbox.reap_stopped(str(tmp_path / "repo"))
        assert not _container_exists(mine)    # this repo's leftover: reaped
        assert _container_exists(foreign)     # foreign: untouched
    finally:
        _docker_rm(mine, foreign)


def test_successful_cycle_stops_but_never_cps_or_rms(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch, container_rc=0)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 0  # the container rc is the run rc
    # the reaper runs before this run's container starts
    assert calls.index("reap") < calls.index("sandbox_argv")
    # S1: the retrieval cycle is gone — the summary arrived via the mount;
    # the stop-trap remains, cp/rm do not
    assert "stop" in calls
    assert "cp" not in calls and "rm" not in calls
    s = json.loads((repo / "evidence" / "lbl" / "summary.json")
                   .read_text(encoding="utf-8"))
    assert s["verifier"] == "PASS" and s["probe_result"] == "CLEAN-FIRST"


def test_status_and_wait_see_final_summary(tmp_path, monkeypatch, capsys):
    """Operator condition 2 (2026-10-09): after the host cycle (publish ->
    marker removal) `cmd_status` and `cmd_wait` must report the FINAL
    verdict — the published summary.json, not `missing`, not a stale one.
    The readers of summary.json: `_publish_evidence` is the ONLY reader of the
    LOG_DIR copy (the worker's mount target); `_status_dict` (cmd_status/cmd_wait)
    reads the published evidence/<label>/summary.json; the supervisor reads the
    same published file."""
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch, container_rc=0)
    assert cli.run_sandboxed(cfg, args, (), (), ()) == 0
    st = cli._status_dict(cfg, "lbl")
    assert st["state"] == "done"
    assert st["rc"] == 0 and st["verifier"] == "PASS"
    assert st["probe_result"] == "CLEAN-FIRST"

    capsys.readouterr()  # drain run_sandboxed's log lines
    assert cli.cmd_status(cfg, "lbl") == 0
    out = json.loads(capsys.readouterr().out)
    assert out["state"] == "done" and out["rc"] == 0
    assert out["verifier"] == "PASS" and out["probe_result"] == "CLEAN-FIRST"

    # terminal state already reached: cmd_wait returns immediately (no polling)
    assert cli.cmd_wait(cfg, "lbl") == 0
    out2 = json.loads(capsys.readouterr().out)
    assert out2["state"] == "done" and out2["rc"] == 0
    assert out2["verifier"] == "PASS" and out2["probe_result"] == "CLEAN-FIRST"


# --- 6: real docker — --rm does the removal --------------------------------------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_rm_container_is_gone_after_exit(tmp_path):
    """S1 rollback, real docker: a container built by sandbox_argv (`--rm`) is
    removed by the daemon on exit — no host-side `docker rm` is needed and the
    name is free again immediately after the run."""
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    log = tmp_path / "logs"
    log.mkdir()
    name, argv = sandbox.sandbox_argv(str(repo), str(log), IMAGE, ["true"])
    proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0, proc.stderr
    ps = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
                        capture_output=True, text=True, timeout=30)
    assert ps.stdout.strip() == ""
