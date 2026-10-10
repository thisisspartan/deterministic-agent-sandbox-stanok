"""k8s_net_opik — in-Pod Opik reachability under the DNS blackout (TASK-STANOK-CC-228).

Contract:
- mul(a, b) returns the product of its two integer arguments.
- trace_endpoint_parts(url) parses (host, port) from an
  http://host:port/path URL with stdlib urllib.parse; port is an int.

The tracing config is ENV-only: the worker Pod receives the Opik backend
address through STANOK_OPIK_TRACE_URL. Under the Package 1 NetworkPolicy
(full worker DNS egress blackout — no kube-dns rule, egress only to the
literal-IP /32 endpoints on port 8080) the backend must be reachable by IP
alone. This module only parses that address; reachability is proven by the
test with stdlib socket, with no name resolution.
"""

from urllib.parse import urlsplit


def mul(a: int, b: int) -> int:
    """Return the product of a and b."""
    return a * b


def trace_endpoint_parts(url: str) -> tuple[str, int]:
    """Parse (host, port) from an http://host:port/path tracing URL."""
    parts = urlsplit(url)
    return parts.hostname, parts.port
