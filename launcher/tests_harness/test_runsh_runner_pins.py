"""Runner-independent run.sh pins — fake python3/timeout shims.

These pins do not depend on the concrete test runner: a fake `python3`
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
import subprocess
import sys
from pathlib import Path

from conftest import PY_PASS

# The shims log their argv + fd 0 to $LOG, then exec the real command.
# CC-168: run.sh derives the STACKS registry via `python3 - <dir>` (a
# tomllib heredoc) — the shims must pass THAT call through to the REAL
# python3, or the registry comes out empty and run.sh refuses (rc=2)
# before any runner runs. The real path is resolved HERE (the test
# process's PATH has no shim dir) and baked into the shim: `command -v -p`
# INSIDE the shebangless shim's exec-fallback context can resolve back to
# the shim itself (infinite recursion -> hang, observed 2026-09-26).
import shutil  # noqa: E402

REAL_PY = shutil.which("python3") or sys.executable
REGISTRY_PASS = f'if [ "$1" = "-" ]; then exec {REAL_PY} "$@"; fi\n'
TIMEOUT_SHIM = (
    'echo "timeout $1" >> "$LOG"\n'
    'shift\n'
    'exec "$@"\n'
)
PY_OK = (
    REGISTRY_PASS +
    'echo "python3 $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'exit 0\n'
)
PY_FAIL_A = (
    REGISTRY_PASS +
    'echo "python3 $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'case "$*" in *a_test.py*) exit 1 ;; esac\n'
    'exit 0\n'
)
PY_FAIL_VERSION = (
    REGISTRY_PASS +
    'case "$*" in *--version*) exit 1 ;; esac\n'
    'echo "python3 $* stdin=$(readlink /proc/self/fd/0)" >> "$LOG"\n'
    'exit 0\n'
)


def build(repo: Path, py_body: str) -> Path:
    """A hermetic repo: live run.sh + fake python3/timeout shims on PATH."""
    (repo / "bin").mkdir()
    (repo / "bin" / "timeout").write_text(TIMEOUT_SHIM, encoding="utf-8")
    (repo / "bin" / "python3").write_text(py_body, encoding="utf-8")
    for p in ("bin/timeout", "bin/python3"):
        (repo / p).chmod(0o755)
    (repo / "tests" / "a_test.py").write_text(PY_PASS, encoding="utf-8")
    (repo / "tests" / "b_test.py").write_text(PY_PASS, encoding="utf-8")
    (repo / "src" / "a.py").write_text("print('ok')\n", encoding="utf-8")
    return repo


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

def test_r1_test_timeout_60_and_stdin_dev_null(repo):
    repo = build(repo, PY_OK)
    log = repo / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py")
    assert p.returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "timeout 60" in lines
    a_lines = [ln for ln in lines if "a_test.py" in ln]
    assert a_lines, f"a_test.py never ran: {lines}"
    assert all("stdin=/dev/null" in ln for ln in a_lines)


# --- R2: smoke keeps the 10s timeout and stdin </dev/null --------------------

def test_r2_smoke_timeout_10_and_stdin_dev_null(repo):
    repo = build(repo, PY_OK)
    log = repo / "log.txt"
    p = run_sh(repo, log, "smoke", "src/a.py")
    assert p.returncode == 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert "timeout 10" in lines
    a_lines = [ln for ln in lines if "src/a.py" in ln]
    assert a_lines, f"src/a.py never ran: {lines}"
    assert all("stdin=/dev/null" in ln for ln in a_lines)


# --- R3: test runs all args on partial failure (no early exit) ---------------

def test_r3_test_runs_all_args_on_partial_failure(repo):
    repo = build(repo, PY_FAIL_A)
    log = repo / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py", "tests/b_test.py")
    assert p.returncode != 0
    lines = log.read_text(encoding="utf-8").splitlines()
    assert any("a_test.py" in ln for ln in lines)
    assert any("b_test.py" in ln for ln in lines)


# --- R4: ENV-FAIL — an unavailable runner exits 6, not a red test ------------

def test_r4_env_fail_unavailable_runner_rc6(repo):
    repo = build(repo, PY_FAIL_VERSION)
    log = repo / "log.txt"
    p = run_sh(repo, log, "test", "tests/a_test.py")
    assert p.returncode == 6
    assert "ENV-FAIL" in p.stderr
