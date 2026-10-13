"""Zone-symlink ban (cc217 review follow-up, operator decision 2026-10-09).

The unified rule: in the writable zones (src/tests/docs/scripts) symlinks do
not exist. ONE enforcement point, ONE scanner (gates.zone_symlinks):

  LAUNCH (gates.zone_symlink_gate, wired into cli._launch_gates after the
  hidden-files gate, rc=13): any symlink — file, directory, dangling, or
  the zone directory itself — refuses the launch, with the path list and
  the fix. A link hands its TARGET the zone's access (the `src/link ->
  launcher/` incident; under the Docker path proven by bind realpath
  resolution, test_docker_bind_resolves_symlink_source — the ban survives
  the Docker-path removal, CC-258, as the unified rule). The ban covers
  UNDECLARED links (the declared-path rule inspects only declared paths)
  and links under tests/ (the protected-file location — a link there
  hides its target from the protected-file rules).

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

(CC-258 step B removed the old test 8 — the live-Docker EXDEV proof of the
Docker mount topology; the k8s topology is pinned by test_k8s_manifests.py,
the hard-link residual closure by the contract-recompute tests.)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_zone_symlink_ban.py -q
"""
import json
import os
import subprocess
import sys
from pathlib import Path

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
    # The protected-file location: a link under tests/ hides its target from
    # the protected-file rules (the GAP documented in test_ticket_zone.py,
    # closed here).
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
