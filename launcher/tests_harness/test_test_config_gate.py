"""W6 — test_config_gate (hermetic).

Owner decision A: pytest config files under tests/ can subvert the verdict
(a `conftest.py` with `pytest_sessionfinish: session.exitstatus = 0` turns a
failing test into rc=0; tests/ is writable and contract_lock only hashes
files that existed at start). The gate rejects a launch (rc=27) when
tests/ holds conftest.py / pytest.ini / tox.ini / setup.cfg / pyproject.toml
(any depth — pytest picks up conftest.py from every directory on the test
file's path).

  1  tests/conftest.py -> gate True
  2  nested tests/unit/conftest.py -> gate True (recursive)
  3  tests/pyproject.toml -> gate True
  4  tests/ with only *_test.py -> gate False (clean)
  5  full path: committed conftest (exitstatus=0) + a failing test ->
     process rc=27, evidence/<label>/summary.json EARLY-ABORT (verdict FAIL,
     not PASS)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_test_config_gate.py -q
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

FORBIDDEN = ("conftest.py", "pytest.ini", "tox.ini", "setup.cfg", "pyproject.toml")


def _repo_with(tmp_path, rel, body):
    repo = tmp_path / "repo"
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return repo


# --- 1: conftest.py in tests/ -------------------------------------------------

def test_conftest_in_tests_flagged(tmp_path, monkeypatch):
    repo = _repo_with(tmp_path, "tests/conftest.py",
                      "def pytest_sessionfinish(session, exitstatus):\n"
                      "    session.exitstatus = 0\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is True


# --- 2: nested conftest.py -----------------------------------------------------

def test_nested_conftest_flagged(tmp_path, monkeypatch):
    repo = _repo_with(tmp_path, "tests/unit/conftest.py",
                      "def pytest_sessionfinish(session, exitstatus):\n"
                      "    session.exitstatus = 0\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is True


# --- 3: pyproject.toml in tests/ ------------------------------------------------

def test_pyproject_in_tests_flagged(tmp_path, monkeypatch):
    repo = _repo_with(tmp_path, "tests/pyproject.toml",
                      "[tool.pytest.ini_options]\naddopts = '--exitfirst'\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is True


# --- 4: clean tests/ -----------------------------------------------------------

def test_clean_tests_not_flagged(tmp_path, monkeypatch):
    repo = _repo_with(tmp_path, "tests/csv_test.py",
                      "def test_ok():\n    assert True\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is False


# --- 5: full path rc=27 ---------------------------------------------------------

def test_full_path_rc27(tmp_path):
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "tickets").mkdir()
    (repo / "Dockerfile").write_text("FROM scratch\n")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "run.sh").write_text("#!/usr/bin/env bash\nexit 0\n")
    # The conftest MUST be committed so the tree is clean (dirty_tree_gate
    # passes) and the test_config_gate is what catches it (rc=27, not rc=22).
    (repo / "tests" / "conftest.py").write_text(
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 0\n", encoding="utf-8")
    (repo / "tests" / "fail_test.py").write_text(
        "def test_fails():\n    assert False\n", encoding="utf-8")
    (repo / "tickets" / "TASK-TEST.md").write_text("# test ticket\n")
    for args in (["init", "-q"], ["add", "-A"],
                 ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "-m", "init"]):
        subprocess.run(["git"] + args, cwd=repo, check=True, capture_output=True)
    env = dict(os.environ)
    env["STANOK_REPO"] = str(repo)
    label = "w6-rc27"
    proc = subprocess.run(
        [sys.executable, str(LAUNCHER_DIR / "stanok.py"),
         "run", "tickets/TASK-TEST.md", label, "--direct"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 27, proc.stdout + proc.stderr
    sum_path = repo / "evidence" / label / "summary.json"
    assert sum_path.is_file()
    data = json.loads(sum_path.read_text())
    assert data["probe_result"] == "EARLY-ABORT"
    assert data["rc"] == 27
    assert data["verifier"] == "FAIL"
