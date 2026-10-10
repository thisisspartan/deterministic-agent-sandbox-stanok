"""k8s_opik — in-Pod Opik tracing via ENV (TASK-STANOK-CC-225).

Contract:
- add(a, b) returns the sum of its two integer arguments.
- trace_endpoint_parts(url) parses (host, port) from an
  http://host:port/path URL with stdlib urllib.parse; port is an int.

The tracing config is ENV-only: the worker Pod receives the Opik backend
address through STANOK_OPIK_TRACE_URL. This module only parses that address;
reachability is proven by the test with stdlib socket.
"""

from urllib.parse import urlsplit


def add(a: int, b: int) -> int:
    """Return the sum of a and b."""
    return a + b


def trace_endpoint_parts(url: str) -> tuple[str, int]:
    """Parse (host, port) from an http://host:port/path tracing URL."""
    parts = urlsplit(url)
    return parts.hostname, parts.port
