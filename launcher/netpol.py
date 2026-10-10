"""netpol — render the NetworkPolicy manifest from configuration (2.4).

k8s/networkpolicy.yaml.tmpl carries NO addresses: the egress targets are
{{MODEL_IP}}/{{OPIK_HOST_IP}}/{{OPIK_BACKEND_IP}} placeholders. The addresses
live in configuration — launcher/config.py defaults (DEFAULT_OPIK_HOST_IP,
DEFAULT_OPIK_BACKEND_IP), overridable at call time via STANOK_OPIK_HOST_IP /
STANOK_OPIK_BACKEND_IP; MODEL_IP is derived from STANOK_SERVER_URL, the same
value the worker Job receives (fail closed: the URL host must parse as an
IPv4 address — a hostname the netpol controller cannot match as an ipBlock
is a configuration error, never a silent render).

Versioned names (Package 1, operator spec 2026-10-10): the template carries
{{REVISION}} — a deterministic hash of the rendered SEMANTIC content. The
canonical text excludes comment lines and metadata.name lines, so the hash is
never self-referential: the name is derived from the revision, the revision
never contains the name. Same inputs -> same revision; any semantic change
(addresses, rules, policyTypes) -> a different revision -> a NEW object name
(the k3s netpol controller ignores NetworkPolicy UPDATES; make-before-break
cutover needs new names).

Consumers: infra/netpol-smoke.sh (`python3 -m launcher.netpol` prints the
rendered manifest; the smoke applies exactly what it renders) and the
launcher, for a future apply-at-startup.

Run: <venv>/bin/python -m launcher.netpol
"""

import hashlib
import ipaddress
import os
import re
import sys
from urllib.parse import urlparse

from launcher import config, k8s

TEMPLATE = "networkpolicy.yaml.tmpl"
# The Config.from_env default — the same fallback the worker gets.
DEFAULT_SERVER_URL = "http://127.0.0.1:8080"


def model_ip() -> str:
    """The model host from STANOK_SERVER_URL — fail closed on a non-IPv4 host."""
    host = urlparse(os.environ.get("STANOK_SERVER_URL", DEFAULT_SERVER_URL)).hostname
    try:
        return str(ipaddress.IPv4Address(host))
    except ValueError:
        raise ValueError(
            f"MODEL_IP: STANOK_SERVER_URL host {host!r} is not an IPv4 "
            "address — a NetworkPolicy ipBlock needs a literal address")


def netpol_variables() -> dict:
    return {
        "MODEL_IP": model_ip(),
        "OPIK_HOST_IP": os.environ.get("STANOK_OPIK_HOST_IP",
                                       config.DEFAULT_OPIK_HOST_IP),
        "OPIK_BACKEND_IP": os.environ.get("STANOK_OPIK_BACKEND_IP",
                                          config.DEFAULT_OPIK_BACKEND_IP),
    }


_NAME_LINE_RE = re.compile(r"^\s*name:\s")


def canonical(text: str) -> str:
    """Semantic content only: comment lines and metadata.name lines are
    excluded — the revision is never self-referential (the name is derived
    from it, so hashing the name would make it depend on itself)."""
    return "\n".join(
        line for line in text.splitlines()
        if not line.lstrip().startswith("#") and not _NAME_LINE_RE.match(line)
    )


def revision(text: str) -> str:
    """Deterministic content hash of the canonical rendered manifest."""
    return hashlib.sha256(canonical(text).encode("utf-8")).hexdigest()[:12]


def render_netpol_with_revision() -> tuple:
    """Two-pass render: addresses first, then the revision of the canonical
    semantic content, then the name substitution. Returns (manifest, revision)."""
    rendered = k8s.render_template(k8s._read_manifest(TEMPLATE), netpol_variables())
    rev = revision(rendered)
    return rendered.replace("{{REVISION}}", rev), rev


def render_netpol() -> str:
    return render_netpol_with_revision()[0]


if __name__ == "__main__":
    sys.stdout.write(render_netpol())
