"""Provenance tests (plan 2026-10-08, step 1): commit_sha is captured on the
HOST before the container starts, passed via STANOK_START_COMMIT env, and the
container-side build_summary never runs git itself.

Incident: in a worktree `.git` is a file pointing outside the mounted tree —
the container-side `git rev-parse HEAD` fails and the old code swallowed it
(`except: pass`), publishing `commit_sha: None` silently.
"""
import subprocess

from launcher import cli, summary
from launcher.config import Config


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _make_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q",
         "--allow-empty", "-m", "base")
    return repo


def test_commit_sha_from_host_env(tmp_path, monkeypatch):
    """Container simulation: repo_root has no usable .git (a worktree pointer
    to a non-existent gitdir), but the host captured STANOK_START_COMMIT.
    build_summary must publish the captured value, not run git."""
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /nonexistent-gitdir\n")
    monkeypatch.setenv("STANOK_START_COMMIT", "0123456789abcdef0123456789abcdef01234567")
    s = summary.build_summary(Config(repo_root=str(repo)), {"label": "x", "rc": 0,
                                                            "verifier": "PASS"}, 0)
    assert s["commit_sha"] == "0123456789abcdef0123456789abcdef01234567"


def test_capture_start_commit_from_head(tmp_path, monkeypatch):
    """Host capture: a normal checkout -> STANOK_START_COMMIT == HEAD."""
    monkeypatch.delenv("STANOK_START_COMMIT", raising=False)
    repo = _make_repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    cli._capture_start_commit(Config(repo_root=str(repo)))
    import os
    assert os.environ["STANOK_START_COMMIT"] == head


def test_capture_start_commit_warns_on_broken_git(tmp_path, monkeypatch, capsys):
    """Host capture failure (worktree pointer to a missing gitdir): a WARN is
    logged, the env is NOT set — no silent anything."""
    monkeypatch.delenv("STANOK_START_COMMIT", raising=False)
    repo = tmp_path / "wt"
    repo.mkdir()
    (repo / ".git").write_text("gitdir: /nonexistent-gitdir\n")
    cli._capture_start_commit(Config(repo_root=str(repo)))
    import os
    assert "STANOK_START_COMMIT" not in os.environ
    assert "WARN" in capsys.readouterr().out


def test_build_summary_warns_without_env(monkeypatch, capsys):
    """No captured env and no git: commit_sha is explicitly None AND a WARN is
    logged — the old silent `except: pass` is a defect."""
    monkeypatch.delenv("STANOK_START_COMMIT", raising=False)
    s = summary.build_summary(Config(repo_root="/nonexistent-repo-root"),
                             {"label": "x", "rc": 0, "verifier": "PASS"}, 0)
    assert s["commit_sha"] is None
    assert "WARN" in capsys.readouterr().out
