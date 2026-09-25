"""Suite-mode contract tests for `run.sh test --all` (D4).

Hermetic: each test builds a temp tree (tmp_path) with a copy of the live
scripts/run.sh + scripts/stacks.generated.sh and a fresh tests/ dir, then
drives `bash scripts/run.sh` via subprocess. The real repo tree is only ever
read.

Contract under test:
- `test --all` runs EVERY file `list` would print (registry globs,
  sorted-unique), sequentially, with the same `=== <file> ===` header and
  60 s per-file timeout as the per-file `test` subcommand;
- a failing file does NOT stop the suite — all files run, rc=1 if ANY failed;
- `--all` is recognized ONLY as the sole argument to `test` (else rc=2);
- an unclaimed test-like file fails the suite with rc=1, named on stderr
  (the W12 rule, exactly as it fails `list`);
- zero test files -> rc=0, no output (an empty suite passes);
- the per-file `test <path>` path is UNCHANGED (regression guard).
"""

import shutil
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_SCRIPTS = REPO_ROOT / "scripts"

PASS_JS = "const { test } = require('node:test');\ntest('ok', () => {});\n"
PASS_PY = "def test_ok():\n    assert True\n"
FAIL_PY = "def test_fail():\n    assert False\n"


def _make_tree(tmp_path: Path, files: dict) -> Path:
    """Build a hermetic tree: live run.sh + stacks.generated.sh + tests/."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy2(LIVE_SCRIPTS / "run.sh", scripts / "run.sh")
    shutil.copy2(
        LIVE_SCRIPTS / "stacks.generated.sh", scripts / "stacks.generated.sh"
    )
    tests = tmp_path / "tests"
    tests.mkdir()
    for name, content in files.items():
        (tests / name).write_text(content)
    return tmp_path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "scripts/run.sh", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_all_passing_mixed_stacks(tmp_path):
    """One passing js + one passing py file: rc=0, both headers, sorted order."""
    root = _make_tree(tmp_path, {"b_test.py": PASS_PY, "a.test.js": PASS_JS})
    r = _run(root, "test", "--all")
    assert r.returncode == 0, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "=== tests/a.test.js ===" in r.stdout, r.stdout
    assert "=== tests/b_test.py ===" in r.stdout, r.stdout
    # sorted-unique discovery order: a.test.js before b_test.py
    assert r.stdout.index("=== tests/a.test.js ===") < r.stdout.index(
        "=== tests/b_test.py ==="
    ), r.stdout


def test_all_failing_file_does_not_stop_suite(tmp_path):
    """A failing py file among passing ones: rc=1, and ALL files still ran."""
    root = _make_tree(
        tmp_path,
        {"a.test.js": PASS_JS, "b_test.py": FAIL_PY, "c_test.py": PASS_PY},
    )
    r = _run(root, "test", "--all")
    assert r.returncode == 1, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    # the failing file's output is present
    assert "=== tests/b_test.py ===" in r.stdout, r.stdout
    assert "FAILED" in r.stdout, r.stdout
    # the passing files still ran (headers present, sorted order)
    assert "=== tests/a.test.js ===" in r.stdout, r.stdout
    assert "=== tests/c_test.py ===" in r.stdout, r.stdout
    assert (
        r.stdout.index("=== tests/a.test.js ===")
        < r.stdout.index("=== tests/b_test.py ===")
        < r.stdout.index("=== tests/c_test.py ===")
    ), r.stdout


def test_all_empty_suite(tmp_path):
    """Zero test files: rc=0, no output (an empty suite passes)."""
    root = _make_tree(tmp_path, {})
    r = _run(root, "test", "--all")
    assert r.returncode == 0, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert r.stdout == "", f"stdout must be empty: {r.stdout!r}"
    assert r.stderr == "", f"stderr must be empty: {r.stderr!r}"


def test_all_arg_shape_refused(tmp_path):
    """`--all` is recognized ONLY as the sole argument to `test` (else rc=2)."""
    root = _make_tree(tmp_path, {"a.test.js": PASS_JS})
    r = _run(root, "test", "--all", "extra")
    assert r.returncode == 2, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    r = _run(root, "test", "a.test.js", "--all")
    assert r.returncode == 2, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )


def test_all_unclaimed_test_like_file(tmp_path):
    """An unclaimed test-like file fails the suite with rc=1, named on stderr."""
    root = _make_tree(
        tmp_path, {"a.test.js": PASS_JS, "zz_test.txt": "not a test\n"}
    )
    r = _run(root, "test", "--all")
    assert r.returncode == 1, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "tests/zz_test.txt" in r.stderr, r.stderr


def test_per_file_path_unchanged(tmp_path):
    """Regression guard: per-file `test <path>` still works (rc=0, header)."""
    root = _make_tree(tmp_path, {"a.test.js": PASS_JS})
    r = _run(root, "test", "tests/a.test.js")
    assert r.returncode == 0, (
        f"rc={r.returncode}\nstdout: {r.stdout}\nstderr: {r.stderr}"
    )
    assert "=== tests/a.test.js ===" in r.stdout, r.stdout
