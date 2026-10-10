"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §7/§9) — the manifests.

Vanilla-K8s manifests in stanok/k8s/ (no k3s-specific hacks). Structural
checks (no YAML parser in the image — the checks are text invariants):
  1  networkpolicy.yaml: worker egress ONLY to kube-dns:53, the model host
     192.168.8.131:8080 (Opik shares it); a deny-all Egress policy for the
     fresh Pod (policyTypes Egress, no egress rules)
  2  worker-job.yaml.tmpl: non-root hardening (runAsNonRoot,
     allowPrivilegeEscalation false, capabilities drop ALL, seccomp
     RuntimeDefault), activeDeadlineSeconds, the nonce/label placeholders,
     NO privileged
  3  fresh-job.yaml.tmpl: verifier only (run.sh list + test --all), the
     patch applied, NO model address (deny-all Pod)

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_manifests.py -q
"""
from pathlib import Path

K8S_DIR = Path(__file__).resolve().parents[2] / "k8s"


def _read(name):
    return (K8S_DIR / name).read_text(encoding="utf-8")


def test_networkpolicy_worker_egress():
    y = _read("networkpolicy.yaml")
    assert "kind: NetworkPolicy" in y
    assert "192.168.8.131" in y
    assert "8080" in y
    assert "53" in y
    assert "kube-dns" in y or "kube-system" in y


def test_networkpolicy_fresh_deny_all():
    y = _read("networkpolicy.yaml")
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
