"""run.sh mutation pins — one hermetic test per surviving mutation.

Mutation testing of scripts/run.sh found 11 mutations (M1-M11). The
runner-behavior pins (M2/M3/M4/M9/M10) moved to
test_runsh_runner_pins.py (fake python3/timeout shims — runner-independent).
The pins surviving here:

  M1   smoke accepts files strictly from src/ (SEC-01: no traversal,
       no symlink, no other directory)
  M11  `list` fails when tests/ is missing

Same hermetic pattern: copy the live run.sh into a tmpdir repo
(scripts/ + tests/ + src/).

Run: .venv/bin/python -m pytest launcher/tests_harness/test_runsh_pins.py -q
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = REPO_ROOT / "scripts" / "run.sh"

PY_PASS = "def test_ok():\n    assert 1 == 1\n"


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


# --- M11: list fails when tests/ is missing ----------------------------------

def test_m11_list_missing_tests_dir(repo):
    shutil.rmtree(repo / "tests")
    p = run(repo, "list")
    assert p.returncode != 0
