"""k8s — the host-side orchestrator of the K8s runtime (SPEC-STANOK-K8S-RUNTIME-2026-10-10).

The runtime switch (CC-231 production cutover, supersedes the P1 §3
default): launch.sh keeps its contract (`run <ticket>
<label> --follow`, status/wait/stop, the marker and summary.json semantics);
this module is the DEFAULT host branch — the Docker path (_host_launch)
runs only on an explicit STANOK_RUNTIME=docker. The
Pod works on a TRANSPORTED COPY of the tree (git archive HEAD | gzip |
base64 through a ConfigMap — the measured decision of 2026-10-10: the full
bundle is 1.3MB > the 800KB ConfigMap threshold, the tarball is ~240KB); the
live tree is never touched during the run. The Pod returns its evidence as
ONE base64 gzip-tar block between nonce markers on stdout; the host accepts
EXACTLY ONE nonce-matching block (zero/two/unclosed = aborted, status
`missing`, never a verdict).

The verdict stays host-issued with the same priority as the Docker path
(CONTRACT-FAIL > FRESH-FAIL > the worker's claims, summary.
_publish_evidence reused unchanged). Because the live tree is untouched, the
host recomputes the protected-files manifest against a SCRATCH tree
(extracted tree + git apply changes.patch) with the SAME
verify._compare_manifests — the two paths cannot drift. The patch gate
(reject filemode 120000 / '..' paths) re-asserts the zone/symlink
invariants on the transport layer; a violation is a host-issued
CONTRACT-FAIL, never a silent apply. The patch lands on the live tree ONLY
on a final PASS (§6 ordering).

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
import tempfile
import time
import uuid

from launcher import opik, verify
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
    verify._tests_manifest + _compare_manifests as the Docker path (the two
    cannot drift): the live tree is untouched in k8s mode, so the tree the
    verdict was computed against is `transported tree + patch`."""
    scratch_cfg = dataclasses.replace(cfg, repo_root=scratch_dir)
    return verify._compare_manifests(before, verify._tests_manifest(scratch_cfg),
                                     declared)


def disable_sandbox_settings(settings_text: str) -> str:
    """O3 (operator 2026-10-10): the machine's native bwrap sandbox is
    DISABLED in the Pod — the K8s boundary (NetworkPolicy + securityContext
    + non-root) replaces it, and bwrap cannot run under a RuntimeDefault
    seccomp profile. The filesystem deny entries and the network block are
    REMOVED (the sandbox_config_gate would otherwise rc=28 on '../evidence'
    — a path that does not exist next to the extracted tree). env and
    permissions are preserved byte-for-byte."""
    data = json.loads(settings_text)
    sandbox = data.setdefault("sandbox", {})
    sandbox["enabled"] = False
    sandbox["failIfUnavailable"] = False
    sandbox.pop("filesystem", None)
    sandbox.pop("network", None)
    return json.dumps(data, ensure_ascii=False, indent=2)


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


def _apply_manifest(text: str) -> None:
    r = _kubectl("apply", "-f", "-", input_text=text)
    if r.returncode != 0:
        raise RuntimeError(f"kubectl apply failed (rc={r.returncode}): "
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


def _stream_pod_logs(pod: str, ns: str, path: str, timeout_s: int) -> None:
    """kubectl logs -f blocks until the Pod's containers exit — the payload
    lands in the host-side log file, never in the supervisor's context."""
    with open(path, "wb") as lf:
        try:
            subprocess.run([_kubectl_bin(), "logs", "-f", pod, "-n", ns],
                           stdout=lf, stderr=subprocess.STDOUT,
                           timeout=timeout_s)
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


def job_deadline() -> int:
    """CC-230: Job activeDeadlineSeconds — 30-minute insurance against a
    hung container (both Jobs share this value; STANOK_K8S_JOB_DEADLINE_S
    overrides)."""
    return int(os.environ.get("STANOK_K8S_JOB_DEADLINE_S", "1800"))


# ==================================================================================
# The fresh check as a deny-all Job (mirror of sandbox.fresh_verify_argv:
# the same `run.sh list; run.sh test --all` pair, no model endpoint)
# ==================================================================================
def _fresh_job(cfg, ns: str, fresh_name: str, cm_tree: str, cm_patch: str,
               patch_file: str, deadline: int) -> tuple:
    try:
        _kubectl_checked("create", "configmap", cm_patch, "-n", ns,
                        f"--from-file=changes.patch={patch_file}")
        _apply_manifest(render_template(_read_manifest("fresh-job.yaml.tmpl"), {
            "JOB_NAME": fresh_name.removeprefix("stanok-fresh-"),
            "IMAGE": cfg.docker_image, "NAMESPACE": ns,
            "CM_TREE": cm_tree, "CM_PATCH": cm_patch, "DEADLINE": str(deadline),
        }))
    except RuntimeError as e:
        return (1, f"EXEC_ERROR: {e}")
    if _wait_job_terminal(fresh_name, ns, deadline + 60) == "complete":
        return (0, "")
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
# host_launch_k8s — the DEFAULT host branch (CC-231; Docker only on an
# explicit STANOK_RUNTIME=docker)
# ==================================================================================
def host_launch_k8s(cfg, args, marker: str) -> int:
    """The K8s-mode host supervision (the counterpart of run_sandboxed):
    transport -> worker Job -> payload -> patch gate + patch identity
    (SHA-256, re-verified before every apply) -> scratch contract ->
    fresh Job -> _publish_evidence -> rc alignment. The marker/summary
    protocol is identical to the Docker path: the supervisor reads
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

    # The same ticket gate as _host_launch (CC-133/CC-206) — before any
    # cluster call: the machine must not start for an unsatisfiable contract.
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            declared, edit_paths, _ = parse_ticket_header(cfg, f.read())
        assert_create_paths_are_new(cfg, declared, edit_paths)
        assert_edit_paths_are_not_protected(cfg, edit_paths)
    except (OSError, ValueError) as e:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.TICKET,
                            f"ERROR: ticket parse error: {e}")

    # CC-232 pre-flight doctor gate (fail-closed): cluster health + manifest
    # contract BEFORE any ConfigMap/Job is created — a dead cluster or a
    # drifted template must not produce cluster resources. Infrastructure
    # defect: rc=16, no marker, no evidence dir.
    preflight = _preflight_cluster(cfg)
    if preflight:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: PREFLIGHT: {preflight}")

    evidence_dir, live_dir = cfg.label_paths(label)
    os.makedirs(evidence_dir, exist_ok=True)
    os.makedirs(live_dir, exist_ok=True)
    run_state = RunState(evidence_dir=evidence_dir, live_dir=live_dir,
                         marker_path=marker)
    with open(marker, "w", encoding="utf-8") as f:
        f.write(f"{int(time.time())} {os.getpid()}\n")
    _install_signal_handlers(run_state)

    # A stale summary.json from an earlier run of this label must not be
    # re-published as this run's verdict (same as run_sandboxed).
    stale = os.path.join(live_dir, "summary.json")
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
    deadline = job_deadline()
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
    try:
        try:
            _kubectl_checked("create", "configmap", cm_ticket, "-n", ns,
                             f"--from-file=ticket.md={args.ticket_path}")
            _kubectl_checked("create", "configmap", cm_tree, "-n", ns,
                             f"--from-file=tree.tar.gz.b64={tree_file}")
            _kubectl_checked("create", "configmap", cm_runner, "-n", ns,
                             "--from-file=pod_runner.py=" +
                             os.path.join(LAUNCHER_DIR, "pod_runner.py"))
            _apply_manifest(render_template(
                _read_manifest("worker-job.yaml.tmpl"), {
                    "JOB_NAME": job_name, "LABEL": label, "NONCE": nonce,
                    "IMAGE": cfg.docker_image, "NAMESPACE": ns,
                    "SERVER_URL": cfg.server_url, "MODEL": cfg.model,
                    "OPIK_TRACE_URL": os.environ.get("STANOK_OPIK_TRACE_URL", ""),
                    "START_COMMIT": os.environ.get("STANOK_START_COMMIT", ""),
                    "DEADLINE": str(deadline),
                    "CM_TICKET": cm_ticket, "CM_TREE": cm_tree,
                    "CM_RUNNER": cm_runner,
                }))
            pod = _pod_of_job(job_name, ns)
            if pod is not None:
                _stream_pod_logs(pod, ns, os.path.join(live_dir, "pod-stdout.log"),
                                 deadline + 180)
            _wait_job_terminal(job_name, ns, deadline + 60)
        except RuntimeError as e:
            rc = int(ExitCode.ENV_FAIL)
            write_env_fail_summary(cfg, label, f"k8s orchestration error — {e}")
            return rc
        except KeyboardInterrupt:
            rc = run_state.interrupted_rc or 130
            return rc

        # The payload: exactly one nonce-matching block, else aborted —
        # nothing is published, `status` reports `missing` (the same
        # semantics as the Docker path's no-summary case).
        payload = None
        pod_log = os.path.join(live_dir, "pod-stdout.log")
        if os.path.isfile(pod_log):
            with open(pod_log, encoding="utf-8", errors="replace") as f:
                payload = extract_payload(f.read(), nonce)
        if payload is None or "summary.json" not in payload:
            log("K8S: no evidence payload block — run treated as aborted "
                "(status 'missing'), no verdict published")
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
        if not contract_violations:
            fresh_rc, fresh_tail = _fresh_job(cfg, ns, fresh_name, cm_tree,
                                              cm_patch, patch_file, deadline)
            if fresh_tail.startswith("EXEC_ERROR:"):
                fresh_infra_error = fresh_tail
            else:
                fresh_check = (fresh_rc, fresh_tail)

        _publish_evidence(cfg, label, worker_rc, contract_violations,
                          fresh_check)

        # The rc alignment of run_sandboxed, verbatim: the process exit must
        # not contradict the summary the supervisor reads.
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
        # Best-effort cleanup: the Jobs and transport ConfigMaps are run
        # artifacts, not cluster state to keep.
        for kind, name in (("job", job_name), ("job", fresh_name),
                          ("configmap", cm_ticket), ("configmap", cm_tree),
                          ("configmap", cm_runner), ("configmap", cm_patch)):
            _kubectl("delete", kind, name, "-n", ns, "--ignore-not-found",
                     "--wait=false")
        try:
            os.remove(marker)
        except OSError:
            pass
