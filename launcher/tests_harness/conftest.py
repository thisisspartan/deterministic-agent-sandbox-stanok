"""Shared hermetic harness for the run.sh contract suites (test_runsh_*).

Every suite copies the live scripts/run.sh into a tmpdir repo
(scripts/ + tests/ + src/) and drives it via bash. The shared pieces
live here so the suites stay one-test-per-case:
  - REPO_ROOT / RUNSH — the live run.sh under test (RUNSH_UNDER_TEST
    env override selects a different run.sh, e.g. a mutation copy),
  - JS_PASS / JS_FAIL / PY_PASS / PY_FAIL — canonical test bodies,
  - the `repo` fixture — a tmpdir repo with the live run.sh installed,
  - run() / write() — the subprocess driver and file helper.

The py stack's runner is `uv run --no-project pytest ...`: uv resolves
the environment via VIRTUAL_ENV first. run() points it at the venv that
runs this suite (it carries pytest; the host system python may not).
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = Path(os.environ.get(
    "RUNSH_UNDER_TEST", REPO_ROOT / "scripts" / "run.sh"))

JS_PASS = (
    "const test = require('node:test');\n"
    "const assert = require('node:assert');\n"
    "test('ok', () => { assert.ok(1); });\n"
)
JS_FAIL = (
    "const test = require('node:test');\n"
    "const assert = require('node:assert');\n"
    "test('bad', () => { assert.strictEqual(1, 2); });\n"
)
PY_PASS = "def test_ok():\n    assert 1 == 1\n"
PY_FAIL = "def test_bad():\n    assert 1 == 2\n"


@pytest.fixture
def repo(tmp_path):
    (tmp_path / "scripts").mkdir()
    shutil.copy(RUNSH, tmp_path / "scripts" / "run.sh")
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def run(repo, *args, timeout=90):
    env = dict(os.environ)
    env["VIRTUAL_ENV"] = os.path.dirname(os.path.dirname(sys.executable))
    return subprocess.run(
        ["bash", "scripts/run.sh", *args],
        cwd=repo, env=env, capture_output=True, text=True, timeout=timeout,
    )


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
