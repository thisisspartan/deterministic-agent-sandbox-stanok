"""Shared hermetic harness for the run.sh contract suites (test_runsh_*).

Every suite copies the live scripts/run.sh into a tmpdir repo
(scripts/ + tests/ + src/) and drives it via bash. The shared pieces
live here so the suites stay one-test-per-case:
  - REPO_ROOT / RUNSH — the live run.sh under test (RUNSH_UNDER_TEST
    env override selects a different run.sh, e.g. a mutation copy),
  - JS_PASS / JS_FAIL / PY_PASS / PY_FAIL — canonical test bodies,
  - the `repo` fixture — a tmpdir repo with the live run.sh installed,
  - run() / write() — the subprocess driver and file helper.

The py stack's runner is `python3 -m pytest ...` (CC-152: the `uv run`
wrapper is dropped — the container's system python already carries
pytest). CC-156: the HOST is not equivalent — the repo's `.venv` pins
pytest 8.3.3 (matching the image), while the host's bare `python3` may
carry a newer pytest (e.g. 9.x) whose verdict/exit semantics differ. So
run() pins the interpreter: when `REPO_ROOT/.venv/bin` exists it is
prepended to PATH, making `python3` resolve to the pinned interpreter.
This is a host-side test-harness concern only — run.sh itself keeps the
bare `python3` the container needs.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = Path(os.environ.get(
    "RUNSH_UNDER_TEST", REPO_ROOT / "scripts" / "run.sh"))
# CC-156: host-side interpreter pin (pytest 8.3.3, image parity). Absent
# on a bare checkout → PATH unchanged → fall back to the host python3.
VENV_BIN = REPO_ROOT / ".venv" / "bin"

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
    # CC-148: run.sh sources the generated registry block — install it
    # alongside (the tmp repo has no manifests, so copy the committed
    # generated file, not regenerate).
    gen = REPO_ROOT / "scripts" / "stacks.generated.sh"
    if gen.is_file():
        shutil.copy(gen, tmp_path / "scripts" / "stacks.generated.sh")
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    return tmp_path


def run(repo, *args, timeout=90):
    env = dict(os.environ)
    if VENV_BIN.is_dir():
        env["PATH"] = str(VENV_BIN) + os.pathsep + env.get("PATH", "")
    return subprocess.run(
        ["bash", "scripts/run.sh", *args],
        cwd=repo, env=env, capture_output=True, text=True, timeout=timeout,
    )


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
