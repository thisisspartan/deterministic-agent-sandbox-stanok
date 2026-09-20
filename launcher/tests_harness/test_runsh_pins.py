"""run.sh mutation pins — one hermetic test per surviving mutation.

Mutation testing of scripts/run.sh found 11 mutations (M1-M11); 7 survive
the contract suite and are pinned here. Each test fails if the
corresponding protection is removed (mutated) from run.sh:

  M1   smoke accepts files strictly from src/ (SEC-01: no traversal,
       no symlink, no other directory)
  M2   `test` keeps its 60s timeout (source-level pin)
  M3   `test` runs with stdin </dev/null (stdin-reading test returns
       immediately, not at the 60s timeout)
  M4   `test` runs ALL args even when one fails (no early exit)
  M9   `smoke` runs with stdin </dev/null (stdin-reading module returns
       immediately, not at the 10s timeout)
  M10  a failing pytest function returns non-zero via the py test-runner
  M11  `list` fails when tests/ is missing

Same hermetic pattern as test_runsh_contract.py: copy the live run.sh
into a tmpdir repo (scripts/ + tests/ + src/).

Run: .venv/bin/python -m pytest launcher/tests_harness/test_runsh_pins.py -q
"""

import re
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = REPO_ROOT / "scripts" / "run.sh"

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
    return subprocess.run(
        ["bash", "scripts/run.sh", *args],
        cwd=repo, capture_output=True, text=True, timeout=timeout,
    )


def write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


# --- M1: smoke strictly from src/ ------------------------------------------

def test_m1_smoke_strictly_from_src(repo):
    write(repo / "evil.py", "print('ok')\n")
    # Traversal: the shape matches src/*.py, but realpath escapes src/
    # -> SEC-01 containment, rc=1.
    p = run(repo, "smoke", "src/../evil.py")
    assert p.returncode == 1
    # Symlink inside src/ pointing outside -> SEC-01, rc=1.
    (repo / "src" / "link.py").symlink_to("../evil.py")
    p = run(repo, "smoke", "src/link.py")
    assert p.returncode == 1
    # A file outside src/ -> shape violation, rc=2.
    write(repo / "tests" / "a_test.py", PY_PASS)
    p = run(repo, "smoke", "tests/a_test.py")
    assert p.returncode == 2


# --- M2: test keeps the 60s timeout -----------------------------------------

def test_m2_test_timeout_60s():
    src = RUNSH.read_text(encoding="utf-8")
    # (?!\d) so a mutated "timeout 600" does not satisfy the pin.
    assert re.search(r"timeout 60(?!\d)", src)


# --- M3: test runs with stdin </dev/null ------------------------------------

def test_m3_test_stdin_dev_null(repo):
    # A test that reads fd 0: with </dev/null it gets b'' and passes
    # instantly; without it, it would block until the 60s timeout (rc=124).
    # os.read (not sys.stdin.read) — pytest's capture wrapper raises
    # OSError on sys.stdin reads, but fd 0 is the real /dev/null.
    write(repo / "tests" / "stdin_test.py",
          "import os\n\n\ndef test_stdin():\n    assert os.read(0, 1) == b''\n")
    t0 = time.monotonic()
    p = run(repo, "test", "tests/stdin_test.py")
    elapsed = time.monotonic() - t0
    assert p.returncode == 0
    assert elapsed < 30


# --- M4: test runs all args on partial failure ------------------------------

def test_m4_test_runs_all_args_on_partial_failure(repo):
    write(repo / "tests" / "a_test.py", PY_FAIL)
    write(repo / "tests" / "b_test.py", PY_PASS)
    p = run(repo, "test", "tests/a_test.py", "tests/b_test.py")
    assert p.returncode != 0
    # Both files were actually run (no early exit on the first failure).
    assert "=== tests/a_test.py ===" in p.stdout
    assert "=== tests/b_test.py ===" in p.stdout


# --- M9: smoke runs with stdin </dev/null ------------------------------------

def test_m9_smoke_stdin_dev_null(repo):
    # A module that reads stdin: with </dev/null it returns instantly;
    # without it, it would block until the 10s smoke timeout (rc=124).
    write(repo / "src" / "stdin.py",
          "import sys\nsys.stdin.read()\nprint('ok')\n")
    t0 = time.monotonic()
    p = run(repo, "smoke", "src/stdin.py")
    elapsed = time.monotonic() - t0
    assert p.returncode == 0
    assert elapsed < 8


# --- M10: failing pytest function -> non-zero rc ----------------------------

def test_m10_py_failing_function_nonzero(repo):
    write(repo / "tests" / "fail_test.py",
          "def test_fail():\n    assert False\n")
    p = run(repo, "test", "tests/fail_test.py")
    assert p.returncode != 0


# --- M11: list fails when tests/ is missing ----------------------------------

def test_m11_list_missing_tests_dir(repo):
    shutil.rmtree(repo / "tests")
    p = run(repo, "list")
    assert p.returncode != 0
