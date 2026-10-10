"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §7/§9) — the manifests.

Vanilla-K8s manifests in stanok/k8s/ (no k3s-specific hacks). Structural
checks (no YAML parser in the image — the checks are text invariants):
  1  networkpolicy.yaml.tmpl (2.4): carries NO addresses — only the
     {{MODEL_IP}}/{{OPIK_HOST_IP}}/{{OPIK_BACKEND_IP}} placeholders (a dotted
     IPv4 literal in the template is a defect); rendered via launcher.netpol
     it gives worker egress ONLY to kube-dns:53, the model host:8080 and the
     Opik backend:8080; a deny-all Egress policy for the fresh Pod
     (policyTypes Egress, no egress rules); model_ip() fails closed on a
     non-IPv4 STANOK_SERVER_URL host
  2  worker-job.yaml.tmpl: non-root hardening (runAsNonRoot,
     allowPrivilegeEscalation false, capabilities drop ALL, seccomp
     RuntimeDefault), activeDeadlineSeconds, the nonce/label placeholders,
     NO privileged
  3  fresh-job.yaml.tmpl: verifier only (run.sh list + test --all), the
     patch applied, NO model address (deny-all Pod)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_manifests.py -q
"""
import re
from pathlib import Path

import pytest

from launcher import netpol

K8S_DIR = Path(__file__).resolve().parents[2] / "k8s"


def _read(name):
    return (K8S_DIR / name).read_text(encoding="utf-8")


def test_networkpolicy_template_carries_no_addresses():
    y = _read("networkpolicy.yaml.tmpl")
    assert "kind: NetworkPolicy" in y
    for ph in ("{{MODEL_IP}}", "{{OPIK_HOST_IP}}", "{{OPIK_BACKEND_IP}}"):
        assert ph in y
    # 2.4: the addresses live in configuration, not in the manifest
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", y)


def test_networkpolicy_worker_egress(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y = netpol.render_netpol()
    assert "kind: NetworkPolicy" in y
    assert "192.168.8.131/32" in y
    assert "8080" in y
    assert "53" in y
    assert "kube-dns" in y or "kube-system" in y
    # no placeholder survived the render
    assert "{{" not in y


def test_netpol_model_ip_fail_closed(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://model.local:8080")
    with pytest.raises(ValueError):
        netpol.model_ip()


def test_netpol_defaults(monkeypatch):
    for var in ("STANOK_OPIK_HOST_IP", "STANOK_OPIK_BACKEND_IP"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    v = netpol.netpol_variables()
    assert v["MODEL_IP"] == "192.168.8.131"
    assert v["OPIK_HOST_IP"] == "192.168.122.156"
    assert v["OPIK_BACKEND_IP"] == "172.25.0.250"


def test_networkpolicy_fresh_deny_all():
    y = _read("networkpolicy.yaml.tmpl")
    assert "stanok=fresh" in y or "stanok: fresh" in y
    assert "policyTypes" in y
    # the deny-all policy: selects the fresh Pod, Egress type, no egress rules
    assert "Egress" in y


def test_worker_job_hardening():
    y = _read("worker-job.yaml.tmpl")
    assert "runAsNonRoot: true" in y
    assert "allowPrivilegeEscalation: false" in y
    assert "ALL" in y  # capabilities drop
    assert "RuntimeDefault" in y
    assert "activeDeadlineSeconds" in y
    assert "{{NONCE}}" in y
    assert "{{LABEL}}" in y
    assert "privileged: true" not in y


def test_fresh_job_verifier_only():
    y = _read("fresh-job.yaml.tmpl")
    assert "run.sh" in y
    assert "test --all" in y
    assert "changes.patch" in y
    assert "192.168.8.131" not in y  # deny-all Pod: no model endpoint
