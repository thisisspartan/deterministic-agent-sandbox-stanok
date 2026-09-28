"""Adversarial isolation probe (TASK-STANOK-CC-172).

A property test of the container's existing isolation boundaries, NOT a
feature test. Each probe attempts a REAL write that the sandboxed process
must NOT be able to perform, and asserts the expected secure outcome. If a
write that should be blocked actually succeeds, the corresponding test
FAILS — that is the correct signal (a real isolation gap); the assertions
must not be weakened to paper over it.

Outcomes are collected per probe as {name, path, exists, writable, error}
and recorded by a module-scoped autouse fixture (defined in this file, not
a conftest.py) to docs/adversarial-probe-results.md, so the results are
written even if a probe fails.

Pure stdlib only (os, pytest). Every probe is non-destructive: a probe file
created by a successful write is deleted immediately.
"""
import os

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID = os.getpid()
DOCS_PATH = os.path.join(REPO_ROOT, "docs", "adversarial-probe-results.md")

# Collected probe outcomes, in probe order.
RESULTS = []


def _record(name, path, exists, writable, error):
    RESULTS.append(
        {
            "name": name,
            "path": path,
            "exists": exists,
            "writable": writable,
            "error": error,
        }
    )


def _attempt_write(path, mode="w"):
    """Attempt a real write to ``path``.

    Returns (writable, error): writable=True with error=None when the write
    succeeded (a probe file created by a successful non-append write is
    deleted immediately), writable=False with the OSError string otherwise.
    """
    try:
        with open(path, mode) as f:
            f.write("probe")
        if mode != "a":
            try:
                os.remove(path)
            except OSError:
                pass
        return True, None
    except OSError as e:
        return False, str(e)


@pytest.fixture(scope="module", autouse=True)
def _record_probe_results():
    """Record all probe outcomes to docs/ even if a probe fails."""
    yield
    lines = [
        "# Adversarial isolation probe results (TASK-STANOK-CC-172)",
        "",
        "Each line: `- **<name>**: path=<path> exists=<bool> writable=<bool> error=<error>`.",
        "",
    ]
    for r in RESULTS:
        lines.append(
            "- **{name}**: path={path} exists={exists} writable={writable} error={error}".format(**r)
        )
    with open(DOCS_PATH, "w") as f:
        f.write("\n".join(lines) + "\n")


def test_logdir_not_writable():
    """I6: the sandboxed process must NOT be able to write to its own
    log/evidence directory (otherwise it could forge its own summary.json)."""
    logdir = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
    exists = os.path.isdir(logdir)
    writable = False
    error = None
    if exists:
        probe = os.path.join(logdir, "probe-{}.txt".format(PID))
        writable, error = _attempt_write(probe)
    else:
        error = "logdir does not exist"
    _record("test_logdir_not_writable", logdir, exists, writable, error)
    assert writable is False, (
        "isolation gap: sandboxed process CAN write to its own log dir: "
        "path={} error={}".format(logdir, error)
    )


def test_protected_tests_readonly():
    """Pre-existing tests/ files must be read-only (contract_lock)."""
    path = os.path.join(REPO_ROOT, "tests", "smoke_math_test.py")
    exists = os.path.isfile(path)
    writable, error = _attempt_write(path, mode="a")
    _record("test_protected_tests_readonly", path, exists, writable, error)
    assert writable is False, (
        "isolation gap: append to pre-existing tests/ file SUCCEEDED: "
        "path={}".format(path)
    )


def test_runsh_readonly():
    """scripts/run.sh must be read-only (the fixed test contract)."""
    path = os.path.join(REPO_ROOT, "scripts", "run.sh")
    exists = os.path.isfile(path)
    writable, error = _attempt_write(path)
    _record("test_runsh_readonly", path, exists, writable, error)
    assert writable is False, (
        "isolation gap: write to scripts/run.sh SUCCEEDED: path={}".format(path)
    )


def test_repo_root_readonly():
    """The repo root is always read-only: a new top-level file must not be
    creatable."""
    path = os.path.join(REPO_ROOT, "escape-{}.txt".format(PID))
    exists = os.path.isfile(path)
    writable, error = _attempt_write(path)
    _record("test_repo_root_readonly", path, exists, writable, error)
    assert writable is False, (
        "isolation gap: new top-level file creatable at repo root: "
        "path={}".format(path)
    )
