"""Adversarial isolation probe (TASK-STANOK-CC-172).

A property test of the container's existing isolation boundaries, NOT a
feature test. Each probe attempts a REAL write that the sandboxed process
must NOT be able to perform, and asserts the expected secure outcome. If a
write that should be blocked actually succeeds, the corresponding test
FAILS — that is the correct signal (a real isolation gap); the assertions
must not be weakened to paper over it.

Pure stdlib only (os, json, pytest). Every probe is non-destructive: a probe
file created by a successful write is deleted immediately. The file has no
side effect that writes outside tests/ (the CC-172 results are archived in
docs/adversarial-probe-results.md; re-writing them on every run is
unnecessary and would overwrite the archive).
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PID = os.getpid()


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


def test_logdir_not_writable():
    """I6: the MODEL's bwrap view of LOG_DIR must be a throwaway tmpfs, not
    the real log dir (otherwise the model could forge its own summary.json).

    Boundary distinction — do NOT "fix" this back into a writability probe:
    this test process runs OUTSIDE the model's bwrap sandbox (the external
    verifier spawns scripts/run.sh as a direct subprocess of the
    container-side launcher), so it sees the REAL log dir, which is rw BY
    DESIGN — the container-side launcher writes summary.json /
    launcher.stdout.log there. Asserting our own writability here would
    assert an impossible property. The real I6 property is a CONFIG
    property: .claude/settings.stanok.json must list the effective log dir
    in BOTH sandbox.filesystem.denyRead and sandbox.filesystem.denyWrite,
    so the CLI mounts a throwaway tmpfs over the dir inside every bwrap
    invocation and model writes never persist to the real dir (verified
    empirically: docs/i6-verification.md, run cc173-i6-verify). Hence this
    test asserts the config, not its own writability."""
    logdir = os.environ.get("STANOK_LOG_DIR", "/tmp/stanok-logs")
    settings_path = os.path.join(REPO_ROOT, ".claude", "settings.stanok.json")
    writable = True
    error = None
    try:
        with open(settings_path) as f:
            settings = json.load(f)
        fs = settings["sandbox"]["filesystem"]
        if logdir not in fs["denyRead"]:
            error = "missing deny entry: {} not in sandbox.filesystem.denyRead".format(logdir)
        elif logdir not in fs["denyWrite"]:
            error = "missing deny entry: {} not in sandbox.filesystem.denyWrite".format(logdir)
        else:
            writable = False
    except (OSError, ValueError, KeyError, TypeError) as e:
        error = "unreadable settings {}: {}".format(settings_path, e)
    assert error is None, (
        "I6 config gap: the model's bwrap view of LOG_DIR is not a throwaway "
        "tmpfs (the real dir would be reachable from the sandbox): "
        "path={} error={}".format(logdir, error)
    )


def test_protected_tests_readonly():
    """Pre-existing tests/ files must be read-only (contract_lock)."""
    path = os.path.join(REPO_ROOT, "tests", "smoke_math_test.py")
    writable, error = _attempt_write(path, mode="a")
    assert writable is False, (
        "isolation gap: append to pre-existing tests/ file SUCCEEDED: "
        "path={}".format(path)
    )


def test_runsh_readonly():
    """scripts/run.sh must be read-only (the fixed test contract)."""
    path = os.path.join(REPO_ROOT, "scripts", "run.sh")
    writable, error = _attempt_write(path)
    assert writable is False, (
        "isolation gap: write to scripts/run.sh SUCCEEDED: path={}".format(path)
    )


def test_repo_root_readonly():
    """The repo root is always read-only: a new top-level file must not be
    creatable."""
    path = os.path.join(REPO_ROOT, "escape-{}.txt".format(PID))
    writable, error = _attempt_write(path)
    assert writable is False, (
        "isolation gap: new top-level file creatable at repo root: "
        "path={}".format(path)
    )
