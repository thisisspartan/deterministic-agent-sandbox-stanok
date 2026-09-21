"""run.sh mutation pins — one hermetic test per surviving mutation.

Mutation testing of scripts/run.sh found 11 mutations (M1-M11). The
runner-behavior pins (M2/M3/M4/M9/M10) moved to
test_runsh_runner_pins.py (fake python3/timeout shims — runner-independent).
The pins surviving here:

  M1   smoke accepts files strictly from src/ (SEC-01: no traversal,
       no symlink, no other directory) — W12: security errors are rc=7
  M11  `list` fails when tests/ is missing

Same hermetic pattern: copy the live run.sh into a tmpdir repo
(scripts/ + tests/ + src/).

Run: .venv/bin/python -m pytest launcher/tests_harness/test_runsh_pins.py -q
"""

import shutil

from conftest import PY_PASS, repo, run, write


# --- M1: smoke strictly from src/ ------------------------------------------

def test_m1_smoke_strictly_from_src(repo):
    write(repo / "evil.py", "print('ok')\n")
    # Traversal: the shape matches src/*.py, but realpath escapes src/
    # -> SEC-01 containment, rc=7 (W12: disjoint from runner codes).
    p = run(repo, "smoke", "src/../evil.py")
    assert p.returncode == 7
    # Symlink inside src/ pointing outside -> SEC-01, rc=7.
    (repo / "src" / "link.py").symlink_to("../evil.py")
    p = run(repo, "smoke", "src/link.py")
    assert p.returncode == 7
    # A file outside src/ -> shape violation, rc=2.
    write(repo / "tests" / "a_test.py", PY_PASS)
    p = run(repo, "smoke", "tests/a_test.py")
    assert p.returncode == 2


# --- M11: list fails when tests/ is missing ----------------------------------

def test_m11_list_missing_tests_dir(repo):
    shutil.rmtree(repo / "tests")
    p = run(repo, "list")
    assert p.returncode != 0
