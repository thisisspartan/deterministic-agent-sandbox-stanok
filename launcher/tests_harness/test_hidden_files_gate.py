"""W4 — hidden_files_gate (hermetic).

Pins the W4 hygiene gate in launcher/stanok.py: a launch is rejected (rc=26)
when src/tests/docs/scripts holds a hidden file (name starting with '.', except
.gitkeep) or a file carrying a 'TEMP:' marker in its first 40 lines. Such
leftovers from past runs leak into the machine's context and slip past
dirty_tree_gate (git status is clean for committed dotfiles).

  1  a hidden `.x.js` in src/ is found -> gate True
  2  only `.gitkeep` present -> gate False (clean)
  3  a file with `TEMP:` on its first line -> gate True
  4  full path `python launcher/stanok.py run ... --direct` with a committed
     hidden file -> process rc=26, evidence/<label>/summary.json EARLY-ABORT

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_hidden_files_gate.py -q
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


# --- 1: hidden .x.js found ----------------------------------------------------

def test_hidden_dotfile_found(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / ".x.js").write_text("// hidden leftover\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.hidden_files_gate() is True


# --- 2: only .gitkeep -> clean ------------------------------------------------

def test_only_gitkeep_clean(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
        (repo / d / ".gitkeep").write_text("")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.hidden_files_gate() is False


# --- 3: TEMP: marker on first line --------------------------------------------

def test_temp_marker_first_line(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "scratch.js").write_text("TEMP: delete after use\nconsole.log(1)\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.hidden_files_gate() is True


# --- 4: full path rc=26 --------------------------------------------------------

def test_full_path_rc26(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "tickets").mkdir()
    (repo / "Dockerfile").write_text("FROM scratch\n")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "run.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    # The hidden file MUST be committed so the tree is clean (dirty_tree_gate
    # passes) and the hidden_files_gate is what catches it (rc=26, not rc=22).
    (repo / "src" / ".x.js").write_text("// hidden leftover\n")
    (repo / "tickets" / "TASK-TEST.md").write_text("# test ticket\n")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git"] + args, cwd=repo, check=True, capture_output=True)
    env = dict(os.environ)
    env["STANOK_REPO"] = str(repo)
    label = "w4-rc26"
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER_DIR / "stanok.py"),
         "run", "tickets/TASK-TEST.md", label, "--direct"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 26, proc.stdout + proc.stderr
    sum_path = repo / "evidence" / label / "summary.json"
    assert sum_path.is_file()
    data = json.loads(sum_path.read_text())
    assert data["probe_result"] == "EARLY-ABORT"
    assert data["rc"] == 26
