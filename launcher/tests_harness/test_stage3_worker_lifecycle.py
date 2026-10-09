"""Stage 3 T3-4 — worker container lifecycle (SPEC-VERDICT-INTEGRITY §2, T3-4).

The worker container runs WITHOUT `--rm`: it must survive its exit so the host
can retrieve the summary from the container's WRITABLE LAYER (`docker cp`),
and only then remove it (`docker rm -f`). The worker's summary.json is written
to a container-internal path (config.CONTAINER_SUMMARY_ROOT — a writable-layer
dir: not tmpfs, not the mounted LOG_DIR); the session's streaming log and the
marker stay in LOG_DIR. Host order: wait -> cp -> rm. A failed `docker cp` is
an ENV-FAIL (rc=16) with the error text: the verdict cannot be PASS.
Reaper: at the start of a host run, STOPPED containers with the `stanok-`
prefix (crash leftovers) are removed; running containers are not touched.
(Deviation from the plan's "at the start of cmd_run": cmd_run executes inside
the container, where the docker CLI is absent — the reaper lives at the start
of the host-side run_sandboxed.)

Tests 1-2: worker argv has no `--rm`; summary routing (container vs host).
Tests 3-5: mocked host cycle — `docker cp` failure -> rc=16 + summary not
PASS; reaper removes only stopped prefixed containers; a successful cycle
calls cp then rm -f and preserves the container rc.
Test 6: real docker (skipped when docker is absent) — the plan's
stop-condition check: `docker cp` DOES copy from a STOPPED container,
CONTAINER_SUMMARY_ROOT is writable under --user, `docker rm -f` removes it.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_worker_lifecycle.py -q
"""
import argparse
import json
import os
import shutil
import subprocess

import pytest

from launcher import cli, sandbox, summary, verify
from launcher import config as launcher_config
from launcher.config import Config, RunState

IMAGE = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")


# --- 1: the worker container is not auto-removed -------------------------------

def test_worker_argv_has_no_rm(tmp_path):
    _, argv = sandbox.sandbox_argv(str(tmp_path / "repo"), str(tmp_path / "logs"),
                                   "img", ["python3", "x"])
    assert "--rm" not in argv
    # the container is still named: it is the cp/rm target (T3-4)
    assert "--name" in argv


# --- 2: summary routing ---------------------------------------------------------

def test_summary_dir_routing(tmp_path, monkeypatch):
    cfg = Config(repo_root=str(tmp_path / "repo"), log_dir=str(tmp_path / "logs"))
    # container: the writable-layer path, NOT the mounted LOG_DIR
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    assert cfg.summary_dir("lbl") == os.path.join(launcher_config.CONTAINER_SUMMARY_ROOT, "lbl")
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
    try:
        summary.write_summary(cfg, job, 1)
        s = json.loads(open(os.path.join(launcher_config.CONTAINER_SUMMARY_ROOT, "lbl",
                                        "summary.json"),
                            encoding="utf-8").read())
        assert s["probe_result"] == "CLEAN-FIRST"
        # the shared LOG_DIR/evidence mount is NOT the summary target anymore
        assert not os.path.exists(str(tmp_path / "ev" / "summary.json"))
    finally:
        shutil.rmtree(launcher_config.CONTAINER_SUMMARY_ROOT, ignore_errors=True)


# --- 3-5: mocked host cycle -----------------------------------------------------

def _mock_run(tmp_path, monkeypatch, cp_result=(0, ""), container_rc=0):
    """run_sandboxed with docker mocked. The mock cp, on success, writes a
    worker-shaped summary to the host path (what a real `docker cp` does).
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
            return container_rc

    def spy_cp(name, cpath, hpath):
        calls.append("cp")
        rc, err = cp_result
        if rc == 0:
            os.makedirs(os.path.dirname(hpath), exist_ok=True)
            with open(hpath, "w", encoding="utf-8") as f:
                json.dump({"label": "lbl", "ticket": "t.md", "rc": container_rc,
                           "verifier": "PASS", "probe_result": "CLEAN-FIRST",
                           "turns": 1, "contract_lock_violations": [],
                           "errors": [], "failures": []}, f)
        return (rc, err)

    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: calls.append("reap"))
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    # T3-6: run_sandboxed now runs the fresh check — mocked PASS here; the
    # wiring itself is pinned in test_stage3_fresh_wiring.py.
    monkeypatch.setattr(verify, "fresh_verify", lambda cfg: (0, ""))
    monkeypatch.setattr(cli.subprocess, "Popen", lambda argv, **kw: FakePopen(argv))
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: calls.append("stop"))
    monkeypatch.setattr(sandbox, "docker_cp", lambda *a: spy_cp(*a))
    monkeypatch.setattr(sandbox, "docker_rm_force", lambda name: calls.append("rm"))
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, args


def test_cp_failure_is_env_fail(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(
        tmp_path, monkeypatch,
        cp_result=(1, "Error: No such container: stanok-test"))
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 16
    s = json.loads((repo / "evidence" / "lbl" / "summary.json")
                   .read_text(encoding="utf-8"))
    assert s["verifier"] == "FAIL"
    assert s["rc"] == 16
    assert s["probe_result"] == "ENV-FAIL"
    assert any("docker cp" in e for e in s["errors"])


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
        sandbox.docker_rm_force(mine)
        sandbox.docker_rm_force(foreign)


def test_successful_cycle_cp_then_rm_rc_preserved(tmp_path, monkeypatch):
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       cp_result=(0, ""), container_rc=0)
    rc = cli.run_sandboxed(cfg, args, (), (), ())
    assert rc == 0  # the container rc is the run rc (I5 ground truth)
    # the reaper runs before this run's container starts
    assert calls.index("reap") < calls.index("sandbox_argv")
    # the plan's order: wait -> cp -> rm
    assert calls.index("wait") < calls.index("cp") < calls.index("rm")
    s = json.loads((repo / "evidence" / "lbl" / "summary.json")
                   .read_text(encoding="utf-8"))
    assert s["verifier"] == "PASS" and s["probe_result"] == "CLEAN-FIRST"


def test_status_and_wait_see_final_summary_after_cp(tmp_path, monkeypatch, capsys):
    """Operator condition 2 (2026-10-09): after the host cycle (cp -> publish
    -> marker removal) `cmd_status` and `cmd_wait` must report the FINAL
    verdict — the published summary.json, not `missing`, not a stale one.
    The readers of summary.json: `_publish_evidence` is the ONLY reader of the
    LOG_DIR copy (the docker cp target); `_status_dict` (cmd_status/cmd_wait)
    reads the published evidence/<label>/summary.json; the supervisor reads the
    same published file."""
    repo, cfg, calls, args = _mock_run(tmp_path, monkeypatch,
                                       cp_result=(0, ""), container_rc=0)
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


# --- 6: real docker — the plan's stop-condition ---------------------------------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_docker_cp_retrieves_summary_from_stopped_container(tmp_path):
    name = f"stanok-cptest-{os.getpid()}"
    inner = ("mkdir -p /var/tmp/stanok-evidence/t && "
             "printf '{\"rc\": 0}' > /var/tmp/stanok-evidence/t/summary.json")
    argv = ["docker", "run", "--name", name, "--init",
            "--user", f"{os.getuid()}:{os.getgid()}",
            IMAGE, "bash", "-c", inner]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=120)
        # the writable-layer path is writable under --user (the worker's uid)
        assert proc.returncode == 0, proc.stderr
        # no --rm: the container survives its exit as STOPPED
        ps = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
                            capture_output=True, text=True, timeout=30)
        assert ps.stdout.strip() != ""
        out = tmp_path / "summary.json"
        rc, err = sandbox.docker_cp(name, "/var/tmp/stanok-evidence/t/summary.json",
                                    str(out))
        assert rc == 0, err
        assert out.read_text(encoding="utf-8") == '{"rc": 0}'
    finally:
        sandbox.docker_rm_force(name)
    ps2 = subprocess.run(["docker", "ps", "-a", "--filter", f"name={name}", "-q"],
                         capture_output=True, text=True, timeout=30)
    assert ps2.stdout.strip() == ""
