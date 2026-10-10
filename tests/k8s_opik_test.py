"""Acceptance tests for src/k8s_opik.py (TASK-STANOK-CC-225).

Proves, from INSIDE the Pod, that the Opik backend address delivered through
the environment (STANOK_OPIK_TRACE_URL) is actually reachable — this is what
makes the run's traces register in Opik. Stdlib only: no hostname resolution,
no third-party packages.
"""

import os
import socket

import pytest

from src.k8s_opik import add, trace_endpoint_parts


def test_add():
    assert add(2, 3) == 5


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
