"""Acceptance tests for src/bash_smoke.py (TASK-STANOK-CC-234).

In-Pod live proof that the CLI Bash tool works after the host-side fix for
the cc231/cc233 incident: the tmp root (CLAUDE_CODE_TMPDIR or /tmp) is
writable, the CLI's `claude-<uid>` directory is creatable and writable, and a
real `bash -c pwd` exits 0.
"""

import os

import pytest

from src.bash_smoke import probe, tmp_root

# CC-232 (operator-approved host-side guard): the invariants below are
# Pod-only — the writable /tmp emptyDir and the STANOK_IN_POD marker exist
# only in the runner Pods. On the host they are false failures; the fresh Job
# runs this suite INSIDE the Pod, where the guards are satisfied and the
# assertions execute unchanged.
_pod_only = pytest.mark.skipif(
    not os.environ.get("STANOK_IN_POD"),
    reason="Pod-only invariant: runs in the worker/fresh Pod (STANOK_IN_POD=1)")


def test_tmp_root_resolution(monkeypatch):
    # The tmp root is read from the environment at call time (the environment
    # is monkeypatched here, so this test runs everywhere): set -> that value,
    # unset -> "/tmp".
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", "/custom/tmp-root")
    assert tmp_root() == "/custom/tmp-root"

    monkeypatch.delenv("CLAUDE_CODE_TMPDIR", raising=False)
    assert tmp_root() == "/tmp"


def test_probe_shape():
    # probe() returns a dict with all four keys, computed facts of the right
    # types, and its tmp_root agrees with tmp_root().
    result = probe()
    assert isinstance(result, dict)
    assert set(
        ("tmp_root", "tmp_root_writable", "claude_dir_ok", "bash_runs")
    ) <= set(result)
    assert result["tmp_root"] == tmp_root()
    assert isinstance(result["tmp_root"], str)
    assert isinstance(result["tmp_root_writable"], bool)
    assert isinstance(result["claude_dir_ok"], bool)
    assert isinstance(result["bash_runs"], bool)


@_pod_only
def test_tmp_root_writable_in_pod():
    # Inside the Pod the tmp root must be writable and the CLI's
    # `claude-<uid>` directory must be creatable and writable — the
    # cc231/cc233 incident was exactly this creation failing.
    result = probe()
    assert result["tmp_root_writable"] is True
    assert result["claude_dir_ok"] is True


@_pod_only
def test_bash_runs_in_pod():
    # A real `bash -c pwd` succeeds in the Pod.
    assert probe()["bash_runs"] is True
