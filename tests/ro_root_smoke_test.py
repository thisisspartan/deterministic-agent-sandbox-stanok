"""Acceptance tests for src/ro_root_smoke.py (TASK-STANOK-CC-229).

In-Pod proof of the readOnlyRootFilesystem hardening (SPEC-READONLY-ROOT):
the root filesystem must reject writes, while the designated writable zone
(/stanok-work emptyDir, and HOME/TMPDIR only when the runner has redirected
them there) must still accept them.
"""
import os

import pytest

from src.ro_root_smoke import mul, write_probe

# CC-232 (operator-approved host-side guard): the root-FS invariants below are
# Pod-only — the read-only root and the /stanok-work emptyDir exist only in
# the runner Pods (both Job templates set STANOK_IN_POD=1). On the host they
# are false failures; the fresh Job runs this suite INSIDE the Pod, where the
# guards are satisfied and the assertions execute unchanged.
_pod_only = pytest.mark.skipif(
    not os.environ.get("STANOK_IN_POD"),
    reason="Pod-only invariant: runs in the worker/fresh Pod (STANOK_IN_POD=1)")


def test_positive_numbers():
    assert mul(2, 3) == 6
    assert mul(100, 200) == 20000
    assert mul(7, -6) == -42
    assert mul(-7, -6) == 42


def test_zero_identity():
    assert mul(0, 0) == 0
    assert mul(0, 42) == 0
    assert mul(42, 0) == 0
    assert mul(0, -13) == 0
    assert mul(-13, 0) == 0


def test_commutativity():
    for a, b in [(1, 2), (-5, 9), (0, 7), (-3, -8), (123456789, -987654321)]:
        assert mul(a, b) == mul(b, a)


@_pod_only
def test_root_is_read_only():
    # The hardening IS in effect only if creating a file at the filesystem
    # root fails. If write_probe("/") succeeds, the root is writable and the
    # acceptance fails.
    assert write_probe("/") is False


@_pod_only
def test_work_dir_writable():
    # /stanok-work (emptyDir) is the designated writable zone in both Pods;
    # the read-only root must not break it.
    assert write_probe("/stanok-work") is True


@_pod_only
def test_runner_redirect_env_writable():
    # The runner redirects HOME/TMPDIR into /stanok-work. Probe those values
    # ONLY when they start with /stanok-work; when the variable is absent or
    # points elsewhere (e.g. the image default in the fresh Pod, which is
    # legitimately read-only), skip the probe — do not assert on it.
    for var in ("TMPDIR", "HOME"):
        value = os.environ.get(var)
        if value is None or not value.startswith("/stanok-work"):
            continue
        assert write_probe(value) is True
