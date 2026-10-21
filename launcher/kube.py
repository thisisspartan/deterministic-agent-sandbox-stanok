"""kube — kubectl plumbing, extracted from launcher/k8s (wave A portion 2, 2026-10-21).

The agreed T3 sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md) splits k8s.py in
portions. This portion moves the cluster-facing layer: manifest rendering
(render_template, _read_manifest, K8S_DIR) and the kubectl call plumbing
(_kubectl, _kubectl_checked, _create_manifest, _kubectl_bin, _namespace,
_k8s_name, _cluster_env). Function bodies are moved verbatim — docstrings,
the R5 render guard and the CC-232 kubeconfig fallback travel with their
functions, behavior unchanged.

Strict from birth (wave A step 1 / launcher.abort precedent, extended): unlike
a plain verbatim move, every function here is annotated and the module joins
the mypy strict section, because launcher.netpol — already a strict module —
is a direct consumer of render_template/_namespace/_read_manifest, and strict
callers require annotated callees (the precedent recorded in mypy.ini for the
cli.py:774 boundary). The extracted functions carry zero strict debt, so the
move shrinks the recorded k8s debt instead of relocating it.

Single patch home: the remaining k8s code calls these as kube._X, so a test
stub on kube._X intercepts every call site; the tests_harness patch sites were
re-bound from k8s to kube together with the move (the agreed sequence's
"name -> new module" map). Guard: tests_harness/test_kube_facade.py — a moved
name lives ONLY in kube (no def and no setattr/assignment on k8s, and every
consumer's kube reference IS this module). Acceptance: byte-identical
behavioral reference against evidence/waveA-ref-b (the wave A reference
recipe, label-normalized).
"""

import os
import re
import subprocess
from collections.abc import Mapping

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
K8S_DIR = os.path.join(LAUNCHER_DIR, "..", "k8s")


# ==================================================================================
# manifest rendering
# ==================================================================================
def render_template(text: str, variables: Mapping[str, object]) -> str:
    for key, value in variables.items():
        v = str(value)
        # R5 (Z.ai external review 2026-10-20, operator order 2026-10-21):
        # str.replace rendering has no escaping. A value carrying "{{"
        # chains a second substitution pass (manifest markup injected
        # through the value); a value carrying "\n" breaks YAML structure
        # at the placeholder site. Every real caller supplies single-line
        # brace-free values (sanitized names, IPs validated by
        # model_ip(), hex revisions, str() of ints); anything else raises
        # before the manifest reaches the cluster.
        # Pair test: tests_harness/test_k8s_manifests.py (R5 pair).
        if "{{" in v or "\n" in v:
            raise ValueError(
                f"render_template: value for {key!r} must not contain "
                "'{{' or a newline (manifest markup injection)")
        text = text.replace("{{" + key + "}}", v)
    return text


def _read_manifest(name: str) -> str:
    with open(os.path.join(K8S_DIR, name), encoding="utf-8") as f:
        return f.read()


# ==================================================================================
# kubectl plumbing (runtime knobs, not Config fields)
# ==================================================================================
def _kubectl_bin() -> str:
    return os.environ.get("STANOK_KUBECTL") or "kubectl"


def _namespace() -> str:
    return os.environ.get("STANOK_K8S_NAMESPACE", "default")


def _k8s_name(label: str) -> str:
    """Object names are sanitized (labels allow [A-Za-z0-9_.-], k8s names do
    not); the evidence/label paths keep the ORIGINAL label — only cluster
    object names are rewritten."""
    name = re.sub(r"-+", "-", re.sub(r"[^a-z0-9-]", "-", label.lower()))
    return name.strip("-")[:50]


def _cluster_env() -> dict[str, str]:
    """CC-232: kubectl config resolution on the operator host. With KUBECONFIG
    unset, kubectl's own fallback chain can land on the non-world-readable
    /etc/rancher/k3s/k3s.yaml (the 2026-10-10 doctor failure); when
    KUBECONFIG is unset and ~/.kube/config exists, set it explicitly — the
    same fallback the doctor k8s health tests use."""
    env = dict(os.environ)
    if not env.get("KUBECONFIG"):
        kc = os.path.expanduser("~/.kube/config")
        if os.path.isfile(kc):
            env["KUBECONFIG"] = kc
    return env


def _kubectl(*argv: str, timeout: int = 60,
             input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run([_kubectl_bin(), *argv], capture_output=True,
                          text=True, timeout=timeout, input=input_text,
                          env=_cluster_env())


def _kubectl_checked(*argv: str,
                     timeout: int = 60) -> subprocess.CompletedProcess[str]:
    r = _kubectl(*argv, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(f"kubectl {' '.join(argv[:2])} failed "
                           f"(rc={r.returncode}): {r.stderr.strip()}")
    return r


def _create_manifest(text: str) -> None:
    """`create`, not `apply` (operator P0 2026-10-11): create fails when the
    object already exists, so a success proves THIS run created it — the
    ownership proof the finally cleanup needs. An `apply` would silently
    modify a foreign object and the cleanup would delete it."""
    r = _kubectl("create", "-f", "-", input_text=text)
    if r.returncode != 0:
        raise RuntimeError(f"kubectl create failed (rc={r.returncode}): "
                           f"{r.stderr.strip()}")


# ==================================================================================
# runtime-class knob (CC-256) — moved with the wave A portion 3 split: the
# manifest line and the preflight check share it, so it lives in the
# cluster-facing module (both consumers reach it as kube._X).
# ==================================================================================
def _runtime_class_name() -> str:
    """CC-256 (operator 2026-10-12): the DEFAULT runtime class is "gvisor" —
    two clean wave-runs under gVisor (cc254, cc255: rc=0 PASS CLEAN-FIRST,
    worker+fresh Pods gvisor by API read-back, clean hooks, comparable time).
    STANOK_K8S_RUNTIME_CLASS=runc opts out to "" (no runtimeClassName field
    == RuntimeDefault, the pre-gVisor behavior); any other value is used as-is.
    An unknown class fails at preflight (preflight._preflight_runtime_class)."""
    rc = os.environ.get("STANOK_K8S_RUNTIME_CLASS", "").strip() or "gvisor"
    return "" if rc == "runc" else rc


def _runtime_class() -> str:
    """Rendered manifest line for the effective class: "" -> the
    {{RUNTIME_CLASS}} line renders empty == RuntimeDefault."""
    rc = _runtime_class_name()
    return f"runtimeClassName: {rc}" if rc else ""
