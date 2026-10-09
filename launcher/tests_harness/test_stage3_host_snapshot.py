"""Stage 3 T3-1 — host-side contract snapshot BEFORE `docker run`.

Trust boundary (operator review 2026-10-09, SPEC-VERDICT-INTEGRITY §1): the
verdict must not depend on files the worker can rewrite. The host snapshots
the protected files (tests/**, scripts/run.sh, scripts/stacks/*.toml —
verify._protected_files, the one source, CC-136) before the container
starts and keeps the snapshot in the HOST PROCESS MEMORY only: a file in
LOG_DIR is inside the container's rw mount and could be forged. T3-2
recomputes it after the container exits and compares.

This ticket adds: `verify.contract_snapshot` (public host entry point, the
same manifest as _tests_manifest) + its call in `cli.run_sandboxed` before
`sandbox.sandbox_argv`/Popen. Nothing consumes the snapshot yet (T3-2).

Tests:
  1  run_sandboxed computes the snapshot BEFORE sandbox_argv/Popen (call order
     via mocks) — the boundary is the docker argv construction, not just Popen
  2  the snapshot covers the protected files with sha256 digests
  3  the snapshot is NOT written into LOG_DIR (memory only)
  4  a protected-file change after the snapshot is detectable by recompute
     (the guard T3-2 builds on)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_stage3_host_snapshot.py -q
"""
import argparse
import hashlib
import os

from launcher import cli, sandbox, verify
from launcher.config import Config


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "tests" / "t_test.py").write_text("def test_x():\n    pass\n",
                                               encoding="utf-8")
    (repo / "scripts" / "run.sh").write_text("#!/bin/bash\n", encoding="utf-8")
    (repo / "scripts" / "stacks").mkdir()
    (repo / "scripts" / "stacks" / "py.toml").write_text('ext = "py"\n',
                                                          encoding="utf-8")
    logdir = tmp_path / "logs"
    logdir.mkdir()
    return repo, Config(repo_root=str(repo), log_dir=str(logdir))


class _FakePopen:
    def __init__(self, argv, **kwargs):
        self.argv = argv

    def wait(self):
        return 0


def _mock_run(tmp_path, monkeypatch):
    """run_sandboxed with docker/signal/stop mocked. Returns (repo, cfg,
    calls, snapshots, args). The real snapshot logic runs; only the call
    sites are observed."""
    repo, cfg = _repo(tmp_path)
    calls, snapshots = [], []

    def spy_snapshot(c):
        calls.append("snapshot")
        snap = verify._tests_manifest(c)
        snapshots.append(snap)
        return snap

    def spy_argv(*a, **k):
        calls.append("sandbox_argv")
        return ("stanok-test", ["docker", "run", "img"])

    def spy_popen(argv, **kwargs):
        calls.append("popen")
        return _FakePopen(argv)

    monkeypatch.setattr(verify, "contract_snapshot", spy_snapshot)
    monkeypatch.setattr(sandbox, "sandbox_argv", spy_argv)
    # T3-6: run_sandboxed now runs the fresh check — mocked PASS here; the
    # wiring itself is pinned in test_stage3_fresh_wiring.py.
    monkeypatch.setattr(verify, "fresh_verify", lambda cfg: (0, ""))
    monkeypatch.setattr(cli.subprocess, "Popen", spy_popen)
    monkeypatch.setattr(sandbox, "docker_stop", lambda name: None)
    # T3-4: run_sandboxed now also calls the reaper, cp and rm -f — mocked so
    # this T3-1 test keeps observing only its own boundary (the snapshot).
    monkeypatch.setattr(sandbox, "reap_stopped", lambda *a: None)
    monkeypatch.setattr(sandbox, "docker_cp", lambda *a: (0, ""))
    monkeypatch.setattr(sandbox, "docker_rm_force", lambda name: None)
    monkeypatch.setattr(cli, "_install_signal_handlers", lambda rs: None)
    monkeypatch.setattr(cli.os, "setpgid", lambda *a: None)
    args = argparse.Namespace(label="lbl", ticket="t.md",
                             local_retries=cfg.default_retries, extra=[])
    return repo, cfg, calls, snapshots, args


# --- 1: the snapshot precedes the container ------------------------------------

def test_snapshot_computed_before_docker_run(tmp_path, monkeypatch):
    repo, cfg, calls, snapshots, args = _mock_run(tmp_path, monkeypatch)
    assert cli.run_sandboxed(cfg, args, (), (), ()) == 0
    assert "snapshot" in calls and "sandbox_argv" in calls and "popen" in calls
    # The boundary is the docker argv construction: a snapshot taken after
    # sandbox_argv (but before Popen) is NOT "before docker run" — the mutant
    # that moves it there must die.
    assert calls.index("snapshot") < calls.index("sandbox_argv")
    assert calls.index("sandbox_argv") < calls.index("popen")


# --- 2: the snapshot is the protected-files manifest ----------------------------

def test_snapshot_covers_protected_files(tmp_path, monkeypatch):
    repo, cfg, calls, snapshots, args = _mock_run(tmp_path, monkeypatch)
    cli.run_sandboxed(cfg, args, (), (), ())
    snap = snapshots[0]
    assert snap["tests/t_test.py"] == hashlib.sha256(
        b"def test_x():\n    pass\n").hexdigest()
    assert snap["scripts/run.sh"] == hashlib.sha256(b"#!/bin/bash\n").hexdigest()
    assert snap["scripts/stacks/py.toml"] == hashlib.sha256(
        b'ext = "py"\n').hexdigest()


# --- 3: memory only — nothing lands in LOG_DIR ----------------------------------

def test_snapshot_not_written_to_log_dir(tmp_path, monkeypatch):
    repo, cfg, calls, snapshots, args = _mock_run(tmp_path, monkeypatch)
    cli.run_sandboxed(cfg, args, (), (), ())
    assert os.listdir(cfg.log_dir) == []


# --- 4: a post-snapshot change is detectable (T3-2 guard) ----------------------

def test_change_after_snapshot_is_detectable(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = verify.contract_snapshot(cfg)
    (repo / "tests" / "t_test.py").write_text("tampered after snapshot\n",
                                              encoding="utf-8")
    after = verify.contract_snapshot(cfg)
    assert after["tests/t_test.py"] != before["tests/t_test.py"]
