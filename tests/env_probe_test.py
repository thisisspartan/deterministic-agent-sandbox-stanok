"""Acceptance tests for src/env_probe.py (TASK-STANOK-CC-230).

In-Pod proof of two host-side fixes: (1) nonce isolation — the payload's
STANOK_NONCE is consumed by the in-Pod runner (os.environ.pop) and must not
reach any child Bash; (2) HOME/TMPDIR alignment — both must be set, point
into the /stanok-work emptyDir, and be writable, while the container root
stays read-only (EROFS).
"""

import errno
import os

import pytest

from src.env_probe import bash_print, write_error

# CC-232 (operator-approved host-side guard): the root-FS and HOME/TMPDIR
# invariants below are Pod-only — the read-only root and the /stanok-work
# emptyDir exist only in the runner Pods (both Job templates set
# STANOK_IN_POD=1). On the host they are false failures; the fresh Job runs
# this suite INSIDE the Pod, where the guards are satisfied and the
# assertions execute unchanged.
_pod_only = pytest.mark.skipif(
    not os.environ.get("STANOK_IN_POD"),
    reason="Pod-only invariant: runs in the worker/fresh Pod (STANOK_IN_POD=1)")


def test_bash_print_sanity():
    assert bash_print("hello") == "hello"


def test_nonce_not_inherited():
    # ${VAR-unset} expands to "unset" only when VAR is absent from the
    # child's environment — the payload nonce must not be inherited.
    assert bash_print("${STANOK_NONCE-unset}") == "unset"


@_pod_only
def test_root_write_denied_erofs():
    # /stanok-ro-test does not exist and cannot be created outside the
    # emptyDir: the probe must fail with Read-only file system — not with
    # any other errno, and not with success.
    assert write_error("/stanok-ro-test") == errno.EROFS


@_pod_only
def test_home_tmpdir_aligned_writable():
    # The designated writable zone: HOME and TMPDIR must be set, must point
    # into /stanok-work, and must accept a probe file (write_error -> None).
    for var in ("HOME", "TMPDIR"):
        value = os.environ.get(var)
        assert value is not None, f"{var} is not set"
        assert value.startswith("/stanok-work"), f"{var}={value!r} is outside /stanok-work"
        assert write_error(value) is None, f"{var}={value!r} is not writable"
