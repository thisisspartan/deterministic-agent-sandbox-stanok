"""k8s — the host-side orchestrator of the K8s runtime (SPEC-STANOK-K8S-RUNTIME-2026-10-10).

The runtime switch (CC-231 production cutover, supersedes the P1 §3
default): launch.sh keeps its contract (`run <ticket>
<label> --follow`, status/wait/stop, the marker and summary.json semantics);
this module is the ONLY host branch (CC-258: the Docker path is removed;
an explicit STANOK_RUNTIME=docker is refused with ENV-FAIL «docker runtime
removed»). The
Pod works on a TRANSPORTED COPY of the tree (git archive HEAD | gzip |
base64 through a ConfigMap — the measured decision of 2026-10-10: the full
bundle is 1.3MB > the 800KB ConfigMap threshold, the tarball is ~240KB); the
live tree is never touched during the run. The Pod returns its evidence as
ONE base64 gzip-tar block between nonce markers on stdout; the host accepts
EXACTLY ONE nonce-matching block (zero/two/unclosed = aborted, status
`missing`, never a verdict).

The verdict stays host-issued with fixed priority
(CONTRACT-FAIL > FRESH-FAIL > the worker's claims, summary.
_publish_evidence reused unchanged). Because the live tree is untouched, the
host recomputes the protected-files manifest against a SCRATCH tree
(extracted tree + git apply changes.patch) with the SAME
verify._compare_manifests — the two paths cannot drift. The patch gate
(reject filemode 120000 / '..' paths) re-asserts the zone/symlink
invariants on the transport layer; a violation is a host-issued
CONTRACT-FAIL, never a silent apply. The patch lands on the live tree ONLY
on a final PASS (§6 ordering).

Image provenance (operator plan 2026-10-12): the host stamps `image_digest`
into the published summary.json — the image ID recorded in the worker Pod's
own containerStatuses (the runtime's record of the image the Job ACTUALLY
ran; a content-addressed image ID is identical across runtimes, so this is
the digest of the image the run used, not the host store's idea of it).
Fail-soft: no Pod / no record -> None (explicit, like commit_sha), never a
guess.

kubectl is the only cluster interface; missing kubectl = rc=16 ENV-FAIL
(infrastructure, call the human). Namespace/kubectl binary are runtime
knobs (STANOK_K8S_NAMESPACE / STANOK_KUBECTL), not Config fields.
CC-232: a pre-flight doctor gate (cluster health + manifest contract tests)
runs fail-closed before any resource is created — rc=16 on failure.
"""

import base64
import dataclasses
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import tempfile
import time
import urllib.error
import urllib.request
import uuid

from launcher import gates, opik, verify
from launcher.config import RunState
from launcher.exitcodes import ExitCode
from launcher.logs import log
from launcher.session import _install_signal_handlers
from launcher.summary import _publish_evidence, write_env_fail_summary
from launcher.ticket import (
    assert_create_paths_are_new, assert_edit_paths_are_not_protected,
    parse_ticket_header,
)

LAUNCHER_DIR = os.path.dirname(os.path.abspath(__file__))
K8S_DIR = os.path.join(LAUNCHER_DIR, "..", "k8s")

# The ConfigMap size guard (O4): measured 2026-10-10 — full git bundle
# 1,308,067B > the threshold; `git archive HEAD | gzip | base64` ~240KB.
# Fail-closed BEFORE any kubectl call.
TRANSPORT_MAX_B64 = 800_000


# ==================================================================================
# Pure helpers (testable without a cluster)
# ==================================================================================
def new_nonce() -> str:
    """Host-generated per-run nonce (uuid4): the payload block must carry
    exactly this nonce — a stale or foreign block is never accepted."""
    return uuid.uuid4().hex


def begin_marker(nonce: str) -> str:
    return f"__STANOK_EVIDENCE_BEGIN_{nonce}__"


def end_marker(nonce: str) -> str:
    return f"__STANOK_EVIDENCE_END_{nonce}__"


def pack_tree(repo_root: str) -> str:
    """The tree transport: `git archive HEAD | gzip | base64` — the tracked
    tree only (no .git: the Pod re-inits its own git for the patch)."""
    p = subprocess.run(["git", "archive", "HEAD"], cwd=repo_root,
                       capture_output=True, check=True)
    return base64.b64encode(gzip.compress(p.stdout, mtime=0)).decode("ascii")


def unpack_tree(blob: str, dest: str) -> None:
    raw = gzip.decompress(base64.b64decode(blob))
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        try:
            tf.extractall(dest, filter="data")
        except TypeError:  # pre-3.12 tarfile without the filter kwarg
            tf.extractall(dest)


def transport_ok(blob: str) -> bool:
    return len(blob) <= TRANSPORT_MAX_B64


def build_payload(files: dict) -> str:
    """One base64 gzip-tar block: {name: bytes} -> the Pod's stdout payload."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return base64.b64encode(buf.getvalue()).decode("ascii")


def extract_payload(text: str, nonce: str):
    """The exactly-one rule: one and only one nonce-matching block, else
    None (the run is treated as aborted, never a verdict)."""
    pattern = (re.escape(begin_marker(nonce)) + r"\s*(.*?)\s*"
               + re.escape(end_marker(nonce)))
    blocks = re.findall(pattern, text, re.DOTALL)
    if len(blocks) != 1:
        return None
    raw = gzip.decompress(base64.b64decode(blocks[0]))
    files = {}
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                files[m.name] = tf.extractfile(m).read()
    return files


_DIFF_PATH_RE = re.compile(r"^diff --git a/(\S+) b/(\S+)", re.M)
_OLDNEW_RE = re.compile(r"^(?:---|\+\+\+) (?:a/|b/)?(\S+)")
_RENAME_COPY_RE = re.compile(r"^(?:rename|copy) (?:from|to) (.+)")
_MODE_SYMLINK_RE = re.compile(r"^(old mode|new(?: file)? mode) 120000", re.M)
_MODE_GITLINK_RE = re.compile(
    r"^(old mode|new(?: file)? mode|deleted file mode) 160000", re.M)
_INDEX_GITLINK_RE = re.compile(r"^index \S+ 160000")
_SUBPROJECT_RE = re.compile(r"^Subproject commit ")


def _path_violations(path: str) -> list:
    """One path, every transport invariant (Package 1, operator spec
    2026-10-10): no absolute path, no '..' segment, no '.git' component
    (the .git directory is the machine's read-only boundary — a patch that
    touches it bypasses every src/tests/docs rule; .gitignore is a normal
    file, only the exact '.git' component is rejected). /dev/null is the
    git sentinel for add/delete, not a path."""
    if path == "/dev/null":
        return []
    violations = []
    if path.startswith("/"):
        violations.append(f"ABSOLUTE: {path}")
    segments = path.split("/")
    if ".." in segments:
        violations.append(f"TRAVERSAL: {path}")
    if ".git" in segments:
        violations.append(f"GITDIR: {path}")
    return violations


def patch_gate(patch_text: str) -> list:
    """The transport-layer re-assertion of the Docker-era invariants (the
    zone-symlink ban rc=13 / SEC-01), hardened per the Package 1 spec:
    EVERY path-bearing header is checked (diff --git, ---/+++, rename
    from/to, copy from/to — renames and copies included), every path is
    checked for absolute/'..'/'.git' forms; symlinks (120000) and gitlinks
    (160000 in any mode form, the `index .. 160000` line, 'Subproject
    commit' lines) are rejected.
    Rejected BEFORE apply — a host-issued CONTRACT-FAIL, never a silent
    apply."""
    violations = []
    current = None
    for line in patch_text.splitlines():
        m = _DIFF_PATH_RE.match(line)
        if m:
            for path in (m.group(1), m.group(2)):
                violations.extend(_path_violations(path))
            current = m.group(2)
            continue
        m = _OLDNEW_RE.match(line)
        if m:
            violations.extend(_path_violations(m.group(1)))
            continue
        m = _RENAME_COPY_RE.match(line)
        if m:
            violations.extend(_path_violations(m.group(1)))
            continue
        if _MODE_SYMLINK_RE.match(line) and current:
            violations.append(f"SYMLINK: {current}")
        elif (_MODE_GITLINK_RE.match(line) or _INDEX_GITLINK_RE.match(line)
                or _SUBPROJECT_RE.match(line)):
            violations.append(f"GITLINK: {current or '<no file header>'}")
    return violations


def patch_sha256(patch_bytes: bytes) -> str:
    """The patch identity (Package 1): SHA-256 of the EXACT patch bytes,
    computed once from the payload; every later use of the patch (scratch
    apply, fresh Job, live apply) is re-verified against this hash —
    fail closed on mismatch."""
    return hashlib.sha256(patch_bytes).hexdigest()


def strict_patch_text(patch_bytes: bytes) -> str:
    """Decode the patch bytes STRICTLY (encoding-gap micro-patch, operator
    review 2026-10-10): the gate, the scratch contract and the apply must
    see exactly the text whose bytes are hashed and applied —
    errors="replace" would substitute U+FFFD and the contract would be
    verified against a tree different from the one that lands. Raises
    UnicodeDecodeError; the caller fail-closes with a host-issued
    CONTRACT-FAIL before any scratch/fresh/apply operation."""
    return patch_bytes.decode("utf-8")


def patch_identity_ok(patch_file: str, expected: str) -> bool:
    """Re-verify the on-disk patch file against the recorded hash."""
    try:
        with open(patch_file, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest() == expected
    except OSError:
        return False


def apply_patch_scratch(tree_blob: str, patch_text: str) -> str:
    """The scratch tree the k8s-mode verdict is computed against: extracted
    transport tree + `git apply` of the Pod's patch (git apply works outside
    a repo — verified 2026-10-10). Returns the scratch dir."""
    scratch = tempfile.mkdtemp(prefix="stanok-scratch-")
    unpack_tree(tree_blob, scratch)
    if patch_text.strip():
        patch_file = os.path.join(scratch, ".changes.patch")
        with open(patch_file, "w", encoding="utf-8") as f:
            f.write(patch_text)
        r = subprocess.run(["git", "apply", ".changes.patch"], cwd=scratch,
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise RuntimeError(f"git apply failed (rc={r.returncode}): "
                               f"{r.stderr.strip()}")
    return scratch


def scratch_contract_violations(cfg, before: dict, scratch_dir: str,
                               declared) -> list:
    """The host contract recompute over the scratch tree — the SAME
    verify._tests_manifest + _compare_manifests as the pre-run snapshot
    (one implementation — no drift): the live tree is untouched in k8s
    mode, so the tree the verdict was computed against is
    `transported tree + patch`."""
    scratch_cfg = dataclasses.replace(cfg, repo_root=scratch_dir)
    return verify._compare_manifests(before, verify._tests_manifest(scratch_cfg),
                                     declared)


def rewrite_tracing_endpoint(settings_text: str, endpoint: str) -> str:
    """CC-225 (operator 2026-10-10): the in-Pod Opik config is ENV-only.
    The extracted settings carry BETA_TRACING_ENDPOINT=http://localhost:8080/
    ... — inside the Pod localhost is the Pod, so the OTLP export is silently
    dropped (live cc221..cc224: zero traces, opik_traces "disabled"). The
    host passes the reachable backend URL through the Job env
    (STANOK_OPIK_TRACE_URL); the Pod runner rewrites the settings value from
    that env BEFORE the base commit — settings.env is applied by claude
    natively (session.py:530 --settings), and the rewrite is part of the
    Pod's baseline, not a tree change. An empty endpoint returns the settings
    unchanged (byte-for-byte)."""
    if not endpoint:
        return settings_text
    data = json.loads(settings_text)
    data.setdefault("env", {})["BETA_TRACING_ENDPOINT"] = endpoint
    return json.dumps(data, ensure_ascii=False, indent=2)


def stamp_opik_traces(summary: dict, count) -> dict:
    """CC-225: the host is the only party that can reach the Opik backend,
    so the host — not the Pod — issues the opik_traces field. The in-Pod
    summary carries the literal "disabled" (STANOK_IN_CONTAINER=1); the host
    replaces it with the trace count measured for THIS session. None (Opik
    unreachable) never masquerades as 0 — the field stays as written."""
    if count is not None:
        summary["opik_traces"] = count
    return summary


def render_template(text: str, variables: dict) -> str:
    for key, value in variables.items():
        text = text.replace("{{" + key + "}}", str(value))
    return text


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


def _read_manifest(name: str) -> str:
    with open(os.path.join(K8S_DIR, name), encoding="utf-8") as f:
        return f.read()


def _cluster_env() -> dict:
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


def _kubectl(*argv, timeout: int = 60, input_text: str = None):
    return subprocess.run([_kubectl_bin(), *argv], capture_output=True,
                          text=True, timeout=timeout, input=input_text,
                          env=_cluster_env())


def _kubectl_checked(*argv, timeout: int = 60):
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


def _pod_of_job(job_name: str, ns: str, timeout_s: int = 120):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        r = _kubectl("get", "pods", "-n", ns, "-l", f"job-name={job_name}",
                     "-o", "jsonpath={.items[0].metadata.name}")
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
        time.sleep(2)
    return None


def _pod_image_id(pod, ns: str):
    """Image provenance (operator plan 2026-10-12): the image ID the runtime
    recorded for THIS run's Pod — `status.containerStatuses[0].imageID`, the
    kubelet/CRI's own record, not the host docker store's idea of the image.
    A content-addressed image ID is identical across runtimes, so this is the
    digest of the image the Job actually ran. Two runtime forms are valid:
    docker reports a bare "sha256:<hex>"; containerd/k3s (the DEFAULT runtime,
    live verify-registry run 2026-10-12) reports "<repo>@sha256:<hex>" — the
    registry-qualified form is the stronger proof (it names the registry the
    kubelet pulled from). Fail-soft: no pod, kubectl error, or a value whose
    tail is not a sha256 digest -> None (explicit, like commit_sha — never a
    guess)."""
    if not pod:
        return None
    r = _kubectl("get", "pod", pod, "-n", ns, "-o",
                 "jsonpath={.status.containerStatuses[0].imageID}")
    out = (r.stdout or "").strip()
    if r.returncode != 0 or not re.search(r"(?:^|@)sha256:[0-9a-f]+$", out):
        return None
    return out


def _stream_pod_logs(pod: str, ns: str, path: str, timeout_s: int) -> None:
    """kubectl logs -f blocks until the Pod's containers exit — the payload
    lands in the host-side log file, never in the supervisor's context."""
    with open(path, "wb") as lf:
        try:
            # CC-232: same config resolution as _kubectl — the log stream is
            # a kubectl call too (incident cc233: without it the stream died
            # on the non-readable /etc/rancher/k3s/k3s.yaml fallback).
            subprocess.run([_kubectl_bin(), "logs", "-f", pod, "-n", ns],
                           stdout=lf, stderr=subprocess.STDOUT,
                           timeout=timeout_s, env=_cluster_env())
        except subprocess.TimeoutExpired:
            log("K8S: kubectl logs -f hit the host timeout")
        except OSError as e:
            log(f"K8S: kubectl logs failed: {e}")


def _job_rc_and_tail(job_name: str, ns: str) -> tuple:
    """(exit_rc, tail) of a FAILED Job: the Pod's terminated exit code plus
    its log tail (the fresh-check failure text)."""
    exit_rc = 1
    p = _kubectl("get", "pods", "-n", ns, "-l", f"job-name={job_name}",
                 "-o", "jsonpath={.items[0].status.containerStatuses[0]."
                       "state.terminated.exitCode}")
    if p.returncode == 0 and p.stdout.strip().lstrip("-").isdigit():
        exit_rc = int(p.stdout.strip())
    pod = _pod_of_job(job_name, ns, timeout_s=30)
    tail = ""
    if pod:
        lg = _kubectl("logs", pod, "-n", ns)
        tail = (lg.stderr or "") + "\n" + (lg.stdout or "")
    return exit_rc, tail


def _pod_infra_cause(pod, ns: str):
    """BL-4 (a1/a2): classify a Pod death as an infrastructure cause.
    The gap _wait_job_terminal leaves: Job-level conditions say only
    'Failed', the Pod's own status says WHY. Two causes are infrastructure
    (rc=16, the 3 ticket retries are not burned on it):
      - containerStatuses[].state.terminated.reason == "OOMKilled" — the
        cgroup OOM kill. Measured 2026-10-16 (two gVisor probes at worker
        limits): kubelet reports it honestly under gVisor too — the Pod-slice
        limit is enforced, the overshoot is swap-absorbed until the swap is
        exhausted, then the sandbox is OOM-killed and the reason appears.
      - status.reason == "Evicted" — kubelet eviction.
    A bare exit 137 with NO reason is NOT OOM: the Job's
    activeDeadlineSeconds kill is also a SIGKILL (job_deadline). Anything
    else (a test failure) stays None — a ticket defect.
    Fail-soft: no pod / kubectl error / unparseable JSON -> None."""
    if not pod:
        return None
    r = _kubectl("get", "pod", pod, "-n", ns, "-o", "json")
    if r.returncode != 0:
        return None
    try:
        status = json.loads(r.stdout).get("status", {})
    except json.JSONDecodeError:
        return None
    for cs in status.get("containerStatuses") or []:
        term = (cs.get("state") or {}).get("terminated") or {}
        if term.get("reason") == "OOMKilled":
            return "OOMKilled"
    if status.get("reason") == "Evicted":
        return "Evicted"
    return None


def _job_infra_cause(name: str, ns: str):
    """Deadline contract (external review 2026-10-16): a Job killed by its
    own activeDeadlineSeconds reports Job condition Failed with
    reason="DeadlineExceeded". The Pod side shows only a bare SIGKILL
    (137, no reason), which _pod_infra_cause deliberately refuses to guess
    — the Job-level reason is the honest signal. Infrastructure defect:
    the session outlived the Job deadline, not a ticket defect.
    Fail-soft: no job / kubectl error / unparseable JSON -> None."""
    r = _kubectl("get", "job", name, "-n", ns, "-o", "json")
    if r.returncode != 0:
        return None
    try:
        conds = json.loads(r.stdout).get("status", {}).get("conditions", [])
    except json.JSONDecodeError:
        return None
    for c in conds:
        if (c.get("type") == "Failed" and c.get("status") == "True"
                and c.get("reason") == "DeadlineExceeded"):
            return "DeadlineExceeded"
    return None


def _wait_job_terminal(name: str, ns: str, timeout_s: int) -> str:
    """Poll the Job until a terminal condition: 'complete' | 'failed' | 'timeout'.
    `kubectl wait --for=condition=complete` blocks for the WHOLE timeout when the
    Job FAILED (live cc221, 2026-10-10: a failed fresh Job hung the host for an
    hour) — the host must learn about a failed Job immediately."""
    deadline = time.monotonic() + timeout_s
    while True:
        r = _kubectl("get", "job", name, "-n", ns, "-o", "json")
        if r.returncode == 0:
            try:
                conds = json.loads(r.stdout).get("status", {}).get("conditions", [])
            except json.JSONDecodeError:
                conds = []
            for c in conds:
                if c.get("status") == "True" and c.get("type") in ("Complete", "Failed"):
                    return c["type"].lower()
        if time.monotonic() >= deadline:
            return "timeout"
        time.sleep(5)


# Startup margin over the turn timeout: tree unpack, git init, settings
# rewrite, CLI start (external review 2026-10-16).
_DEADLINE_MARGIN_S = 300


def job_deadline(cfg) -> int:
    """CC-230 + the deadline contract (external review 2026-10-16): Job
    activeDeadlineSeconds must STRICTLY EXCEED the session's own turn
    timeout. The old default (1800) equalled STANOK_TURN_TIMEOUT_S (1800):
    the Job SIGKILLed the Pod at the exact moment the in-Pod turn timer
    would have produced a clean TURN-TIMEOUT verdict — the verdict channel
    lost to the insurance timer. Default: cfg.turn_timeout_s + startup
    margin; it stays below the supervisor's wait cap (test_timer_contract
    pins the ordering). STANOK_K8S_JOB_DEADLINE_S overrides explicitly —
    the operator's knob wins over the contract, no questions asked."""
    override = os.environ.get("STANOK_K8S_JOB_DEADLINE_S")
    if override:
        return int(override)
    return int(cfg.turn_timeout_s) + _DEADLINE_MARGIN_S


def _runtime_class_name() -> str:
    """CC-256 (operator 2026-10-12): the DEFAULT runtime class is "gvisor" —
    two clean wave-runs under gVisor (cc254, cc255: rc=0 PASS CLEAN-FIRST,
    worker+fresh Pods gvisor by API read-back, clean hooks, comparable time).
    STANOK_K8S_RUNTIME_CLASS=runc opts out to "" (no runtimeClassName field
    == RuntimeDefault, the pre-gVisor behavior); any other value is used as-is.
    An unknown class fails at preflight (_preflight_runtime_class)."""
    rc = os.environ.get("STANOK_K8S_RUNTIME_CLASS", "").strip() or "gvisor"
    return "" if rc == "runc" else rc


def _runtime_class() -> str:
    """Rendered manifest line for the effective class: "" -> the
    {{RUNTIME_CLASS}} line renders empty == RuntimeDefault."""
    rc = _runtime_class_name()
    return f"runtimeClassName: {rc}" if rc else ""


# ==================================================================================
# Resource sampling (operator decision 2026-10-16): the G1 requests/limits
# (bb5eed6) were committed as "pending measured peaks" — this closes the
# measurement half. Read-only polling of the kubelet stats API (`kubectl get
# --raw /api/v1/nodes/<node>/proxy/stats/summary` — the native kubelet
# primitive, no new mechanism) while a Job runs; observed peaks are
# host-stamped into summary.json as resource_peaks, like patch_sha256.
# gVisor caveat (BL-4 finding): under runsc the Pod's host cgroup IS the
# sandbox process (guest memory = host anonymous memory), so pod-level numbers
# are host-real; per-container accounting under runsc can drift. Peaks are
# published as OBSERVED kubelet numbers, never as truth claims; None when no
# sample succeeded (never a 0 masquerade).
# ==================================================================================
SAMPLE_INTERVAL_S = 10.0


def _node_of_pod(pod: str, ns: str):
    r = _kubectl("get", "pod", pod, "-n", ns, "-o", "jsonpath={.spec.nodeName}")
    node = (r.stdout or "").strip()
    return node or None


def _kubelet_stats(node: str) -> dict:
    r = _kubectl_checked("get", "--raw",
                        f"/api/v1/nodes/{node}/proxy/stats/summary")
    return json.loads(r.stdout)


def _peak_from_stats(stats: dict, pod: str, ns: str):
    """Pure extraction: the Pod's typed peak record from one kubelet summary,
    or None when the Pod is not in it."""
    for p in stats.get("pods", []):
        ref = p.get("podRef") or {}
        if ref.get("name") != pod or ref.get("namespace") != ns:
            continue
        mem = p.get("memory") or {}
        cpu = p.get("cpu") or {}
        return {
            "cpu_peak_nanocores": cpu.get("usageNanoCores"),
            "mem_peak_usage_bytes": mem.get("usageBytes"),
            "mem_peak_working_set_bytes": mem.get("workingSetBytes"),
        }
    return None


class _ResourceSampler(threading.Thread):
    """Samples kubelet stats for one Pod every interval until stopped, keeping
    the observed maxima. A fetch error is counted, never fatal — the sampler
    must never affect the run it observes."""

    def __init__(self, pod: str, ns: str, interval_s: float = SAMPLE_INTERVAL_S,
                 fetch=None):
        super().__init__(daemon=True)
        self.pod, self.ns, self.interval_s = pod, ns, interval_s
        self._fetch = fetch or self._default_fetch
        # NOT "_stop": CPython 3.11 Thread._wait_for_tstate_lock calls
        # self._stop() at join() — an Event attribute there shadows the
        # internal and join() raises TypeError (external review 2026-10-16,
        # reproduced on 3.11.15; the host venv is 3.13, so only a 3.11
        # launcher hits it — pinned by test_py311_join_contract).
        self._stop_event = threading.Event()
        self.samples = 0
        self.errors = 0
        self._peak = None

    def _default_fetch(self):
        node = _node_of_pod(self.pod, self.ns)
        if node is None:
            raise RuntimeError(f"pod {self.pod}: nodeName unavailable")
        return _kubelet_stats(node)

    def run(self):
        while not self._stop_event.is_set():
            try:
                peak = _peak_from_stats(self._fetch(), self.pod, self.ns)
                if peak is not None:
                    self.samples += 1
                    self._merge(peak)
            except Exception:
                self.errors += 1
            self._stop_event.wait(self.interval_s)

    def _merge(self, peak: dict) -> None:
        if self._peak is None:
            self._peak = dict(peak)
            return
        for key in ("cpu_peak_nanocores", "mem_peak_usage_bytes",
                    "mem_peak_working_set_bytes"):
            cur, new = self._peak.get(key), peak.get(key)
            if new is not None:
                self._peak[key] = new if cur is None else max(cur, new)

    def stop_and_peaks(self):
        """Stop sampling, return the typed record (peaks + samples/errors), or
        None when nothing was ever observed (never a 0 masquerade)."""
        self._stop_event.set()
        self.join(timeout=2 * self.interval_s + 5)
        if self.samples == 0:
            return None
        out = dict(self._peak)
        out["samples"] = self.samples
        out["errors"] = self.errors
        return out


# ==================================================================================
# The fresh check as a deny-all Job (the same `run.sh list; run.sh test
# --all` pair as the worker, no model endpoint — the Docker-era
# fresh_verify_argv mirror is gone with the Docker path, CC-258)
# ==================================================================================
def _fresh_job(cfg, ns: str, fresh_name: str, cm_tree: str, cm_patch: str,
               patch_file: str, deadline: int, created: list,
               image_ref: str, peaks_out: dict = None) -> tuple:
    try:
        # BL-4 (b): the patch transport guard — symmetry with the tree guard
        # (host_launch_k8s, TRANSPORT_MAX_B64): fail closed BEFORE the
        # kubectl call. The classification is unchanged (EXEC_ERROR -> the
        # caller's rc=16); the guard only moves the failure before any
        # cluster call.
        patch_size = os.path.getsize(patch_file)
        if patch_size > TRANSPORT_MAX_B64:
            return (1, f"EXEC_ERROR: patch transport {patch_size}B exceeds "
                       f"the ConfigMap limit {TRANSPORT_MAX_B64}B — "
                       "fail-closed before any kubectl call")
        _kubectl_checked("create", "configmap", cm_patch, "-n", ns,
                        f"--from-file=changes.patch={patch_file}")
        created.append(("configmap", cm_patch))
        _create_manifest(render_template(_read_manifest("fresh-job.yaml.tmpl"), {
            "JOB_NAME": fresh_name.removeprefix("stanok-fresh-"),
            "IMAGE": image_ref, "NAMESPACE": ns,
            "CM_TREE": cm_tree, "CM_PATCH": cm_patch, "DEADLINE": str(deadline),
            "RUNTIME_CLASS": _runtime_class(),
        }))
        created.append(("job", fresh_name))
    except RuntimeError as e:
        return (1, f"EXEC_ERROR: {e}")
    # Resource measurement (operator decision 2026-10-16): the same read-only
    # kubelet sampling as the worker Job; peaks go into the caller's holder
    # (host-stamped like patch_sha256). Only done when a holder is provided —
    # without one the flow is byte-for-byte the pre-measurement one.
    sampler = None
    fresh_pod = None
    if peaks_out is not None:
        fresh_pod = _pod_of_job(fresh_name, ns, timeout_s=30)
        if fresh_pod is not None:
            sampler = _ResourceSampler(fresh_pod, ns)
            sampler.start()
    completed = _wait_job_terminal(fresh_name, ns, deadline + 60) == "complete"
    if sampler is not None:
        peaks_out["peaks"] = sampler.stop_and_peaks()
    if completed:
        return (0, "")
    # BL-4 (a2): a fresh Pod killed by an infrastructure cause (cgroup OOM /
    # eviction) is EXEC_ERROR — the caller maps it to rc=16 ENV-FAIL, not a
    # FRESH-FAIL that burns the ticket's 3 retries on an infrastructure defect.
    if fresh_pod is None:
        fresh_pod = _pod_of_job(fresh_name, ns, timeout_s=30)
    cause = _pod_infra_cause(fresh_pod, ns)
    if cause:
        return (1, f"EXEC_ERROR: fresh Pod {cause} — infrastructure defect")
    exit_rc, tail = _job_rc_and_tail(fresh_name, ns)
    if not tail.strip():
        tail = f"the fresh Job did not complete (exit {exit_rc})"
    return (exit_rc, verify._tail_output(cfg, tail))


# ==================================================================================
# CC-232: pre-flight doctor gate (fail-closed BEFORE any resource creation)
# ==================================================================================
def _preflight_cluster(cfg):
    """CC-232 (operator spec 2026-10-11): before ANY cluster resource is
    created, prove the two things doctor.sh proves about the K8s runtime —
    (1) the cluster is reachable and every node is Ready; (2) the manifest
    contract tests pass (a drifted template must never reach the cluster).
    Returns None when launch-ready, else the abort reason. An infrastructure
    defect (rc=16), never a ticket defect — the 3 ticket retries are not
    burned on it."""
    r = subprocess.run([_kubectl_bin(), "get", "nodes", "--no-headers"],
                       capture_output=True, text=True, timeout=30,
                       env=_cluster_env())
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


def _disk_path(cfg) -> str:
    """The filesystem the kubelet image GC evicts from: the k3s data dir when
    it exists on this host (single-node k3s == the operator host), else the
    repo filesystem."""
    for p in ("/var/lib/rancher/k3s", cfg.repo_root):
        if os.path.isdir(p):
            return p
    return "/"


def _preflight_disk(cfg):
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


def _preflight_image_label(cfg):
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


def _preflight_opik(cfg):
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


def _preflight_runtime_class(cfg):
    """The effective runtime class (default gvisor, CC-256) must EXIST — the
    former behavior (unknown class fails at Pod creation, mid-run) burned the
    whole run for a name typo. The runc opt-out (effective class "") skips
    the check."""
    rc = _runtime_class_name()
    if not rc:
        return None
    r = _kubectl("get", "runtimeclass", rc, "--no-headers")
    if r.returncode != 0:
        return (f"runtimeclass {rc!r} not in the cluster — fix: create it or "
                "set STANOK_K8S_RUNTIME_CLASS=runc")
    return None


_NETPOL_PREFIXES = ("stanok-worker-egress-", "stanok-fresh-deny-all-")


def _preflight_netpol(cfg):
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
    ns = _namespace()
    r = _kubectl("get", "networkpolicy", "-n", ns, "-o",
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


def _preflight_dangling(cfg):
    """No dangling stanok Jobs/Pods: the run lock serializes runs, so any
    stanok-labeled ACTIVE resource at preflight time is a leftover of a
    crashed run (a finished Job awaiting its TTL is not dangling — it is
    already inert). A leftover Pod/Job collides with the new run's names or
    holds the node's resources — refuse with the cleanup named."""
    ns = _namespace()
    leftovers = []
    r = _kubectl("get", "jobs", "-n", ns, "-l", "stanok", "-o",
                 "jsonpath={range .items[*]}{.metadata.name} "
                 "{.status.active}{\"\\n\"}{end}")
    if r.returncode != 0:
        return (f"cannot list stanok Jobs in namespace {ns} "
                f"(rc={r.returncode}) — infrastructure defect")
    for line in r.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1].isdigit() and int(parts[1]) > 0:
            leftovers.append(f"job/{parts[0]}")
    r = _kubectl("get", "pods", "-n", ns, "-l", "stanok", "-o",
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


def _preflight(cfg):
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


# ==================================================================================
# Image delivery (operator 2026-10-12): the Job image reference, by DIGEST.
# The incident: cc248 ImagePullBackOff — kubelet GC evicted the tag-pinned
# image and the manual `k3s ctr import` transport was invisible to the launch.
# A digest reference makes the pull self-sufficient: containerd fetches the
# exact manifest from the node-local registry after any GC. Fail-closed here
# (before any cluster resource): an image not pushed to the registry is an
# infrastructure defect (rc=16) with the fix named — never a silent pull wait.
# ==================================================================================
def _image_ref(cfg):
    """Resolve the pushed RepoDigest for cfg.docker_image at cfg.registry.
    Returns (ref, None) on success, (None, reason) when the image is absent
    locally or not pushed — the reason text names the fix (setup.sh)."""
    r = subprocess.run(["docker", "inspect", "--format={{json .RepoDigests}}",
                        cfg.docker_image],
                       capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None, (f"image {cfg.docker_image!r} not found locally — "
                      "run setup.sh (build)")
    try:
        # `docker inspect --format={{json .RepoDigests}}` prints `null` for an
        # image that exists but was never pushed — `or []` normalizes it.
        digests = json.loads(r.stdout) or []
    except json.JSONDecodeError:
        digests = []
    ref = next((d for d in digests if isinstance(d, str)
                and d.startswith(cfg.registry + "/")), None)
    if ref is None:
        return None, (f"image {cfg.docker_image!r} is not pushed to the registry "
                      f"{cfg.registry!r} — run setup.sh (build+push); one-time "
                      "root step: k8s/setup-registry.sh")
    return ref, None


# ==================================================================================
# host_launch_k8s — the ONLY host branch (CC-231; CC-258 removed the
# Docker path)
# ==================================================================================
def host_launch_k8s(cfg, args, marker: str) -> int:
    """The host supervision: transport -> worker Job -> payload -> patch gate
    + patch identity (SHA-256, re-verified before every apply) -> scratch
    contract -> fresh Job -> _publish_evidence -> rc alignment. The
    marker/summary protocol is unchanged: the supervisor reads
    evidence/<label>/summary.json exactly as before.

    The cluster calls are wrapped: a kubectl failure is an infrastructure
    defect (rc=16, write_env_fail_summary), NOT a ticket defect — the 3
    ticket retries must not be burned on it."""
    from launcher.cli import _early_abort  # lazy: cli imports this module

    label = args.label
    ns = _namespace()
    kname = _k8s_name(label)
    job_name = f"stanok-job-{kname}"
    fresh_name = f"stanok-fresh-{kname}"
    cm_ticket = f"stanok-ticket-{kname}"
    cm_tree = f"stanok-tree-{kname}"
    cm_runner = f"stanok-runner-{kname}"
    cm_patch = f"stanok-patch-{kname}"

    if shutil.which(_kubectl_bin()) is None:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: kubectl ({_kubectl_bin()}) not found — the "
                            "K8s runtime is unavailable (rc=16, infrastructure)")

    # The ticket gate (CC-133/CC-206) — before any cluster call: the machine
    # must not start for an unsatisfiable contract.
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            declared, edit_paths, _, accept_paths, accept_mode = \
                parse_ticket_header(cfg, f.read())
        assert_create_paths_are_new(cfg, declared, edit_paths)
        assert_edit_paths_are_not_protected(cfg, edit_paths)
    except (OSError, ValueError) as e:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.TICKET,
                            f"ERROR: ticket parse error: {e}")

    # Unified launch preflight (operator spec 2026-10-12; CC-232 subsumed):
    # disk, image staleness, Opik reachability, cluster health + manifest
    # contract, RuntimeClass, dangling stanok resources — BEFORE any
    # ConfigMap/Job is created. Infrastructure defect: rc=16, no marker, no
    # evidence dir. Clean tree + start commit are enforced upstream in
    # cli.cmd_run (rc=22 / STANOK_START_COMMIT) — not duplicated here.
    reason = _preflight(cfg)
    if reason:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: PREFLIGHT: {reason}")

    # Image delivery (operator 2026-10-12): the digest reference is resolved
    # BEFORE any cluster resource — an image not pushed to the registry aborts
    # with rc=16 and names the fix (setup.sh), never a silent ImagePullBackOff.
    image_ref, image_err = _image_ref(cfg)
    if image_err:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: PREFLIGHT: {image_err}")

    evidence_dir, live_dir = cfg.label_paths(label)
    os.makedirs(evidence_dir, exist_ok=True)
    os.makedirs(live_dir, exist_ok=True)
    run_state = RunState(evidence_dir=evidence_dir, live_dir=live_dir,
                         marker_path=marker)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())} {os.getpid()}\n")
    _install_signal_handlers(run_state)

    # A stale summary.json / failures.log from an earlier run of this label
    # must not be re-published as this run's verdict (CC-237).
    for stale_name in ("summary.json", "failures.log"):
        stale = os.path.join(live_dir, stale_name)
        if os.path.isfile(stale):
            try:
                os.replace(stale, stale + ".prev")
            except OSError:
                pass

    # T3-1: the pre-run contract snapshot of the LIVE tree — the scratch
    # recompute compares against this (the live tree is untouched during the
    # run; the tree the verdict was computed against is the scratch).
    before_manifest = verify.contract_snapshot(cfg)
    nonce = new_nonce()
    deadline = job_deadline(cfg)
    # CC-225: the run-start bound for the Opik trace scan (the API list is
    # newest-first; the scan stops at this timestamp).
    run_start_iso = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())

    try:
        tree_blob = pack_tree(cfg.repo_root)
    except (subprocess.CalledProcessError, OSError) as e:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: tree transport pack failed: {e}")
    if not transport_ok(tree_blob):
        return _early_abort(
            cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
            f"ERROR: tree transport {len(tree_blob)}B exceeds the ConfigMap "
            f"limit {TRANSPORT_MAX_B64}B — fail-closed before any kubectl call")
    tree_file = os.path.join(live_dir, "tree.tar.gz.b64")
    with open(tree_file, "w", encoding="ascii") as f:
        f.write(tree_blob)

    rc = int(ExitCode.CHILD_DIED)
    # P0 (operator 2026-10-11): the finally cleanup deletes ONLY resources
    # whose creation by THIS run is proven — a ConfigMap create that returned
    # success, a Job created via `create` (not `apply`: create fails if the
    # object already exists, so success == ownership). A foreign object is
    # never deleted.
    created = []
    try:
        try:
            _kubectl_checked("create", "configmap", cm_ticket, "-n", ns,
                             f"--from-file=ticket.md={args.ticket_path}")
            created.append(("configmap", cm_ticket))
            _kubectl_checked("create", "configmap", cm_tree, "-n", ns,
                             f"--from-file=tree.tar.gz.b64={tree_file}")
            created.append(("configmap", cm_tree))
            _kubectl_checked("create", "configmap", cm_runner, "-n", ns,
                             "--from-file=pod_runner.py=" +
                             os.path.join(LAUNCHER_DIR, "pod_runner.py"))
            created.append(("configmap", cm_runner))
            _create_manifest(render_template(
                _read_manifest("worker-job.yaml.tmpl"), {
                    "JOB_NAME": job_name, "LABEL": label, "NONCE": nonce,
                    "IMAGE": image_ref, "NAMESPACE": ns,
                    "SERVER_URL": cfg.server_url, "MODEL": cfg.model,
                    "OPIK_TRACE_URL": cfg.opik_trace_url,
                    "START_COMMIT": os.environ.get("STANOK_START_COMMIT", ""),
                    "DEADLINE": str(deadline),
                    "CM_TICKET": cm_ticket, "CM_TREE": cm_tree,
                    "CM_RUNNER": cm_runner,
                    "RUNTIME_CLASS": _runtime_class(),
                }))
            created.append(("job", job_name))
            pod = _pod_of_job(job_name, ns)
            worker_peaks = None
            sampler = None
            if pod is not None:
                # Resource measurement (operator decision 2026-10-16): read-only
                # kubelet sampling while the Job runs — it never changes the
                # Job's behavior; a sampler failure never affects the run it
                # observes (the sampler counts errors, never raises).
                sampler = _ResourceSampler(pod, ns)
                sampler.start()
                _stream_pod_logs(pod, ns, os.path.join(live_dir, "pod-stdout.log"),
                                 deadline + 180)
            _wait_job_terminal(job_name, ns, deadline + 60)
            if sampler is not None:
                worker_peaks = sampler.stop_and_peaks()
        except RuntimeError as e:
            rc = int(ExitCode.ENV_FAIL)
            write_env_fail_summary(cfg, label, f"k8s orchestration error — {e}")
            return rc
        except KeyboardInterrupt:
            rc = run_state.interrupted_rc or 130
            return rc

        # The payload: exactly one nonce-matching block, else aborted —
        # nothing is published, `status` reports `missing`.
        payload = None
        pod_log = os.path.join(live_dir, "pod-stdout.log")
        if os.path.isfile(pod_log):
            with open(pod_log, encoding="utf-8", errors="replace") as f:
                payload = extract_payload(f.read(), nonce)
        if payload is None or "summary.json" not in payload:
            cause = _pod_infra_cause(pod, ns)
            if cause:
                # BL-4 (a1): the Pod died of an infrastructure cause (cgroup
                # OOM / kubelet eviction) — rc=16 ENV-FAIL, not the generic
                # 'missing' abort: the 3 ticket retries are not burned on it.
                log(f"K8S: worker Pod {cause} — infrastructure defect (rc=16)")
                rc = int(ExitCode.ENV_FAIL)
                write_env_fail_summary(cfg, label,
                                      f"worker Pod {cause} — infrastructure defect")
                return rc
            # The in-Pod exit code, when the payload carried it but not a
            # summary: name it in the abort log — the session ran and died,
            # the evidence transport did not deliver a verdict.
            internal = ""
            if payload is not None:
                internal = payload.get("internal_rc.txt", b"").strip().decode(
                    "ascii", "replace")
            # Deadline contract (external review 2026-10-16): the Job's own
            # condition says DeadlineExceeded — the session outlived the Job
            # deadline. Infrastructure defect (rc=16), not a 'missing' abort:
            # the 3 ticket retries are not burned on it.
            if _job_infra_cause(job_name, ns) == "DeadlineExceeded":
                log("K8S: Job hit activeDeadlineSeconds (DeadlineExceeded) — "
                    "infrastructure defect (rc=16); fix: raise "
                    "STANOK_K8S_JOB_DEADLINE_S or lower STANOK_TURN_TIMEOUT_S")
                rc = int(ExitCode.ENV_FAIL)
                write_env_fail_summary(
                    cfg, label,
                    "Job DeadlineExceeded — the session outlived the Job "
                    "activeDeadlineSeconds (infrastructure defect)")
                return rc
            log("K8S: no evidence payload block — run treated as aborted "
                "(status 'missing'), no verdict published"
                + (f" (in-Pod session exit code was {internal})"
                   if internal else ""))
            return rc
        for name, data in payload.items():
            with open(os.path.join(live_dir, name), "wb") as f:
                f.write(data)

        # Patch identity (Package 1): the hash of the EXACT payload bytes is
        # computed ONCE here; the on-disk patch file is the payload bytes
        # verbatim (binary write — never a text re-encode), and every later
        # use (scratch apply, fresh Job, live apply) is re-verified against
        # this hash. The identity is recorded in the evidence.
        patch_bytes = payload.get("changes.patch", b"")
        patch_sha = patch_sha256(patch_bytes)
        # Strict decode (encoding-gap micro-patch): a patch that is not
        # valid UTF-8 is a fail-closed contract violation BEFORE any
        # gate/scratch/fresh/apply operation — no U+FFFD substitution.
        try:
            patch_text = strict_patch_text(patch_bytes)
            decode_violation = None
        except UnicodeDecodeError as e:
            patch_text = ""
            decode_violation = (
                f"PATCH-UTF8: changes.patch is not valid UTF-8 ({e}) — "
                "fail closed, nothing is applied")
        patch_file = os.path.join(live_dir, "changes.patch")
        with open(patch_file, "wb") as f:
            f.write(patch_bytes)

        # CC-225: the host stamps opik_traces — the in-Pod summary carries
        # the literal "disabled" (STANOK_IN_CONTAINER=1); the host reaches
        # the Opik backend and counts THIS session's traces, so the field
        # is host-issued (the Pod is not its own judge). None (backend
        # unreachable) leaves the field as written — never a 0 masquerade.
        sum_path = os.path.join(live_dir, "summary.json")
        try:
            with open(sum_path, encoding="utf-8") as f:
                summary = json.load(f)
            summary["patch_sha256"] = patch_sha
            # G4 (SPEC-G4-ACCEPTANCE-CONTRACT-2026-10-14): the acceptance
            # contract is host-stamped from the HOST's own ticket parse —
            # host-issued like patch_sha256/image_digest (the Pod is not its
            # own judge). The mode records whether independent acceptance
            # checks were part of the contract: provided | none | undeclared.
            summary["acceptance"] = {"mode": accept_mode,
                                     "paths": list(accept_paths)}
            # Image provenance (operator plan 2026-10-12): host-stamped like
            # patch_sha256 — the Pod's own containerStatuses record. None is
            # explicit (never a guess), with a WARN, same as commit_sha.
            image_digest = _pod_image_id(pod, ns)
            summary["image_digest"] = image_digest
            if image_digest is None:
                log("WARN: image provenance: Pod imageID unavailable — "
                    "publishing image_digest=None")
            sid = summary.get("session_id")
            if sid:
                stamp_opik_traces(
                    summary, opik.session_trace_count(sid, run_start_iso))
            with open(sum_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except (OSError, json.JSONDecodeError):
            pass

        summary_path = os.path.join(live_dir, "summary.json")
        worker_rc = int(ExitCode.DEFECT)
        try:
            with open(summary_path, encoding="utf-8") as f:
                worker_rc = int(json.load(f).get("rc", 1))
        except (OSError, ValueError, json.JSONDecodeError):
            pass

        # Verdict cross-check (external review 2026-10-16): pod_runner ships
        # the session subprocess's own exit code in internal_rc.txt. cli.py
        # writes summary.json's "rc" and returns the same value, so a healthy
        # run has internal_rc == summary rc. A contradiction means one of the
        # two channels substituted its own verdict — an infrastructure defect
        # (rc=16), not a ticket defect: the 3 ticket retries are not burned
        # on it. Absent (an image predating the contract) -> no check.
        internal_rc = None
        try:
            internal_rc = int(payload["internal_rc.txt"].strip())
        except (KeyError, ValueError):
            pass
        if internal_rc is not None and internal_rc != worker_rc:
            log(f"K8S INTERNAL-RC: in-Pod session exited {internal_rc} but "
                f"summary.json claims rc={worker_rc} — verdict-substitution, "
                "infrastructure defect (rc=16)")
            rc = int(ExitCode.ENV_FAIL)
            write_env_fail_summary(
                cfg, label,
                f"in-Pod session exit {internal_rc} contradicts summary.json "
                f"rc={worker_rc} — verdict-substitution, infrastructure defect")
            return rc

        # Strict UTF-8 decode first (a non-UTF-8 patch never reaches the
        # gate), then the patch gate (a symlink/traversal/absolute/.git/
        # gitlink patch is rejected before anything is applied), then the identity
        # re-verification (the on-disk patch must be the hashed bytes), then
        # the scratch contract recompute — all feed the SAME
        # contract_violations channel _publish_evidence forces to
        # CONTRACT-FAIL.
        if decode_violation:
            contract_violations = [decode_violation]
            log(f"K8S PATCH-UTF8: {decode_violation}")
        else:
            contract_violations = patch_gate(patch_text)
            if contract_violations:
                log(f"K8S PATCH-GATE: {contract_violations}")
        if not contract_violations:
            if not patch_identity_ok(patch_file, patch_sha):
                contract_violations = [
                    f"PATCH-SHA: {patch_file} does not match the hashed patch "
                    f"bytes ({patch_sha}) — fail closed, nothing is applied"]
                log(f"K8S PATCH-SHA: {contract_violations}")
            else:
                try:
                    scratch = apply_patch_scratch(tree_blob, patch_text)
                except RuntimeError as e:
                    contract_violations = [f"PATCH-APPLY: {e}"]
                else:
                    try:
                        contract_violations = scratch_contract_violations(
                            cfg, before_manifest, scratch, declared)
                    finally:
                        shutil.rmtree(scratch, ignore_errors=True)

        # The fresh check runs ONLY when the contract is intact (a fresh run
        # over a tampered tree is uninformative — spec §1.6); it is NOT
        # gated on the worker's claims.
        fresh_check = None
        fresh_infra_error = None
        fresh_peaks = None
        if not contract_violations:
            peaks_holder = {}
            fresh_rc, fresh_tail = _fresh_job(cfg, ns, fresh_name, cm_tree,
                                              cm_patch, patch_file, deadline,
                                              created, image_ref, peaks_holder)
            fresh_peaks = peaks_holder.get("peaks")
            if fresh_tail.startswith("EXEC_ERROR:"):
                fresh_infra_error = fresh_tail
            else:
                fresh_check = (fresh_rc, fresh_tail)

        # Resource measurement (operator decision 2026-10-16): host-stamped
        # like patch_sha256 — the OBSERVED kubelet peaks of this run, closing
        # the "pending measured peaks" gap of bb5eed6. None = no sample ever
        # succeeded (never a 0 masquerade). These are kubelet numbers, not
        # truth claims (gVisor caveat, BL-4).
        try:
            with open(summary_path, encoding="utf-8") as f:
                summary = json.load(f)
            summary["resource_peaks"] = {"worker": worker_peaks,
                                         "fresh": fresh_peaks}
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump(summary, f, ensure_ascii=False, indent=2)
        except (OSError, json.JSONDecodeError):
            log("WARN: resource_peaks: summary.json unreadable — field not "
                "stamped")

        _publish_evidence(cfg, label, worker_rc, contract_violations,
                          fresh_check)

        # The rc alignment, verbatim: the process exit must not contradict
        # the summary the supervisor reads.
        rc = worker_rc
        if fresh_infra_error is not None:
            rc = int(ExitCode.ENV_FAIL)
            write_env_fail_summary(cfg, label,
                                   f"fresh check unavailable — {fresh_infra_error}")
        elif fresh_check is not None and fresh_check[0] != 0:
            rc = fresh_check[0]
        elif contract_violations and rc == 0:
            rc = int(ExitCode.DEFECT)

        # §6 ordering: the patch lands on the LIVE tree ONLY on a final PASS
        # (rc=0, no violations, fresh green). A defect leaves the live tree
        # exactly as the run started.
        if (rc == 0 and not contract_violations
                and (fresh_check is None or fresh_check[0] == 0)
                and patch_text.strip()):
            # Identity re-verified a third time, immediately before the live
            # apply (Package 1): the bytes that land on the live tree must be
            # the bytes the verdict was computed against — fail closed.
            if not patch_identity_ok(patch_file, patch_sha):
                log(f"WARN: final PASS but patch identity mismatch before "
                    f"live apply (expected {patch_sha}) — apply SKIPPED")
            else:
                r = subprocess.run(["git", "apply", patch_file],
                                   cwd=cfg.repo_root,
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    log(f"WARN: final PASS but git apply on the live tree "
                        f"failed (rc={r.returncode}): {r.stderr.strip()}")
        return rc
    except KeyboardInterrupt:
        return run_state.interrupted_rc or 130
    finally:
        # Best-effort cleanup of THIS run's artifacts only: every entry in
        # `created` was created by a successful create (ownership proven).
        # Resources this run never created are NOT touched — a foreign object
        # with a colliding name survives (operator P0 2026-10-11).
        for kind, name in created:
            _kubectl("delete", kind, name, "-n", ns, "--ignore-not-found",
                     "--wait=false")
        try:
            os.remove(marker)
        except OSError:
            pass
