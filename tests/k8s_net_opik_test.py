"""Acceptance tests for src/k8s_net_opik.py (TASK-STANOK-CC-228).

Proves, from INSIDE the Pod, that the Opik backend address delivered through
the environment (STANOK_OPIK_TRACE_URL) is reachable WITHOUT any name
resolution — the closing gate under the Package 1 DNS blackout (no kube-dns
rule; egress only to literal-IP /32 endpoints on port 8080). Stdlib only:
no hostname resolution, no third-party packages.
"""

import os
import socket

import pytest

from src.k8s_net_opik import mul, trace_endpoint_parts


def test_positive_numbers():
    assert mul(2, 3) == 6
    assert mul(100, 200) == 20000
    assert mul(7, 1) == 7


def test_negative_times_positive_sign():
    assert mul(-2, 3) == -6
    assert mul(3, -2) == -6
    assert mul(-2, -3) == 6


def test_zero_identity():
    assert mul(0, 0) == 0
    assert mul(0, 42) == 0
    assert mul(42, 0) == 0
    assert mul(0, -13) == 0
    assert mul(-13, 0) == 0


def test_commutativity():
    for a, b in [(1, 2), (-5, 9), (0, 7), (-3, -8), (123456789, -987654321)]:
        assert mul(a, b) == mul(b, a)


def test_trace_endpoint_parts():
    assert trace_endpoint_parts("http://192.168.122.156:8080/v1/private/otel") == (
        "192.168.122.156",
        8080,
    )


def test_opik_backend_reachable():
    url = os.environ.get("STANOK_OPIK_TRACE_URL", "")
    if not url:
        pytest.skip("no Opik env in this Pod")
    host, port = trace_endpoint_parts(url)
    try:
        sock = socket.create_connection((host, port), timeout=5)
    except OSError as exc:
        pytest.fail(
            f"Opik backend {host}:{port} unreachable from the Pod: {exc}"
        )
    sock.close()
