"""Acceptance tests for src/pod_guard.py (TASK-STANOK-CC-233).

In-Pod proof that the Pod-only test guard (CC-232) is actually active in both
runner Pods: the STANOK_IN_POD marker is present in the running Pod, and the
designated writable zone (/stanok-work emptyDir) accepts writes.
"""

import os

import pytest

from src.pod_guard import in_pod, write_ok

# CC-232 (operator-approved host-side guard): the invariants below are
# Pod-only — the STANOK_IN_POD marker and the /stanok-work emptyDir exist
# only in the runner Pods (both Job templates set STANOK_IN_POD=1). On the
# host they are false failures; the fresh Job runs this suite INSIDE the Pod,
# where the guards are satisfied and the assertions execute unchanged.
_pod_only = pytest.mark.skipif(
    not os.environ.get("STANOK_IN_POD"),
    reason="Pod-only invariant: runs in the worker/fresh Pod (STANOK_IN_POD=1)")


def test_in_pod_marker_parsing(monkeypatch):
    # The marker is read from the environment at call time (the environment is
    # monkeypatched here, so this test runs everywhere): absent -> False,
    # "1" -> True, any other value -> False.
    monkeypatch.delenv("STANOK_IN_POD", raising=False)
    assert in_pod() is False

    monkeypatch.setenv("STANOK_IN_POD", "1")
    assert in_pod() is True

    monkeypatch.setenv("STANOK_IN_POD", "0")
    assert in_pod() is False


@_pod_only
def test_marker_present_in_pod():
    # The marker must be present in the running Pod — the guard is active.
    assert in_pod() is True


@_pod_only
def test_work_zone_writable():
    # /stanok-work (emptyDir) is the designated writable zone in both Pods;
    # a uniquely-named probe file must be creatable and removable there.
    assert write_ok("/stanok-work") is True
