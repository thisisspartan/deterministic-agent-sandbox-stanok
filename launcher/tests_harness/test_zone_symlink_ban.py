"""Zone-symlink ban (cc217 review follow-up, operator decision 2026-10-09).

The unified rule: in the writable zones (src/tests/docs/scripts) symlinks do
not exist. Two enforcement points, ONE scanner (gates.zone_symlinks):

  1. LAUNCH (gates.zone_symlink_gate, wired into cli._launch_gates after the
     hidden-files gate, rc=13): any symlink — file, directory, dangling, or
     the zone directory itself — refuses the launch, with the path list and
     the fix. The container mounts the repo :ro and derives rw carve-outs
     only inside the zones; Docker resolves a bind source's realpath, so a
     link hands its TARGET rw access (the `src/link -> launcher/` incident,
     proven by test_docker_bind_resolves_symlink_source). The ban covers
     UNDECLARED links (the declared-path rule inspects only declared paths)
     and links under tests/ (the protected-file location — host_ro_paths
     would otherwise bind them :ro verbatim and Docker would resolve them).
  2. POST-TURN (verify._check_zone_symlinks, called from
     session._post_turn_decision): a symlink created by the model during the
     run is a contract_lock violation -> the existing forced-FAIL path
     (CONTRACT-FAIL, no retry). Compared against the session-start snapshot,
     NOT the ticket — a ticket never declares arbitrary links.

Tests:
  1  symlink file in src/ -> gate names it
  2  symlink directory in src/ -> gate names it (dir links included)
  3  symlink under tests/ -> gate names it (the protected-file location)
  4  dangling symlink -> gate names it (target need not exist)
  5  the zone directory itself is a symlink -> gate names it
  6  clean zones (regular files/dirs) -> gate returns []
  7  full path: committed symlink in src/ -> launch rc=13, EARLY-ABORT summary
  8  post-turn: new symlink after the snapshot -> contract_lock violation ->
     forced FAIL (the existing _contract_lock_forced_fail path)
  9  post-turn: link present in the baseline snapshot -> no violation
 10  post-turn: clean -> no violation
 11  wiring: _post_turn_decision runs the scan and returns the forced rc=1
 12  hard links: ln() from a zone to a repo file fails in Docker (EXDEV) —
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

from launcher import gates, session, verify
from launcher.config import Config
from launcher.plan import SessionPlan

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


# --- 8-10: post-turn scan -> the existing forced-FAIL path ------------------------

def test_new_symlink_after_snapshot_forces_contract_fail(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = gates.zone_symlinks(cfg)  # the session-start snapshot: clean
    assert before == []
    # Simulate the model creating a link between turns.
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    job = {}
    verify._check_zone_symlinks(cfg, before, job, 1)
    assert job["contract_lock_violations"] == ["turn 1: NEW-SYMLINK: src/link"]
    assert verify._contract_lock_forced_fail(job, 1) == 1
    assert job["verifier"] == "FAIL"


def test_baseline_symlink_not_flagged(tmp_path):
    # Compared against the snapshot, not the ticket: a link that already
    # existed at session start is not a NEW one (the launch gate is what
    # refuses it there — the post-turn rule only bans links created mid-run).
    repo, cfg = _repo(tmp_path)
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    before = gates.zone_symlinks(cfg)
    assert before == ["src/link"]
    job = {}
    verify._check_zone_symlinks(cfg, before, job, 2)
    assert "contract_lock_violations" not in job
    assert verify._contract_lock_forced_fail(job, 2) is None


def test_clean_turn_no_violation(tmp_path):
    repo, cfg = _repo(tmp_path)
    before = gates.zone_symlinks(cfg)
    (repo / "src" / "mod.py").write_text("x = 1\n")
    job = {}
    verify._check_zone_symlinks(cfg, before, job, 1)
    assert "contract_lock_violations" not in job


# --- 11: wiring — _post_turn_decision runs the scan -------------------------------

def test_post_turn_decision_forces_fail_on_new_symlink(tmp_path, monkeypatch):
    repo, cfg = _repo(tmp_path)
    before = gates.zone_symlinks(cfg)
    (repo / "src" / "link").symlink_to("../launcher/target.txt")
    # With the order contract (forced FAIL before verify_gate, operator
    # review 2026-10-09) verify_gate is never reached — the stub is only a
    # guard: the test pins that the scan feeds the forced-FAIL path BEFORE
    # any test execution.
    monkeypatch.setattr(session, "verify_gate", lambda cfg, plan: (True, [], False))
    plan = SessionPlan(declared_paths=(), edit_paths=())
    result = session.TurnResult(usage={}, live_window={}, writes=1, error="",
                                loop_trap=None)
    job = {"turn_telemetry": [{"input_tokens": 100}]}
    rc, next_prompt = session._post_turn_decision(
        cfg, job, 1, 3, plan, result, {}, before, 100, 100)
    assert rc == 1
    assert job["verifier"] == "FAIL"
    assert any("NEW-SYMLINK: src/link" in msg for _, msg in job["failures"])


# --- 12: hard links cannot escape a zone (the scanner's deliberate gap) ---------

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
