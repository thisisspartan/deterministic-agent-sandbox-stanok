"""Runner-independent run.sh pins — fake uv/timeout shims.

These pins do not depend on the concrete test runner: a fake `uv`
and `timeout` on PATH record their argv and fd 0, so the pins hold for
ANY runner command line in the STACKS registry. (A real pytest/node
replaces or ignores stdin, so a stdin-reading test cannot prove
`</dev/null`; a source regex is satisfied by a comment — the shims
observe the actual process.)

  R1   `test` runs with a 60s timeout and stdin </dev/null
  R2   `smoke` runs with a 10s timeout and stdin </dev/null
  R3   `test` runs ALL args even when one fails (no early exit)
  R4   ENV-FAIL: an unavailable runner exits 6 (not a red test)

Same hermetic pattern as test_runsh_pins.py: copy the live run.sh into a
tmpdir repo (scripts/ + tests/ + src/ + bin/ shims). Linux-only
(/proc/self/fd).

Run: .venv/bin/python -m pytest launcher/tests_harness/test_runsh_runner_pins.py -q
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = REPO_ROOT / "scripts" / "run.sh"

PY_PASS = "def test_ok():\n    assert 1 == 1\n"

# The shims log their argv + fd 0 to $LOG, then exec the real command.
TIMEOUT_SHIM = (
    'echo "timeout $1" >> "$LOG"\n'
    'shift\n'
    'exec "$@"\n'
)
UV_OK = (
    'echo "uv $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'exit 0\n'
)
UV_FAIL_A = (
    'echo "uv $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'case "$*" in *a_test.py*) exit 1 ;; esac\n'
    'exit 0\n'
)
UV_FAIL_VERSION = (
    'case "$*" in *--version*) exit 1 ;; esac\n'
    'echo "uv $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'exit 0\n'
)


def build(tmp_path: Path, py_body: str) -> Path:
    """A hermetic repo: live run.sh + fake uv/timeout shims on PATH."""
    (tmp_path / "scripts").mkdir()
    shutil.copy(RUNSH, tmp_path / "scripts" / "run.sh")
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "bin").mkdir()
    (tmp_path / "bin" / "timeout").write_text(TIMEOUT_SHIM, encoding="utf-8")
    (tmp_path / "bin" / "uv").write_text(py_body, encoding="utf-8")
    for p in ("bin/timeout", "bin/uv"):
        (tmp_path / p).chmod(0o755)
    (tmp_path / "tests" / "a_test.py").write_text(PY_PASS, encoding="utf-8")
    (tmp_path / "tests" / "b_test.py").write_text(PY_PASS, encoding="utf-8")
    (tmp_path / "src" / "a.py").write_text("print('ok')\n", encoding="utf-8")
    return tmp_path


def run_sh(repo: Path, log: Path, *args: str, timeout: int = 90) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PATH"] = f"{repo / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
    env["LOG"] = str(log)
    # stdin is an OPEN pipe on purpose: if run.sh forgot `</dev/null`, the
    # shim's readlink /proc/self/fd/0 would show the pipe, not /dev/null.
    return subprocess.run(
        ["bash", "scripts/run.sh", *args],
        cwd=repo, env=env, capture_output=True, text=True,
        timeout=timeout, stdin=subprocess.PIPE,
    )


# --- R1: test keeps the 60s timeout and stdin </dev/null ---------------------

def test_r1_test_timeout_60_and_stdin_dev_null(tmp_path):
    repo = build(tmp_path, UV_OK)
    log = tmp_path / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py")
    assert p.returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "timeout 60" in lines
    a_lines = [ln for ln in lines if "a_test.py" in ln]
    assert a_lines, f"a_test.py never ran: {lines}"
    assert all("stdin=/dev/null" in ln for ln in a_lines)


# --- R2: smoke keeps the 10s timeout and stdin </dev/null --------------------

def test_r2_smoke_timeout_10_and_stdin_dev_null(tmp_path):
    repo = build(tmp_path, UV_OK)
    log = tmp_path / "log.txt"
    p = run_sh(repo, log, "smoke", "src/a.py")
    assert p.returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "timeout 10" in lines
    a_lines = [ln for ln in lines if "src/a.py" in ln]
    assert a_lines, f"src/a.py never ran: {lines}"
    assert all("stdin=/dev/null" in ln for ln in a_lines)


# --- R3: test runs all args on partial failure (no early exit) ---------------

def test_r3_test_runs_all_args_on_partial_failure(tmp_path):
    repo = build(tmp_path, UV_FAIL_A)
    log = tmp_path / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py", "tests/b_test.py")
    assert p.returncode != 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert any("a_test.py" in ln for ln in lines)
    assert any("b_test.py" in ln for ln in lines)


# --- R4: ENV-FAIL — an unavailable runner exits 6, not a red test ------------

def test_r4_env_fail_unavailable_runner_rc6(tmp_path):
    repo = build(tmp_path, UV_FAIL_VERSION)
    log = tmp_path / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py")
    assert p.returncode == 6
    assert "ENV-FAIL" in p.stderr
