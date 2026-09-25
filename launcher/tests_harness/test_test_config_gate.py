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

CC-151 (stack-agnostic, manifest-driven): the forbidden set is the union of
the `verdict_config` lists in scripts/stacks/*.toml, not a hardcoded py
tuple. Cases 1-4 run in repos with NO manifests -> the fail-closed fallback
(legacy py set) applies, so they are unchanged. New cases:
  6  py manifest declares the py set -> tests/conftest.py flagged (True)
  7  js manifest (verdict_config=[]) -> a js test file is clean (False), and
     a conftest.py-named file is NOT inherited from py's list (False)
  8  jq manifest (verdict_config=[]) -> a .json test file is clean (False)
  9  a manifest declaring a custom pattern -> that file is flagged (True),
     proving the guard reads the manifest, not a hardcoded tuple

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


# CC-151: minimal manifests (only `ext` + `verdict_config`; the guard reads
# only verdict_config). One manifest per repo so the union is unambiguous.
PY_MANIFEST = (
    'ext = "py"\n'
    'verdict_config = ["conftest.py", "pytest.ini", "tox.ini", '
    '"setup.cfg", "pyproject.toml"]\n'
)
JS_MANIFEST = 'ext = "js"\nverdict_config = []\n'
JQ_MANIFEST = 'ext = "jq"\nverdict_config = []\n'
CUSTOM_MANIFEST = 'ext = "zz"\nverdict_config = ["custom_verdict.ini"]\n'


def _repo_with_manifest(tmp_path, manifest_name, manifest_body, rel, body):
    repo = tmp_path / "repo"
    m = repo / "scripts" / "stacks" / manifest_name
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(manifest_body, encoding="utf-8")
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


# --- 6: py manifest-driven (CC-151) -------------------------------------------

def test_py_manifest_conftest_flagged(tmp_path, monkeypatch):
    repo = _repo_with_manifest(
        tmp_path, "py.toml", PY_MANIFEST,
        "tests/conftest.py",
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 0\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is True


# --- 7: js stack not over-blocked (CC-151) -------------------------------------

def test_js_stack_test_file_clean(tmp_path, monkeypatch):
    # js declares no verdict_config -> a js test file is clean.
    repo = _repo_with_manifest(
        tmp_path, "js.toml", JS_MANIFEST,
        "tests/calc.test.js", "const test = require('node:test');\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is False


def test_js_stack_does_not_inherit_py_list(tmp_path, monkeypatch):
    # The manifest is authoritative: a js-only repo does NOT inherit py's
    # conftest.py ban (no cross-stack over-blocking).
    repo = _repo_with_manifest(
        tmp_path, "js.toml", JS_MANIFEST,
        "tests/conftest.py",
        "def pytest_sessionfinish(session, exitstatus):\n"
        "    session.exitstatus = 0\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is False


# --- 8: jq stack not over-blocked (CC-151) -------------------------------------

def test_jq_stack_test_file_clean(tmp_path, monkeypatch):
    repo = _repo_with_manifest(
        tmp_path, "jq.toml", JQ_MANIFEST,
        "tests/data.json", "{}\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is False


# --- 9: manifest is authoritative (custom pattern) (CC-151) -------------------

def test_custom_manifest_pattern_flagged(tmp_path, monkeypatch):
    # A manifest declaring a non-py verdict_config pattern is enforced —
    # proves the guard reads the manifest, not a hardcoded py tuple.
    repo = _repo_with_manifest(
        tmp_path, "zz.toml", CUSTOM_MANIFEST,
        "tests/custom_verdict.ini", "[v]\n")
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    assert stanok.test_config_gate() is True
