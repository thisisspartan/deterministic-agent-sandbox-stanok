"""CC-134: evidence/ is HOST-OWNED — the container has no rw view of it.

Before CC-134 the container mounted `evidence/` rw, so the agent and the
in-container Runner shared a writable verdict dir with the host. Now:

  - `sandbox.WRITABLE_ZONES` = the 4 project zones (no "evidence");
    evidence/ is visible read-only through the repo :ro mount, so a write
    from inside the container is an EROFS denial, not a missing path.
  - `label_paths()` resolves BOTH dirs into the rw LOG_DIR/<label> when
    STANOK_IN_CONTAINER=1, so every in-container writer (summary.json,
    launcher.stdout.log, the .running marker) lands somewhere writable.
  - `_publish_evidence()` copies the verdict into evidence/<label> on the
    HOST, after the container exits.

CC-135 (T4) landed after this file: `sandbox_argv` no longer mounts the zones
rw wholesale — the caller passes per-ticket `rw_paths` and the default is
`()` (nothing writable but log_dir), so the tests below pass them explicitly.

The last test is a real `docker run` (the image is a hard doctor requirement
already): a zone write succeeds, an evidence/ write is refused.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import sandbox  # noqa: E402
import stanok  # noqa: E402


def _host_paths(tmp_path, monkeypatch, label="cc134"):
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    monkeypatch.setattr(stanok, "LOG_DIR", str(log))
    return repo, log


def test_evidence_is_not_a_writable_zone():
    # The former carve-out is gone (single zone list, CC-132/CC-134).
    assert "evidence" not in sandbox.WRITABLE_ZONES
    assert sandbox.WRITABLE_ZONES == ("src", "tests", "docs", "scripts")


def test_sandbox_argv_mounts_evidence_read_only(tmp_path):
    repo = tmp_path / "repo"
    for rel in ("evidence", "src", "tests"):
        (repo / rel).mkdir(parents=True)
    log = tmp_path / "logs"
    log.mkdir()
    # T4/CC-135: the carve-outs are per-ticket (rw_paths), not the zone list —
    # the default is fail-closed (nothing writable but log_dir).
    _, argv = sandbox.sandbox_argv(str(repo), str(log), "img", ["true"])
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    rw = [m for m in mounts if m.endswith(":rw")]
    assert f"{repo}:{repo}:ro" in mounts
    assert f"{tmp_path}:{tmp_path}:ro" in mounts  # the parent dir (tickets/CLAUDE.md gate)
    assert f"{log}:{log}:rw" in rw
    assert rw == [f"{log}:{log}:rw"], rw  # default: no carve-out at all

    _, argv = sandbox.sandbox_argv(str(repo), str(log), "img", ["true"],
                                   rw_paths=("src/mod.py",))
    mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "-v"]
    rw = [m for m in mounts if m.endswith(":rw")]
    assert f"{repo}/src/mod.py:{repo}/src/mod.py:rw" in rw
    assert f"{repo}/evidence:{repo}/evidence:rw" not in rw
    assert f"{repo}/tests:{repo}/tests:rw" not in rw  # a sibling zone stays ro
    assert not any("/evidence" in m for m in rw)


def test_label_paths_container_writes_into_log_dir(tmp_path, monkeypatch):
    repo, log = _host_paths(tmp_path, monkeypatch)
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    evidence, live = stanok.label_paths("run1")
    assert evidence == str(repo / "evidence" / "run1")
    assert live == str(log / "run1")

    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    evidence, live = stanok.label_paths("run1")
    assert evidence == str(log / "run1")
    assert live == str(log / "run1")


def test_publish_evidence_copies_the_verdict(tmp_path, monkeypatch):
    repo, log = _host_paths(tmp_path, monkeypatch)
    container_dir = log / "run1"
    container_dir.mkdir()
    (container_dir / "summary.json").write_text('{"rc": 0}', encoding="utf-8")
    (container_dir / "launcher.stdout.log").write_text("log\n", encoding="utf-8")
    (container_dir / "session-x.jsonl").write_text("{}\n", encoding="utf-8")

    stanok._publish_evidence("run1")

    published = repo / "evidence" / "run1"
    assert (published / "summary.json").read_text(encoding="utf-8") == '{"rc": 0}'
    assert (published / "launcher.stdout.log").is_file()
    # The session log stays in LOG_DIR; evidence/ carries the verdict only.
    assert not (published / "session-x.jsonl").exists()


def test_publish_evidence_absent_is_a_noop(tmp_path, monkeypatch):
    repo, _ = _host_paths(tmp_path, monkeypatch)
    stanok._publish_evidence("never-started")
    assert not (repo / "evidence").exists()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_container_cannot_write_evidence(tmp_path):
    repo = tmp_path / "repo"
    for zone in (*sandbox.WRITABLE_ZONES, "evidence"):
        (repo / zone).mkdir(parents=True)
    log = tmp_path / "logs"
    log.mkdir()
    cmd = (
        f"touch '{repo}/src/probe' && echo SRC-OK; "
        f"if touch '{repo}/evidence/probe' 2>/dev/null; "
        f"then echo EVIDENCE-OK; else echo EVIDENCE-DENIED; fi"
    )
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    name, argv = sandbox.sandbox_argv(str(repo), str(log), image,
                                      ["bash", "-c", cmd], rw_paths=("src",))
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=180)
    finally:
        sandbox.docker_stop(name)
    assert "SRC-OK" in proc.stdout, proc
    assert "EVIDENCE-DENIED" in proc.stdout, proc
