"""Review C5 (2026-10-17): hooks/stanok-post-commit must survive every sync.

The auto-pin hook is part of the required behavior of a public skeleton (a
parent with a stanok submodule must keep its gitlink current), so
sync-skeleton.sh mirrors it from the parent's canonical hooks/ directory.
This test runs the REAL script against a synthetic SRC/DST git pair and
asserts:

  1. the hook lands in DST — tracked, byte-identical, mode 100755 (git
     silently never runs a non-exec hook);
  2. a SECOND sync does not remove it (the regression C5 was about: the
     top_sync allowlist silently skipped hooks/ entirely);
  3. the hook itself is portable — no machine-local absolute paths or
     private IPs (public-tree hygiene).

Layout guard: the script and the hook live in the PARENT repo. In a
standalone stanok checkout they are absent — skip with an explicit reason,
never a silent green (same pattern as the doctor guards).
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PARENT = REPO_ROOT.parent
SCRIPT = PARENT / ".claude" / "sync-skeleton.sh"
HOOK = PARENT / "hooks" / "stanok-post-commit"

pytestmark = pytest.mark.skipif(
    not (SCRIPT.is_file() and HOOK.is_file()),
    reason="parent repo not present (standalone stanok checkout) — "
    "sync-skeleton.sh / hooks/ absent",
)

GIT_IDENTITY = {
    "GIT_AUTHOR_NAME": "sync-test", "GIT_AUTHOR_EMAIL": "t@invalid",
    "GIT_COMMITTER_NAME": "sync-test", "GIT_COMMITTER_EMAIL": "t@invalid",
}


def _git(repo, *args):
    return subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True,
        check=True,
    )


def _build_pair(tmp_path):
    """Synthetic SRC (parent + nested stanok repo + canonical hook) and a
    clean empty DST (parent + nested stanok repo)."""
    src, dst = tmp_path / "src", tmp_path / "dst"
    for repo in (src, dst):
        repo.mkdir(parents=True)
        _git(repo, "init", "-q", "-b", "main")
        nested = repo / "stanok"
        nested.mkdir()
        _git(nested, "init", "-q", "-b", "main")
    # SRC content: a top-level infra file, the canonical hook, a submodule file
    (src / "README.md").write_text("# synthetic\n", encoding="utf-8")
    hooks = src / "hooks"
    hooks.mkdir()
    shutil.copy(HOOK, hooks / "stanok-post-commit")
    (hooks / "stanok-post-commit").chmod(0o755)
    (src / "stanok" / "infra.txt").write_text("infra\n", encoding="utf-8")
    # DST starts as an empty checked-out pair (no hook yet — that is C5)
    (dst / "stanok" / ".gitkeep").write_text("", encoding="utf-8")
    env = {**os.environ, **GIT_IDENTITY}
    # nested repo first: a parent cannot record a gitlink for a submodule
    # that has no commit checked out yet
    for repo in (src, dst):
        for target in (repo / "stanok", repo):
            _git(target, "add", "-A")
            _git(target, "-c", "user.name=t", "-c", "user.email=t@invalid",
                 "commit", "-q", "-m", "init")
    return src, dst, env


def _run_sync(src, dst, env):
    return subprocess.run(
        ["bash", str(SCRIPT)],
        env={**env, "SRC": str(src), "DST": str(dst)},
        capture_output=True, text=True, timeout=120,
    )


def _tracked_mode(dst, path):
    out = subprocess.run(
        ["git", "-C", str(dst), "ls-files", "-s", "--", path],
        capture_output=True, text=True,
    )
    return out.stdout.strip()  # "<mode> <sha> 0\tpath" or ""


def test_sync_mirrors_the_hook_tracked_identical_and_exec(tmp_path):
    src, dst, env = _build_pair(tmp_path)
    result = _run_sync(src, dst, env)
    assert result.returncode == 0, result.stderr

    mode = _tracked_mode(dst, "hooks/stanok-post-commit")
    assert mode.startswith("100755"), f"hook not tracked as exec: {mode!r}"
    mirrored = dst / "hooks" / "stanok-post-commit"
    assert mirrored.read_bytes() == HOOK.read_bytes(), "hook content changed"


def test_second_sync_does_not_remove_the_hook(tmp_path):
    src, dst, env = _build_pair(tmp_path)
    assert _run_sync(src, dst, env).returncode == 0
    result = _run_sync(src, dst, env)  # the "next sync" C5 was about
    assert result.returncode == 0, result.stderr
    mode = _tracked_mode(dst, "hooks/stanok-post-commit")
    assert mode.startswith("100755"), f"hook lost on re-sync: {mode!r}"


def test_hook_is_portable_no_machine_local_paths():
    body = HOOK.read_text(encoding="utf-8")
    for marker in ("/home/", "/Users/", "192.168."):
        assert marker not in body, f"hook carries machine-local marker {marker!r}"
