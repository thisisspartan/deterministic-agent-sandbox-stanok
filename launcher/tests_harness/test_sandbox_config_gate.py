"""W7 — sandbox_config_gate (hermetic). Regression test for CC-107.

Root cause (CC-107): cli.js resolves sandbox.filesystem deny entries against
the --settings file's directory (REPO_ROOT/.claude), NOT cwd. A deny entry
that resolves to a NON-EXISTENT path inside the allowed-write region makes
cli.js emit `--ro-bind /dev/null <path>`; bwrap must then create the
mount-point file, and when the parent sits on a read-only mount (the Docker
repo mount) it dies with EROFS and EVERY Bash call in the session fails from
the first command. The gate rejects a launch (rc=28) when any denyWrite /
denyRead entry resolves to a path that does not exist.

  1  denyWrite "hooks" (bare -> .claude/hooks, absent) -> gate True  (CC-107)
  2  denyWrite "../hooks" (-> repo/hooks, exists)      -> gate False (fixed)
  3  denyRead  "launcher" (bare -> .claude/launcher)   -> gate True
  4  all "../" entries pointing at existing dirs       -> gate False
  5  no sandbox.filesystem block                       -> gate False
  6  full path: bare "hooks" denyWrite -> process rc=28,
     evidence/<label>/summary.json EARLY-ABORT (verdict FAIL, not PASS)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_sandbox_config_gate.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher"

if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402


def _repo_with_settings(tmp_path, fs):
    repo = tmp_path / "repo"
    claude = repo / ".claude"
    claude.mkdir(parents=True)
    cfg = {"sandbox": {"filesystem": fs}}
    (claude / "settings.stanok.json").write_text(json.dumps(cfg), encoding="utf-8")
    return repo


def _mk(repo, *dirs):
    for d in dirs:
        (repo / d).mkdir(parents=True, exist_ok=True)


# --- 1: bare denyWrite entry -> non-existent .claude/hooks (CC-107) --------

def test_bare_denywrite_flagged(tmp_path, monkeypatch):
    repo = _repo_with_settings(tmp_path, {"denyWrite": ["hooks"]})
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.sandbox_config_gate() is True


# --- 2: "../" denyWrite entry -> existing repo/hooks (the fix) -------------

def test_dotdot_denywrite_ok(tmp_path, monkeypatch):
    repo = _repo_with_settings(tmp_path, {"denyWrite": ["../hooks"]})
    _mk(repo, "hooks")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.sandbox_config_gate() is False


# --- 3: bare denyRead entry -> non-existent .claude/launcher ---------------

def test_bare_denyread_flagged(tmp_path, monkeypatch):
    repo = _repo_with_settings(tmp_path, {"denyRead": ["launcher"]})
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.sandbox_config_gate() is True


# --- 4: all "../" entries point at existing dirs ---------------------------

def test_all_dotdot_entries_ok(tmp_path, monkeypatch):
    fs = {
        "denyWrite": ["../evidence", "../hooks", "../launcher", "../.claude"],
        "denyRead": ["../hooks", "../launcher", "../evidence", "../.claude"],
    }
    repo = _repo_with_settings(tmp_path, fs)
    _mk(repo, "evidence", "hooks", "launcher")  # .claude already exists
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.sandbox_config_gate() is False


# --- 5: no sandbox.filesystem block ----------------------------------------

def test_no_filesystem_block_ok(tmp_path, monkeypatch):
    repo = _repo_with_settings(tmp_path, {})
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.sandbox_config_gate() is False


# --- 6: full path rc=28 -----------------------------------------------------

def test_full_path_rc28(tmp_path):
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / "tickets").mkdir()
    (repo / "scripts").mkdir()
    (repo / "Dockerfile").write_text("FROM scratch\n")
    (repo / "scripts" / "run.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    # The bad settings file MUST be committed so the tree is clean
    # (dirty_tree_gate passes) and sandbox_config_gate is what catches it
    # (rc=28, not rc=22).
    (repo / ".claude" / "settings.stanok.json").write_text(
        json.dumps({"sandbox": {"filesystem": {"denyWrite": ["hooks"]}}}),
        encoding="utf-8")
    (repo / "tickets" / "TASK-TEST.md").write_text("# test ticket\n")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git"] + args, cwd=repo, check=True, capture_output=True)
    env = dict(os.environ)
    env["STANOK_REPO"] = str(repo)
    label = "w7-rc28"
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER_DIR / "stanok.py"),
         "run", "tickets/TASK-TEST.md", label, "--direct"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 28, proc.stdout + proc.stderr
    sum_path = repo / "evidence" / label / "summary.json"
    assert sum_path.is_file()
    data = json.loads(sum_path.read_text())
    assert data["probe_result"] == "EARLY-ABORT"
    assert data["rc"] == 28
    assert data["verifier"] == "FAIL"
