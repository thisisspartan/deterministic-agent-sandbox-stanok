"""k8s_net — NetworkPolicy isolation probe (TASK-STANOK-CC-224).

Contract: the Pod must NOT be able to reach the LAN/Internet. Each probe
asserts only the NEGATIVE side of the policy, so it is green both in the
worker Pod (egress: model + kube-dns + Opik only) and in the fresh-check
Pod (deny-all network). The model endpoint itself is deliberately NOT
probed — it is reachable in the worker Pod and unreachable in the fresh
Pod by design.

Probe rules: raw IPs only (no hostname resolution), stdlib `socket` only,
timeout <= 3 s. Any OSError (timeout, refused, no route, host unreachable)
counts as unreachable = pass; a successful connect is a policy leak = fail.
"""

import os
import socket

import pytest

TIMEOUT_SECONDS = 3.0

# CC-232 (operator-approved host-side guard): these probes assert the
# NetworkPolicy boundary that exists only in the runner Pods (deny-all fresh
# Pod / egress-restricted worker Pod — both set STANOK_IN_POD=1). On the
# host the egress is open, so the probes are false reds; the fresh Job runs
# them INSIDE the Pod, where the policy is in effect.
_pod_only = pytest.mark.skipif(
    not os.environ.get("STANOK_IN_POD"),
    reason="Pod-only invariant: runs in the worker/fresh Pod (STANOK_IN_POD=1)")


def _assert_unreachable(host: str, port: int) -> None:
    """Fail if a TCP connect to host:port succeeds; pass on any OSError."""
    try:
        sock = socket.create_connection((host, port), timeout=TIMEOUT_SECONDS)
    except OSError:
        return
    sock.close()
    raise AssertionError(
        f"egress leak: TCP connect to {host}:{port} succeeded, "
        "but the NetworkPolicy must deny it"
    )


@_pod_only
def test_model_host_ssh_port_denied():
    """The model host is allowed on the model port only — port 22 must be denied."""
    _assert_unreachable("192.168.8.131", 22)


@_pod_only
def test_internet_denied():
    """1.1.1.1:80 is a live listener: a successful connect means egress is open."""
    _assert_unreachable("1.1.1.1", 80)


@_pod_only
def test_external_dns_denied():
    """Cluster kube-dns is allowed; external DNS over TCP is not."""
    _assert_unreachable("8.8.8.8", 53)
