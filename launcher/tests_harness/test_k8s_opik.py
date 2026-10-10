"""CC-225 (operator 2026-10-10) — in-Pod Opik tracing via ENV.

The live cc221..cc224 runs exported OTLP to `http://localhost:8080/...`
from settings.stanok.json — inside the Pod localhost is the Pod, the spans
were silently dropped, opik_traces stayed the literal "disabled". The fix
is ENV-only (no git-tree file changes):
  1  k8s.rewrite_tracing_endpoint: settings.env.BETA_TRACING_ENDPOINT is
     rewritten from the Job env value BEFORE the base commit; empty value
     -> settings returned unchanged (byte-for-byte)
  2  worker-job.yaml.tmpl carries STANOK_OPIK_TRACE_URL rendered from the
     host env (the Pod gets the reachable backend address, not localhost)
  3  networkpolicy.yaml.tmpl rendered via launcher.netpol (2.4): worker
     egress additionally to the Opik backend on the node host
     192.168.122.156:8080 and its post-DNAT container address
     172.25.0.250:8080 (CC-225); the fresh Pod stays deny-all
  4  k8s.stamp_opik_traces: the host replaces the in-Pod "disabled" with
     the host-measured trace count for THIS session (the Pod is not its own
     judge); opik.session_trace_count paginates + filters thread_id
     client-side (CC-159), newest-first early-stop at the run start

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_opik.py -q
"""
import json

from launcher import k8s, opik

SETTINGS = json.dumps({
    "env": {"BETA_TRACING_ENDPOINT": "http://localhost:8080/v1/private/otel",
            "OTEL_SERVICE_NAME": "stanok-machine"},
    "permissions": {"allow": ["Read"]},
    "sandbox": {"enabled": True},
})
OPIK_URL = "http://192.168.122.156:8080/v1/private/otel"


def test_rewrite_tracing_endpoint_sets_env_only():
    out = json.loads(k8s.rewrite_tracing_endpoint(SETTINGS, OPIK_URL))
    assert out["env"]["BETA_TRACING_ENDPOINT"] == OPIK_URL
    # everything else in env and the rest of the settings survive
    assert out["env"]["OTEL_SERVICE_NAME"] == "stanok-machine"
    assert out["permissions"] == {"allow": ["Read"]}
    assert out["sandbox"] == {"enabled": True}


def test_rewrite_tracing_endpoint_empty_is_noop():
    assert k8s.rewrite_tracing_endpoint(SETTINGS, "") == SETTINGS


def test_worker_manifest_carries_opik_env():
    from pathlib import Path
    y = (Path(__file__).resolve().parents[2] / "k8s" /
         "worker-job.yaml.tmpl").read_text(encoding="utf-8")
    assert "STANOK_OPIK_TRACE_URL" in y
    assert "{{OPIK_TRACE_URL}}" in y


def test_networkpolicy_opik_egress_worker_only(monkeypatch):
    from launcher import netpol
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y = netpol.render_netpol()
    docs = y.split("---")
    worker = docs[0]
    assert "192.168.122.156/32" in worker  # the Opik backend on the node host
    assert "172.25.0.250/32" in worker     # post-DNAT container address (CC-225)
    assert "192.168.8.131/32" in worker    # the model host stays allowed
    # the fresh policy (the remaining docs) stays deny-all: no ipBlocks
    assert "192.168.122.156" not in "".join(docs[1:])


def test_stamp_opik_traces_replaces_disabled():
    summary = {"opik_traces": "disabled"}
    out = k8s.stamp_opik_traces(summary, 3)
    assert out["opik_traces"] == 3
    # None (Opik unreachable) never masquerades as 0 — field untouched
    untouched = k8s.stamp_opik_traces({"opik_traces": "disabled"}, None)
    assert untouched["opik_traces"] == "disabled"


def test_session_trace_count_exists_and_filters():
    assert callable(opik.session_trace_count)
    assert opik._trace_matches({"metadata": {"thread_id": "abc"}}, "abc")
    assert not opik._trace_matches({"metadata": {"thread_id": "x"}}, "abc")
    assert not opik._trace_matches({}, "abc")
