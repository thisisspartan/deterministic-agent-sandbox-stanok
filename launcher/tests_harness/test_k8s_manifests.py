"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §7/§9) — the manifests.

Vanilla-K8s manifests in stanok/k8s/ (no k3s-specific hacks). Structural
checks (no YAML parser in the image — the checks are text invariants):
  1  networkpolicy.yaml.tmpl (2.4 + Package 1, operator spec 2026-10-10):
     carries NO addresses — only the {{MODEL_IP}}/{{OPIK_HOST_IP}}/
     {{OPIK_BACKEND_IP}} placeholders (a dotted IPv4 literal in the
     template is a defect); rendered via launcher.netpol it gives worker
     egress ONLY to the model host:8080 and the Opik endpoints:8080 —
     NO kube-dns rule (full DNS egress blackout: the endpoints are IP
     literals in the Job env); the fresh Pod is default-deny in BOTH
     directions (policyTypes Ingress + Egress, no allow rules); names are
     versioned {{REVISION}} (deterministic, non-self-referential — pinned
     by test_revision_deterministic_and_non_self_referential below);
     model_ip() fails closed on a non-IPv4 STANOK_SERVER_URL host
  2  worker-job.yaml.tmpl: non-root hardening (runAsNonRoot,
     allowPrivilegeEscalation false, capabilities drop ALL, seccomp
     RuntimeDefault), activeDeadlineSeconds, the nonce/label placeholders,
     NO privileged; disk bound (Package 1): emptyDir sizeLimit 2Gi +
     ephemeral-storage requests/limits NOT equal to the volume size
     (the limit counts writable layer + emptyDir + logs together)
  3  fresh-job.yaml.tmpl: verifier only (run.sh list + test --all), the
     patch applied, NO model address (deny-all Pod), the same disk bound
  4  CC-229 (SPEC-READONLY-ROOT-2026-10-10): readOnlyRootFilesystem: true
     in BOTH job templates (all Pod writes already target the /stanok-work
     emptyDir — HOME/TMPDIR re-redirected by pod_runner.py)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_manifests.py -q
"""
import re
from pathlib import Path

import pytest

from launcher import k8s, netpol

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


def _docs(text):
    """Policy documents with comment lines stripped — the structural
    assertions run on the spec text only (the header comments describe the
    policies and would otherwise leak words like 'Ingress' into a doc)."""
    docs = []
    for d in text.split("\n---\n"):
        if "kind: NetworkPolicy" in d:
            docs.append("\n".join(
                line for line in d.splitlines()
                if not line.lstrip().startswith("#")))
    return docs


def _worker_doc(text):
    return next(d for d in _docs(text) if "stanok: worker" in d)


def _fresh_doc(text):
    return next(d for d in _docs(text) if "stanok: fresh" in d)


def test_networkpolicy_worker_egress(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y = netpol.render_netpol()
    assert "kind: NetworkPolicy" in y
    assert "192.168.8.131/32" in y
    assert "8080" in y
    # Package 1: full DNS egress blackout — NO kube-dns rule, no port 53
    # anywhere in the worker policy (the endpoints are IP literals).
    w = _worker_doc(y)
    assert "port: 53" not in w
    assert "kube-dns" not in w
    assert "kube-system" not in w
    # Egress-only: the worker policy carries no Ingress type.
    assert "Ingress" not in w
    # no placeholder survived the render
    assert "{{" not in y


def test_networkpolicy_fresh_deny_both_directions():
    y = _read("networkpolicy.yaml.tmpl")
    f = _fresh_doc(y)
    # Package 1: default-deny in BOTH directions — Ingress AND Egress in
    # policyTypes, and NO allow rules (no ingress:/egress: rule keys).
    assert "Ingress" in f
    assert "Egress" in f
    assert "ingress:" not in f
    assert "egress:" not in f


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


# --- Package 1 (operator spec 2026-10-10): versioned names + disk bound ---

def test_networkpolicy_template_carries_revision_placeholder():
    y = _read("networkpolicy.yaml.tmpl")
    assert "{{REVISION}}" in y
    # both policies are versioned
    assert "stanok-worker-egress-{{REVISION}}" in y
    assert "stanok-fresh-deny-all-{{REVISION}}" in y


# --- CC-229 (SPEC-READONLY-ROOT-2026-10-10): read-only root FS ----------

def test_worker_job_read_only_root():
    y = _read("worker-job.yaml.tmpl")
    assert "readOnlyRootFilesystem: true" in y


def test_fresh_job_read_only_root():
    y = _read("fresh-job.yaml.tmpl")
    assert "readOnlyRootFilesystem: true" in y


def test_rendered_names_are_versioned(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    y, rev = netpol.render_netpol_with_revision()
    assert re.search(r"name: stanok-worker-egress-[0-9a-f]{12}$", y, re.M)
    assert re.search(r"name: stanok-fresh-deny-all-[0-9a-f]{12}$", y, re.M)
    # one revision for the whole manifest — both names carry it
    assert y.count(f"-{rev}") == 2
    assert "{{" not in y


def test_revision_deterministic_and_non_self_referential(monkeypatch):
    monkeypatch.setenv("STANOK_SERVER_URL", "http://192.168.8.131:8080")
    _, r1 = netpol.render_netpol_with_revision()
    _, r2 = netpol.render_netpol_with_revision()
    assert r1 == r2  # same inputs -> same revision (make-before-break safe)

    # a semantic change (an egress port) -> a different revision
    orig = k8s._read_manifest
    k8s._read_manifest = lambda name: orig(name).replace("port: 8080",
                                                          "port: 9090")
    try:
        _, r3 = netpol.render_netpol_with_revision()
    finally:
        k8s._read_manifest = orig
    assert r3 != r1

    # a NAME-only change -> the SAME revision (the hash never contains the
    # name it is used in — non-self-referential)
    k8s._read_manifest = lambda name: orig(name).replace(
        "stanok-worker-egress-", "stanok-worker-egressX-")
    try:
        _, r4 = netpol.render_netpol_with_revision()
    finally:
        k8s._read_manifest = orig
    assert r4 == r1


def test_job_disk_bounds():
    # Package 1: emptyDir sizeLimit + ephemeral-storage requests/limits —
    # and the limit must NOT equal the volume size (double-accounting:
    # the kubelet counts writable layer + emptyDir + /var/log/pods).
    for name in ("worker-job.yaml.tmpl", "fresh-job.yaml.tmpl"):
        y = _read(name)
        assert "sizeLimit: 2Gi" in y
        assert 'ephemeral-storage: "1Gi"' in y
        assert 'ephemeral-storage: "4Gi"' in y
        assert 'ephemeral-storage: "2Gi"' not in y
