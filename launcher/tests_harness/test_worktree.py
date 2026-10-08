"""Worktree tests (plan 2026-10-08, step 3; decisions D1/D2).

D2: the run lock key is the shared GIT COMMON DIR, not the repo path — a
worktree has a different path but the same git directory, so two runs from
two worktrees of one repo must serialize (second gets rc=21). Before the
fix the key was md5(repo_root): two worktrees got two different lock files
and ran in parallel — the red test below proves it.

D1: worktrees are for smoke runs only; a worktree placed next to `stanok/`
inside the project root must get the SAME gate behavior as the main
checkout (ticket resolution via dirname(repo_root), role-leak check there).
"""
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

from launcher import cli
from launcher.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCH = REPO_ROOT / "launch.sh"
LOG_DIR = Path("/tmp/stanok-logs")
DEAD_SERVER = "http://127.0.0.1:59999"


def _launch(args, env_extra):
    """Run launch.sh with the doctor env; return the exit code (same driver
    as test_doctor._launch)."""
    env = dict(os.environ)
    env["STANOK_PY"] = shutil.which("python3") or sys.executable
    env.update(env_extra)
    proc = subprocess.run([str(LAUNCH)] + [str(a) for a in args],
                          env=env, capture_output=True, timeout=120)
    return proc.returncode


def _cleanup(label):
    shutil.rmtree(REPO_ROOT / "evidence" / label, ignore_errors=True)
    shutil.rmtree(LOG_DIR / label, ignore_errors=True)


def _ticket(tmp_path, body):
    t = tmp_path / f"wt-ticket-{uuid.uuid4().hex[:8]}.md"
    t.write_text(body, encoding="utf-8")
    return t


def _git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)


def _make_repo(tmp_path):
    """A repo with src/ and tests/ committed: declared ticket paths resolve
    under existing dirs (CC-133), so the launch reaches the LOCK gate —
    the red failure is the real defect (wrong lock file), not a parse error."""
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tests").mkdir(parents=True)
    (repo / "src" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "tests" / "__init__.py").write_text("", encoding="utf-8")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "base")
    return repo


def _add_worktree(repo, tmp_path):
    wt = tmp_path / "stanok-wt"
    r = _git(repo, "worktree", "add", "-q", str(wt), "-b", "smoke/test")
    assert r.returncode == 0, r.stderr
    return wt


def _common_dir(repo):
    out = _git(repo, "rev-parse", "--git-common-dir").stdout.strip()
    return os.path.abspath(out if os.path.isabs(out) else os.path.join(str(repo), out))


def test_lock_key_is_git_common_dir(tmp_path):
    """Unit: main checkout and worktree of one repo resolve to the SAME key;
    a non-repo resolves to None (fail closed, no silent path fallback)."""
    repo = _make_repo(tmp_path)
    wt = _add_worktree(repo, tmp_path)
    k_main = cli._lock_key(Config(repo_root=str(repo)))
    k_wt = cli._lock_key(Config(repo_root=str(wt)))
    assert k_main == k_wt == _common_dir(repo)
    assert cli._lock_key(Config(repo_root=str(tmp_path / "not-a-repo"))) is None


def test_lock_shared_across_worktrees(tmp_path):
    """Integration (the D2 red test): the repo lock is held by this process;
    a launch from a WORKTREE of the same repo must be refused with rc=21.
    Before the fix: md5(worktree path) -> a different lock file -> rc=20."""
    repo = _make_repo(tmp_path)
    wt = _add_worktree(repo, tmp_path)
    key = _common_dir(repo)
    lock_path = LOG_DIR / f"stanok-{hashlib.md5(key.encode()).hexdigest()[:12]}.lock"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lf = open(lock_path, "w")
    fcntl.flock(lf, fcntl.LOCK_EX | fcntl.LOCK_NB)
    label = f"wtlock-{uuid.uuid4().hex[:8]}"
    t = _ticket(tmp_path, "# wt\n\ntest: tests/wt_test.py\nimpl: src/wt.py\n\nrun.sh: exists\n")
    try:
        rc = _launch(["run", str(t), label], {
            "STANOK_REPO": str(wt),
            "STANOK_SERVER_URL": DEAD_SERVER,
            "STANOK_NO_SANDBOX": "1",
        })
        assert rc == 21, f"expected lock refusal rc=21, got {rc}"
    finally:
        fcntl.flock(lf, fcntl.LOCK_UN)
        lf.close()
        _cleanup(label)


def test_resolve_ticket_from_worktree(tmp_path):
    """D1 pin: a worktree placed next to stanok/ inside the project root
    resolves tickets via dirname(repo_root) — same behavior as the main
    checkout."""
    proj = tmp_path / "proj"
    (proj / "tickets").mkdir(parents=True)
    t = proj / "tickets" / "T-wt.md"
    t.write_text("impl: src/x.py\n", encoding="utf-8")
    wt = proj / "stanok-wt"
    wt.mkdir()
    cfg = Config(repo_root=str(wt))
    assert cli._resolve_ticket(cfg, "tickets/T-wt.md") == str(t)


def test_role_leak_gate_covers_worktree(tmp_path):
    """D1 pin: the role-leak check (rc=24) fires for a worktree whose parent
    directory carries CLAUDE.md — identical to the main checkout."""
    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "CLAUDE.md").write_text("role leak", encoding="utf-8")
    repo = _make_repo(proj)
    wt = _add_worktree(repo, proj)
    label = f"wtrole-{uuid.uuid4().hex[:8]}"
    t = _ticket(tmp_path, "impl: src/x.py\n\ntest: tests/x_test.py\n\nrun.sh: exists\n")
    try:
        rc = _launch(["run", str(t), label], {
            "STANOK_REPO": str(wt),
            "STANOK_SERVER_URL": DEAD_SERVER,
            "STANOK_NO_SANDBOX": "1",
        })
        assert rc == 24, f"expected role-leak rc=24, got {rc}"
    finally:
        _cleanup(label)
