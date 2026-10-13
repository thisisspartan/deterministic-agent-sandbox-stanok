"""CC-134: evidence/ is HOST-OWNED — the container has no rw view of it.

Before CC-134 the container mounted `evidence/` rw, so the agent and the
in-container Runner shared a writable verdict dir with the host. Now:

  - `zones.WRITABLE_ZONES` = the 4 project zones (no "evidence"); CC-258 moved
    the list to launcher/zones.py (the zone policy survives the Docker-path
    removal);
    evidence/ is visible read-only through the repo :ro mount, so a write
    from inside the container is an EROFS denial, not a missing path.
  - `Config.label_paths()` resolves BOTH dirs into the rw log_dir/<label> when
    STANOK_IN_CONTAINER=1, so every in-container writer (summary.json,
    launcher.stdout.log, the .running marker) lands somewhere writable.
  - `summary._publish_evidence()` copies the verdict into evidence/<label> on
    the HOST, after the container exits.

CC-258 (step C): the summary-routing tests moved here from
test_stage3_worker_lifecycle.py — that file pinned the Docker worker
lifecycle and is gone; the routing it also pinned is runtime-agnostic
(Config.summary_dir + summary.write_summary: the in-container writer lands
in the rw log_dir, never in the host-owned evidence/), so it survives here.

CC-258 (step B): the two Docker tests (the sandbox_argv mount table and the
live-`docker run` evidence denial) are gone with the Docker path; the
evidence-boundary invariant on the k8s path is pinned by
test_k8s_manifests.py (read-only roots) and the tests below (the host-owned
evidence/ is never a container summary target).
"""
import json
import os

from launcher import summary, zones
from launcher.config import Config


def _host_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    log = tmp_path / "logs"
    log.mkdir()
    return repo, log, Config(repo_root=str(repo), log_dir=str(log))


def test_evidence_is_not_a_writable_zone():
    # The former carve-out is gone (single zone list, CC-132/CC-134).
    assert "evidence" not in zones.WRITABLE_ZONES
    assert zones.WRITABLE_ZONES == ("src", "tests", "docs", "scripts")


def test_label_paths_container_writes_into_log_dir(tmp_path, monkeypatch):
    repo, log, cfg = _host_paths(tmp_path)
    monkeypatch.delenv("STANOK_IN_CONTAINER", raising=False)
    evidence, live = cfg.label_paths("run1")
    assert evidence == str(repo / "evidence" / "run1")
    assert live == str(log / "run1")

    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    evidence, live = cfg.label_paths("run1")
    assert evidence == str(log / "run1")
    assert live == str(log / "run1")


def test_summary_dir_routing(tmp_path, monkeypatch):
    # moved from test_stage3_worker_lifecycle.py (CC-258): the worker's
    # summary target is the rw LOG_DIR mount in the container, the host's
    # publish target is the evidence dir — the same rule in both runtimes.
    cfg = Config(repo_root=str(tmp_path / "repo"), log_dir=str(tmp_path / "logs"))
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    assert cfg.summary_dir("lbl") == os.path.join(str(tmp_path / "logs"), "lbl")
    monkeypatch.delenv("STANOK_IN_CONTAINER")
    assert cfg.summary_dir("lbl") == str(tmp_path / "repo" / "evidence" / "lbl")


def test_write_summary_follows_routing(tmp_path, monkeypatch):
    cfg = Config(repo_root=str(tmp_path / "repo"), log_dir=str(tmp_path / "logs"))
    monkeypatch.setenv("STANOK_IN_CONTAINER", "1")
    job = {"label": "lbl", "ticket": "t.md", "rc": 0, "verifier": "PASS",
           "turns": 1}
    summary.write_summary(cfg, job, 1)
    s = json.loads((tmp_path / "logs" / "lbl" / "summary.json")
                   .read_text(encoding="utf-8"))
    assert s["probe_result"] == "CLEAN-FIRST"
    # the host-owned evidence/ is NOT the container's summary target
    assert not os.path.exists(str(tmp_path / "repo" / "evidence"))


def test_publish_evidence_copies_the_verdict(tmp_path):
    repo, log, cfg = _host_paths(tmp_path)
    container_dir = log / "run1"
    container_dir.mkdir()
    (container_dir / "summary.json").write_text('{"rc": 0}', encoding="utf-8")
    (container_dir / "launcher.stdout.log").write_text("log\n", encoding="utf-8")
    (container_dir / "failures.log").write_text("boom\n", encoding="utf-8")
    (container_dir / "session-x.jsonl").write_text("{}\n", encoding="utf-8")

    summary._publish_evidence(cfg, "run1", 0)

    published = repo / "evidence" / "run1"
    assert (published / "summary.json").read_text(encoding="utf-8") == '{"rc": 0}'
    assert (published / "launcher.stdout.log").is_file()
    # CC-237: failures.log is part of the verdict artifacts.
    assert (published / "failures.log").read_text(encoding="utf-8") == "boom\n"
    # The session log stays in LOG_DIR; evidence/ carries the verdict only.
    assert not (published / "session-x.jsonl").exists()


def test_publish_evidence_stray_failures_log_not_half_published(tmp_path):
    # CC-237: the gate stays summary.json-only — a run that died before
    # writing its verdict publishes NOTHING, even with a stray failures.log.
    repo, log, cfg = _host_paths(tmp_path)
    container_dir = log / "run1"
    container_dir.mkdir()
    (container_dir / "failures.log").write_text("boom\n", encoding="utf-8")
    summary._publish_evidence(cfg, "run1", 1)
    assert not (repo / "evidence").exists()


def test_publish_evidence_absent_is_a_noop(tmp_path):
    repo, _, cfg = _host_paths(tmp_path)
    summary._publish_evidence(cfg, "never-started", 0)
    assert not (repo / "evidence").exists()
