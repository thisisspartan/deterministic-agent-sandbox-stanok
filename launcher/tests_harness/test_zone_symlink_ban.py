"""Zone-symlink ban (cc217 review follow-up, operator decision 2026-10-09).

The unified rule: in the writable zones (src/tests/docs/scripts) symlinks do
not exist. ONE enforcement point, ONE scanner (gates.zone_symlinks):

  LAUNCH (gates.zone_symlink_gate, wired into cli._launch_gates after the
  hidden-files gate, rc=13): any symlink — file, directory, dangling, or
  the zone directory itself — refuses the launch, with the path list and
  the fix. The container mounts the repo :ro and derives rw carve-outs
  only inside the zones; Docker resolves a bind source's realpath, so a
  link hands its TARGET rw access (the `src/link -> launcher/` incident,
  proven by test_docker_bind_resolves_symlink_source). The ban covers
  UNDECLARED links (the declared-path rule inspects only declared paths)
  and links under tests/ (the protected-file location — host_ro_paths
  would otherwise bind them :ro verbatim and Docker would resolve them).

S3 (PLAN-SIMPLIFY-2026-10-09): the post-turn scan (verify._check_zone_symlinks)
was REMOVED — the launch ban remains; a mid-run new file under tests/ or src/
is caught by the structural rules (T3-9/T3-10, worker + host echelons).

Tests:
  1  symlink file in src/ -> gate names it
  2  symlink directory in src/ -> gate names it (dir links included)
  3  symlink under tests/ -> gate names it (the protected-file location)
  4  dangling symlink -> gate names it (target need not exist)
  5  the zone directory itself is a symlink -> gate names it
  6  clean zones (regular files/dirs) -> gate returns []
  7  full path: committed symlink in src/ -> launch rc=13, EARLY-ABORT summary
  8  hard links: ln() from a zone to a repo file fails in Docker (EXDEV) —
     the scanner does not look for hard links because they cannot escape a
     zone: base repo :ro + per-zone rw binds are separate mounts

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_zone_symlink_ban.py -q
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from launcher import gates
from launcher.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_DIR = REPO_ROOT / "launcher"


def _repo(tmp_path):
    repo = tmp_path / "repo"
    for d in ("src", "tests", "docs", "scripts"):
        (repo / d).mkdir(parents=True)
    (repo / "launcher").mkdir()
    (repo / "launcher" / "target.txt").write_text("regular file\n")
    return repo, Config(repo_root=str(repo))


# --- 1-5: the launch gate names every kind of link ------------------------------

def test_gate_names_symlink_file_in_src(tmp_path):
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    problems = gates.zone_symlink_gate(cfg)
    assert any("src/link" in p for p in problems), problems


def test_gate_names_symlink_directory_in_zone(tmp_path):
    # A directory link is the same class: Docker resolves the bind source's
    # realpath, so the rw mount would land on the target dir.
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "dirlink").symlink_to("../launcher")
    problems = gates.zone_symlink_gate(cfg)
    assert any("src/dirlink" in p for p in problems), problems


def test_gate_names_symlink_under_tests(tmp_path):
    # The protected-file location: host_ro_paths would bind tests/ symlinks
    # :ro verbatim and Docker resolves them to their targets (the GAP
    # documented in test_ticket_zone.py, closed here).
    repo, cfg = _repo(tmp_path)
    (repo / "tests" / "link_test.py").symlink_to("../launcher/target.txt")
    problems = gates.zone_symlink_gate(cfg)
    assert any("tests/link_test.py" in p for p in problems), problems


def test_gate_names_dangling_symlink(tmp_path):
    # islink fires on dangling links too — the target need not exist.
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "dangling").symlink_to("../launcher/missing")
    problems = gates.zone_symlink_gate(cfg)
    assert any("src/dangling" in p for p in problems), problems


def test_gate_names_zone_directory_itself(tmp_path):
    # `src -> ../launcher`: the zone root is the link; no walk would even
    # see its contents as zone content.
    repo = tmp_path / "repo"
    (repo / "launcher").mkdir(parents=True)
    (repo / "src").symlink_to("launcher")
    for d in ("tests", "docs", "scripts"):
        (repo / d).mkdir()
    problems = gates.zone_symlink_gate(Config(repo_root=str(repo)))
    assert any(p.startswith("src") for p in problems), problems


# --- 6: clean zones pass ----------------------------------------------------------

def test_gate_clean_zones_return_empty(tmp_path):
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "mod.py").write_text("x = 1\n")
    (repo / "src" / "pkg").mkdir()
    (repo / "src" / "pkg" / "deep.py").write_text("y = 2\n")
    (repo / "tests" / "a_test.py").write_text("def test_a():\n    assert 1\n")
    assert gates.zone_symlink_gate(cfg) == []


# --- 7: full path rc=13 -----------------------------------------------------------

def test_full_path_rc13(tmp_path):
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "launcher").mkdir()
    (repo / "tickets").mkdir()
    (repo / "launcher" / "target.txt").write_text("regular file\n")
    # The symlink must be COMMITTED so the tree is clean (dirty_tree_gate
    # passes) and the zone-symlink gate is what catches it (rc=13, not rc=22).
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    (repo / "tickets" / "TASK-TEST.md").write_text("# test ticket\n")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git"] + args, cwd=repo, check=True, capture_output=True)
    env = dict(os.environ)
    env["STANOK_REPO"] = str(repo)
    label = "zoneban-rc13"
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER_DIR / "stanok.py"),
         "run", str(repo / "tickets" / "TASK-TEST.md"), label],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 13, proc.stdout + proc.stderr
    # The abort message is actionable: names the path and the fix (operator
    # point 5: an accidental operator-side symlink must say what to do).
    out = proc.stdout + proc.stderr
    assert "src/link" in out
    sum_path = repo / "evidence" / label / "summary.json"
    assert sum_path.is_file()
    data = json.loads(sum_path.read_text())
    assert data["probe_result"] == "EARLY-ABORT"
    assert data["rc"] == 13


# --- 8: hard links cannot escape a zone (the scanner's deliberate gap) ---------

@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_docker_hardlink_across_mounts_fails(tmp_path):
    # The hard-link answer (operator review 2026-10-09): the scanner does NOT
    # look for hard links, and this test proves why that is safe: the mount
    # topology (sandbox._mount_specs: base repo :ro, each writable zone a
    # separate rw bind) makes ln() from a zone to a file outside it cross
    # mounts -> EXDEV. A hard link inside ONE zone stays inside it. The
    # conclusion is verified at the Docker layer, not assumed from topology.
    repo = tmp_path / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "launcher").mkdir()
    (repo / "launcher" / "target.txt").write_text("regular file\n")
    image = os.environ.get("STANOK_DOCKER_IMAGE", "stanok-machine:latest")
    proc = subprocess.run(
        ["docker", "run", "--rm",
         "--user", f"{os.getuid()}:{os.getgid()}",
         "-v", f"{repo}:{repo}:ro",
         "-v", f"{repo}/src:{repo}/src:rw",
         image, "bash", "-c", f"ln {repo}/launcher/target.txt {repo}/src/hard"],
        capture_output=True, text=True, timeout=180)
    out = proc.stdout + proc.stderr
    assert proc.returncode != 0, out
    assert "cross-device" in out.lower(), out
    assert not (repo / "src" / "hard").exists()
