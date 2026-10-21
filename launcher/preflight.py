"""preflight — the unified launch preflight (the wave A portion 3 split).

The agreed T3 sequence (specs/ARCHIVE/CONTEXT-2026-10-21c.md) splits k8s.py in
portions. This portion moves the pre-flight gate verbatim: _preflight_cluster
(the CC-232 cluster-health + manifest-contract gate) and the unified launch
preflight (_preflight composition, the seven checks, the _disk_path helper and
the DISK_MAX_PERCENT / _NETPOL_PREFIXES constants). Docstrings and the
section comments travel with the functions; behavior is unchanged.

Strict from birth (wave A precedent, extended): the moved functions were
unannotated (strict-class debt inside k8s.py); at move time they are annotated
(cfg: Config in string form via TYPE_CHECKING — the gates.py house style —
and the str | None reason signatures), and the module joins the mypy strict
section. The moved code therefore carries zero strict debt: the recorded k8s
count shrinks instead of being relocated.

Single patch home: host_launch_k8s reaches the gate as preflight._preflight,
and _preflight's composition resolves the seven checks through this module's
globals — a test stub on a name here intercepts every call site. The
tests_harness patch sites were re-bound from k8s to preflight together with
the move (the agreed sequence's "name -> new module" map). Guard:
tests_harness/test_preflight_facade.py. Acceptance: byte-identical
behavioral reference against evidence/waveA-ref-c (the wave A reference
recipe, label-normalized).
"""

import os
import subprocess
import sys
import urllib.error
import urllib.request
from typing import TYPE_CHECKING

from launcher import gates, kube

if TYPE_CHECKING:
    from launcher.config import Config

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))


# ==================================================================================
# CC-232: pre-flight doctor gate (fail-closed BEFORE any resource creation)
# ==================================================================================
def _preflight_cluster(cfg: "Config") -> str | None:
    """CC-232 (operator spec 2026-10-11): before ANY cluster resource is
    created, prove the two things doctor.sh proves about the K8s runtime —
    (1) the cluster is reachable and every node is Ready; (2) the manifest
    contract tests pass (a drifted template must never reach the cluster).
    Returns None when launch-ready, else the abort reason. An infrastructure
    defect (rc=16), never a ticket defect — the 3 ticket retries are not
    burned on it."""
    r = subprocess.run([kube._kubectl_bin(), "get", "nodes", "--no-headers"],
                       capture_output=True, text=True, timeout=30,
                       env=kube._cluster_env())
    if r.returncode != 0:
        return ("cluster unreachable: kubectl get nodes failed "
                f"(rc={r.returncode}): {(r.stderr or r.stdout).strip()[:300]}")
    for line in r.stdout.splitlines():
        fields = line.split()
        # exact column match: "NotReady" CONTAINS "Ready" — a substring test
        # would be a false green.
        if len(fields) < 2 or fields[1] != "Ready":
            return f"node not Ready: {line.strip()[:120]}"
    t = subprocess.run(
        [sys.executable, "-m", "pytest",
         os.path.join(LAUNCHER_DIR, "tests_harness", "test_k8s_manifests.py"),
         "-q", "-p", "no:cacheprovider"],
        cwd=cfg.repo_root, capture_output=True, text=True, timeout=120)
    if t.returncode != 0:
        tail = " | ".join((t.stdout or t.stderr).strip().splitlines()[-4:])
        return (f"manifest contract tests failed (rc={t.returncode}) — the "
                f"k8s templates drifted from the contract: {tail}")
    return None


# ==================================================================================
# Unified launch preflight (operator spec 2026-10-12): every check that turns a
# mid-run infrastructure failure into a pre-launch ENV-FAIL with the fix named.
# _preflight runs the checks in order (cheap host-side first, cluster-side
# after) and returns the FIRST reason; host_launch_k8s aborts rc=16 on it.
# Two items of the operator list are NOT duplicated here — they are already
# enforced upstream in cli.cmd_run before this function is ever reached:
# clean tree (dirty_tree_gate, rc=22) and start commit capture
# (_capture_start_commit -> STANOK_START_COMMIT). A preflight check is added
# only for a failure class that has no upstream guard.
# ==================================================================================
DISK_MAX_PERCENT = 80  # the cc248 GC incident fired at 85% — the guard is lower


def _disk_path(cfg: "Config") -> str:
    """The filesystem the kubelet image GC evicts from: the k3s data dir when
    it exists on this host (single-node k3s == the operator host), else the
    repo filesystem."""
    for p in ("/var/lib/rancher/k3s", cfg.repo_root):
        if os.path.isdir(p):
            return p
    return "/"


def _preflight_disk(cfg: "Config") -> str | None:
    path = _disk_path(cfg)
    r = subprocess.run(["df", "--output=pcent", path], capture_output=True,
                       text=True, timeout=15)
    if r.returncode != 0:
        return (f"cannot measure disk usage (df rc={r.returncode} on {path}) — "
                "infrastructure defect")
    try:
        pct = int(r.stdout.strip().splitlines()[-1].strip().rstrip("%"))
    except (IndexError, ValueError):
        return f"cannot parse df output for {path} — infrastructure defect"
    if pct >= DISK_MAX_PERCENT:
        return (f"disk usage {pct}% >= {DISK_MAX_PERCENT}% on {path} — kubelet "
                "image GC will evict the image mid-run (the cc248 precedent); "
                "fix: free disk space or prune images (sudo k3s ctr images prune)")
    return None


def _preflight_image_label(cfg: "Config") -> str | None:
    """Image staleness: the built image must carry the stanok.digest LABEL
    equal to sha256 over gates.DIGEST_INPUTS re-computed from the CURRENT
    tree — an image older than the Dockerfile/run.sh/stacks/lock must not
    reach the cluster (the pull would run an old entrypoint). CC-106 moved
    the docker-build half to doctor (gates.preflight_image, doctor-only);
    the operator preflight spec (2026-10-12) put the k8s-launch check here,
    where a stale digest pull is silent."""
    try:
        want = gates._image_digest(cfg)
    except OSError as e:
        return f"cannot compute the image digest from the current tree: {e}"
    r = subprocess.run(["docker", "inspect", "--format",
                        '{{index .Config.Labels "stanok.digest"}}',
                        cfg.docker_image],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return (f"image {cfg.docker_image!r} not found locally — "
                "run setup.sh (build)")
    got = r.stdout.strip()
    if got != want:
        return (f"image {cfg.docker_image!r} is stale: label {got!r} != "
                f"sha256(current build inputs) {want!r} — fix: rebuild+push "
                "via ./setup.sh")
    return None


def _preflight_opik(cfg: "Config") -> str | None:
    """Tracing is ON by default (operator 2026-10-12) — so the trace endpoint
    must be reachable BEFORE the run, not silently dropped mid-run (OTLP drops
    spans when the endpoint is unreachable). An explicit empty
    STANOK_OPIK_TRACE_URL disables tracing and this check is skipped.
    Any HTTP answer (even 405) proves reachability; only a connection failure
    is a defect. Proxy-bypassed: the endpoint is node-local, the supervisor's
    http_proxy must not route (or fake) it."""
    url = (cfg.opik_trace_url or "").strip()
    if not url:
        return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        opener.open(urllib.request.Request(url, method="HEAD"), timeout=5)
    except urllib.error.HTTPError:
        return None  # answered — reachable
    except (urllib.error.URLError, OSError) as e:
        return (f"Opik unreachable at {url}: {e} — fix: start Opik (~/opik) "
                "or disable tracing with STANOK_OPIK_TRACE_URL=''")
    return None


def _preflight_runtime_class(cfg: "Config") -> str | None:
    """The effective runtime class (default gvisor, CC-256) must EXIST — the
    former behavior (unknown class fails at Pod creation, mid-run) burned the
    whole run for a name typo. The runc opt-out (effective class "") skips
    the check."""
    rc = kube._runtime_class_name()
    if not rc:
        return None
    r = kube._kubectl("get", "runtimeclass", rc, "--no-headers")
    if r.returncode != 0:
        return (f"runtimeclass {rc!r} not in the cluster — fix: create it or "
                "set STANOK_K8S_RUNTIME_CLASS=runc")
    return None


_NETPOL_PREFIXES = ("stanok-worker-egress-", "stanok-fresh-deny-all-")


def _preflight_netpol(cfg: "Config") -> str | None:
    """The network boundary (SPEC-STANOK-K8S-RUNTIME §7) must EXIST in the
    effective namespace before any run: without it the worker Pod runs with
    no egress restriction and the fresh Pod is not deny-all — the boundary
    silently absent. The Jobs render their namespace from STANOK_K8S_NAMESPACE
    (worker/fresh-job.yaml.tmpl) and the netpol template from the same knob;
    a policy applied to another namespace does not select these Pods, so the
    check is namespace-scoped (external review 2026-10-16).
    Coverage by NAME PREFIX, any revision: the make-before-break cutover
    (Package 1) means an older revision may legitimately be the applied one
    — presence of the boundary is the contract, never revision match."""
    ns = kube._namespace()
    r = kube._kubectl("get", "networkpolicy", "-n", ns, "-o",
                 "jsonpath={.items[*].metadata.name}")
    if r.returncode != 0:
        return (f"cannot list NetworkPolicies in namespace {ns} "
                f"(rc={r.returncode}) — infrastructure defect")
    names = r.stdout.split()
    missing = [p for p in _NETPOL_PREFIXES
               if not any(n.startswith(p) for n in names)]
    if missing:
        want = " or ".join(f"{p}<revision>" for p in missing)
        return (f"no NetworkPolicy {want} in namespace {ns} — the network "
                "boundary is absent; fix: run infra/netpol-smoke.sh")
    return None


def _preflight_dangling(cfg: "Config") -> str | None:
    """No dangling stanok Jobs/Pods: the run lock serializes runs, so any
    stanok-labeled ACTIVE resource at preflight time is a leftover of a
    crashed run (a finished Job awaiting its TTL is not dangling — it is
    already inert). A leftover Pod/Job collides with the new run's names or
    holds the node's resources — refuse with the cleanup named."""
    ns = kube._namespace()
    leftovers = []
    r = kube._kubectl("get", "jobs", "-n", ns, "-l", "stanok", "-o",
                 "jsonpath={range .items[*]}{.metadata.name} "
                 "{.status.active}{\"\\n\"}{end}")
    if r.returncode != 0:
        return (f"cannot list stanok Jobs in namespace {ns} "
                f"(rc={r.returncode}) — infrastructure defect")
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) > 0:
            leftovers.append(f"job/{parts[0]}")
    r = kube._kubectl("get", "pods", "-n", ns, "-l", "stanok", "-o",
                 "jsonpath={range .items[*]}{.metadata.name} "
                 "{.status.phase}{\"\\n\"}{end}")
    if r.returncode != 0:
        return (f"cannot list stanok Pods in namespace {ns} "
                f"(rc={r.returncode}) — infrastructure defect")
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] in ("Running", "Pending", "Unknown"):
            leftovers.append(f"pod/{parts[0]}")
    if leftovers:
        return (f"dangling stanok resources in namespace {ns}: "
                f"{', '.join(leftovers)} — leftovers of a crashed run; fix: "
                "launch.sh stop <label> or kubectl delete them")
    return None


def _preflight(cfg: "Config") -> str | None:
    """The unified gate (operator spec 2026-10-12): host-side checks first
    (disk, image staleness, Opik), then the cluster checks (health+manifest,
    RuntimeClass, NetworkPolicy boundary, dangling). Returns None when
    launch-ready, else the first reason — an infrastructure defect (rc=16),
    never a ticket defect."""
    for check in (_preflight_disk, _preflight_image_label, _preflight_opik,
                  _preflight_cluster, _preflight_runtime_class,
                  _preflight_netpol, _preflight_dangling):
        reason = check(cfg)
        if reason:
            return reason
    return None
