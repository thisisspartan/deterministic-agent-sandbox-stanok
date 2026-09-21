"""run.sh contract suite — 26 hermetic cases against the REAL scripts/run.sh.

Copies the live run.sh into a tmpdir repo (scripts/ + tests/ + src/) and
pins the fixed contract:
  - strict charset on test/smoke args (rc=2 on shape violations),
  - SEC-01 realpath containment in tests/ (no symlink in any component,
    no traversal escape — rc=1),
  - timeouts (smoke: 10s kill -> rc=124),
  - `list`: a single globally sorted, unique stream (sort -u semantics),
  - rc=2 on unknown extensions and wrong argument counts.

Run: .venv/bin/python -m pytest launcher/tests_harness/test_runsh_contract.py -q
"""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNSH = REPO_ROOT / "scripts" / "run.sh"

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
# pytest-style: the py test-runner is `uv run --no-project pytest -q`, so a
# bare module-level assert would give rc=5 ("no tests ran") even when true.
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
    # The py stack's runner is `uv run --no-project pytest ...`: uv resolves
    # the environment via VIRTUAL_ENV first. Point it at the venv that runs
    # this suite (it carries pytest; the host system python may not).
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


# --- list (5) ---------------------------------------------------------------

def test_list_empty(repo):
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.strip() == ""


def test_list_js_sorted_unique(repo):
    write(repo / "tests" / "a.test.js", JS_PASS)
    write(repo / "tests" / "sub" / "b.test.js", JS_PASS)
    write(repo / "tests" / "sub" / "deep" / "c.test.js", JS_PASS)
    p = run(repo, "list")
    assert p.returncode == 0
    lines = p.stdout.splitlines()
    assert lines == sorted(lines)
    assert len(lines) == len(set(lines)) == 3


def test_list_py_sorted_unique(repo):
    write(repo / "tests" / "a_test.py", PY_PASS)
    write(repo / "tests" / "sub" / "b_test.py", PY_PASS)
    write(repo / "tests" / "sub" / "deep" / "c_test.py", PY_PASS)
    p = run(repo, "list")
    assert p.returncode == 0
    lines = p.stdout.splitlines()
    assert lines == sorted(lines)
    assert len(lines) == len(set(lines)) == 3


def test_list_mixed_sorted_unique(repo):
    # Adversarial names: the py path sorts BEFORE the js path, so only a
    # single globally sorted-unique stream (sort -u) passes — two separate
    # per-stack sorted blocks do not.
    write(repo / "tests" / "z.test.js", JS_PASS)
    write(repo / "tests" / "a_test.py", PY_PASS)
    p = run(repo, "list")
    assert p.returncode == 0
    lines = p.stdout.splitlines()
    assert lines == sorted(lines)
    assert len(lines) == len(set(lines)) == 2


def test_list_only_test_files(repo):
    write(repo / "tests" / "a.test.js", JS_PASS)
    write(repo / "tests" / "notes.txt", "not a test\n")
    write(repo / "src" / "x.js", "console.log(1);\n")
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["tests/a.test.js"]


# --- test subcommand (10) ---------------------------------------------------

def test_test_js_pass(repo):
    write(repo / "tests" / "a.test.js", JS_PASS)
    p = run(repo, "test", "tests/a.test.js")
    assert p.returncode == 0
    assert "=== tests/a.test.js ===" in p.stdout


def test_test_js_fail(repo):
    write(repo / "tests" / "a.test.js", JS_FAIL)
    p = run(repo, "test", "tests/a.test.js")
    assert p.returncode != 0


def test_test_py_pass(repo):
    write(repo / "tests" / "a_test.py", PY_PASS)
    p = run(repo, "test", "tests/a_test.py")
    assert p.returncode == 0


def test_test_py_fail(repo):
    write(repo / "tests" / "a_test.py", PY_FAIL)
    p = run(repo, "test", "tests/a_test.py")
    assert p.returncode != 0


def test_test_multiple_args_ok(repo):
    write(repo / "tests" / "a.test.js", JS_PASS)
    write(repo / "tests" / "b_test.py", PY_PASS)
    p = run(repo, "test", "tests/a.test.js", "tests/b_test.py")
    assert p.returncode == 0
    assert "=== tests/a.test.js ===" in p.stdout
    assert "=== tests/b_test.py ===" in p.stdout


def test_test_unknown_extension(repo):
    write(repo / "tests" / "a.test.ts", "x")
    p = run(repo, "test", "tests/a.test.ts")
    assert p.returncode == 2


def test_test_bad_charset(repo):
    write(repo / "tests" / "a b.test.js", JS_PASS)
    p = run(repo, "test", "tests/a b.test.js")
    assert p.returncode == 2


def test_test_missing_file(repo):
    p = run(repo, "test", "tests/nope.test.js")
    assert p.returncode == 2


def test_test_traversal_escape(repo):
    # The arg string passes the charset shape (.. is a legal segment), but
    # realpath resolves OUTSIDE tests/ -> SEC-01 containment, rc=7
    # (W12: security errors are disjoint from runner codes).
    write(repo / "evil.test.js", JS_PASS)
    p = run(repo, "test", "tests/../evil.test.js")
    assert p.returncode == 7


def test_test_symlink_escape(repo):
    # A symlink inside tests/ pointing outside -> SEC-01, rc=7.
    write(repo / "evil.test.js", JS_PASS)
    (repo / "tests" / "link.test.js").symlink_to("../evil.test.js")
    p = run(repo, "test", "tests/link.test.js")
    assert p.returncode == 7


# --- smoke subcommand (5) ---------------------------------------------------

def test_smoke_js_ok(repo):
    write(repo / "src" / "ok.js", "console.log('ok');\n")
    p = run(repo, "smoke", "src/ok.js")
    assert p.returncode == 0


def test_smoke_py_ok(repo):
    write(repo / "src" / "ok.py", "print('ok')\n")
    p = run(repo, "smoke", "src/ok.py")
    assert p.returncode == 0


def test_smoke_timeout(repo):
    # A 15s program must be killed by the 10s smoke timeout -> rc=124.
    write(repo / "src" / "slow.js", "setTimeout(() => {}, 15000);\n")
    t0 = time.monotonic()
    p = run(repo, "smoke", "src/slow.js", timeout=60)
    elapsed = time.monotonic() - t0
    assert p.returncode == 124
    assert elapsed < 14


def test_smoke_unknown_extension(repo):
    write(repo / "src" / "a.ts", "x")
    p = run(repo, "smoke", "src/a.ts")
    assert p.returncode == 2


def test_smoke_multiple_args(repo):
    write(repo / "src" / "a.js", "console.log(1);\n")
    write(repo / "src" / "b.js", "console.log(2);\n")
    p = run(repo, "smoke", "src/a.js", "src/b.js")
    assert p.returncode == 2


# --- W12: unregistered test-like files in `list` ---------------------------

def test_list_unregistered_test_like_fails(repo):
    # The reviewer's case: a test-like file no registry line claims must not
    # be SILENT in `list` (old behavior: not listed, verify_gate = PASS).
    write(repo / "tests" / "ok_test.py", PY_PASS)
    write(repo / "tests" / "calc_test.go", "package main\n")
    p = run(repo, "list")
    assert p.returncode == 1
    assert "tests/calc_test.go" in p.stderr
    # The registered file is still listed on stdout.
    assert "tests/ok_test.py" in p.stdout


def test_list_registered_only_passes(repo):
    write(repo / "tests" / "ok_test.py", PY_PASS)
    write(repo / "tests" / "a.test.js", JS_PASS)
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["tests/a.test.js", "tests/ok_test.py"]


def test_list_fixture_dir_exempt(repo):
    # Files under a fixtures/ or data/ directory are not test-like, even
    # when their name contains "test". (A .json fixture would ALSO be
    # claimed by the jq registry line — use a .txt name to isolate the
    # fixture-dir exemption.)
    write(repo / "tests" / "ok_test.py", PY_PASS)
    write(repo / "tests" / "fixtures" / "test_vectors.txt", "1 2 3\n")
    write(repo / "tests" / "data" / "test_samples.txt", "a b c\n")
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["tests/ok_test.py"]


def test_list_pycache_dir_exempt(repo):
    # A .pyc cache artifact under tests/__pycache__/ is not a test: the W12
    # unregistered-test-like check must not fire on it (w12-verify: the
    # verifier's pytest run regenerated the .pyc and `list` went red).
    write(repo / "tests" / "ok_test.py", PY_PASS)
    write(repo / "tests" / "__pycache__" / "ok_test.cpython-311-pytest-8.3.3.pyc", "x")
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["tests/ok_test.py"]


def test_list_non_test_named_file_silent(repo):
    # A non-test-like helper file (no "test" in the name) is not flagged.
    write(repo / "tests" / "ok_test.py", PY_PASS)
    write(repo / "tests" / "helpers.py", "def f():\n    return 1\n")
    p = run(repo, "list")
    assert p.returncode == 0
    assert p.stdout.splitlines() == ["tests/ok_test.py"]


# --- W12: rc table pins ------------------------------------------------------

def test_rc_table_runner_2_remapped_to_1(repo):
    # A runner that itself exits 2 (pytest: interrupted) must surface as
    # rc=1 (a test failed), not run.sh's refusal code 2.
    write(repo / "tests" / "a_test.py", PY_PASS)
    # Simulate: temporarily replace the py runner via a fake uv on PATH.
    bin = repo / "bin"
    bin.mkdir()
    fake_uv = bin / "uv"
    fake_uv.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "$*" == *"--version"* ]]; then exit 0; fi\n'
        "exit 2\n",
    )
    fake_uv.chmod(0o755)
    env = dict(os.environ)
    env["PATH"] = f"{bin}:{env['PATH']}"
    env["VIRTUAL_ENV"] = os.path.dirname(os.path.dirname(sys.executable))
    p = subprocess.run(
        ["bash", "scripts/run.sh", "test", "tests/a_test.py"],
        cwd=repo, env=env, capture_output=True, text=True, timeout=90,
    )
    assert p.returncode == 1, f"expected rc=1 (remapped), got {p.returncode}"
