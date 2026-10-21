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
import io
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid

from launcher import gates, kube, lifecycle, opik, peaks, patchgate, preflight, verify
from launcher.abort import _early_abort  # wave A step 1: was a lazy import from cli (the cli->k8s cycle was its only reason; abort imports neither)
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
# Wave A portion 2 (2026-10-21): K8S_DIR moved with _read_manifest to
# launcher/kube.py — the manifest directory is read only there.

# The ConfigMap size guard (O4): measured 2026-10-10 — full git bundle
# 1,308,067B > the threshold; `git archive HEAD | gzip | base64` ~240KB.
# Fail-closed BEFORE any kubectl call.
TRANSPORT_MAX_B64 = 800_000

# R4 (Z.ai external review 2026-10-20, operator order 2026-10-21): the
# decompressed-payload cap. The payload is the Pod's evidence channel; a
# pathological or hostile gzip-tar block can decompress to an arbitrary
# size, and the host must not materialize it unconditionally. An extracted
# total above this limit is rejected whole (None — the run is treated as
# aborted), fail-closed like the member-name guard in extract_payload.
# Real payloads are the five flat files pod_runner.py:154-161 emits, far
# below 64MiB; the cap bounds only malformed/adversarial blocks.
# #312 (B1a, host-side — precedent CC-266): the budget is enforced IN-STREAM
# (see _bounded_gunzip below), not post-hoc — peak materialization is O(cap).
# Pair tests: tests_harness/test_k8s_payload.py (R4 + #312 pairs).
PAYLOAD_MAX_DECOMPRESSED_BYTES = 64 * 1024 * 1024

# #312 (B1a): headroom INSIDE the stream budget for tar STRUCTURE — 512-byte
# headers/blocks, padding, pax attributes. An honest payload at the file-sum
# cap carries ~10 KiB of structure (the five flat files); 1 MiB admits that
# with ~100x margin, while a header FLOOD merely consumes its own budget and
# is rejected fail-closed like every malformed shape.
PAYLOAD_TAR_OVERHEAD_BYTES = 1 * 1024 * 1024

# C3 (review 2026-10-17): the fresh Pod's own `git apply` failure must exit
# with a code DISJOINT from every run.sh/runner code (run.sh header:
# 0,1,2,3,4,5,6,7,124; pytest 0-5, node --test 0/1, jq 0/5) so the host can
# classify it as an infrastructure defect instead of a test failure. The host
# already applied the identical verified bytes to the scratch tree — a Pod that
# cannot apply the same patch to the same tree is a Pod anomaly, not a defect.
# Rendered into fresh-job.yaml.tmpl via {{APPLY_FAIL_RC}} (single source, same
# convention as {{DEADLINE}}).
FRESH_APPLY_FAIL_RC = 20


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
        # fail closed (wave C F5; corrected by measurement 2026-10-20):
        # unpack_tree is HOST-side only — the host runtime is the launcher
        # venv (measured 3.13.13), which HAS the `filter` kwarg; the Pod
        # image is measured 3.11.2 with NO `filter` kwarg in extractall,
        # which is exactly why pod_runner._unpack keeps the TypeError
        # fallback. The old host-side `except TypeError` silently dropped
        # the filter on a runtime where it cannot occur; removed — a
        # TypeError must propagate.
        tf.extractall(dest, filter="data")


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


# #312: the streaming window of _bounded_gunzip — output is decompressed in
# capped reads so an over-budget stream aborts before its bytes exist.
_GUNZIP_CHUNK = 256 * 1024


def _bounded_gunzip(compressed: bytes, limit: int) -> "bytes | None":
    """#312 (B1a): gunzip with a hard output budget. Returns the decompressed
    stream, or None the MOMENT it would exceed `limit` — gzip.GzipFile.read(n)
    caps each read, so the output never grows past limit + one chunk and a
    bomb is rejected mid-stream, before its bytes are materialized. Malformed
    input raises exactly like the plain gzip.decompress this replaces."""
    out = bytearray()
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as gz:
        while True:
            chunk = gz.read(_GUNZIP_CHUNK)
            if not chunk:
                return bytes(out)
            out += chunk
            if len(out) > limit:
                return None


def extract_payload(text: str, nonce: str):
    """The exactly-one rule: one and only one nonce-matching block, else
    None (the run is treated as aborted, never a verdict).

    Member-name guard (operator spec 2026-10-20, external-review finding):
    the Pod is an external boundary and its member names reach
    `os.path.join(live_dir, name)` at the write site — a directory component
    or a leading '/' would write outside live_dir. A name must be a bare
    flat filename: `os.path.basename(name) != name or
    name.startswith(("/", ".."))` fails closed like a malformed block
    (None, the run is aborted). `''` and `'.'` collapse os.path.join to
    live_dir itself — IsADirectoryError at the write site, not a clean
    abort (B1a review 2026-10-20) — rejected by the same guard.
    pod_runner.py:154-161 emits only flat names (changes.patch,
    internal_rc.txt, summary.json, launcher.stdout.log, failures.log), so
    a real payload never trips this.

    Decompressed-size guard (R4, Z.ai external review 2026-10-20, operator
    order 2026-10-21): a block whose extracted files total more than
    PAYLOAD_MAX_DECOMPRESSED_BYTES fails closed like a malformed block
    (None). #312 (B1a 2026-10-21, host-side — precedent CC-266) makes the
    budget IN-STREAM instead of post-hoc: the gunzip is bounded by the cap
    plus tar structure overhead (PAYLOAD_TAR_OVERHEAD_BYTES), and each
    member read is capped by the remaining budget — peak materialization
    is O(cap), so an over-cap bomb aborts mid-stream, before its bytes
    exist. Pair tests: tests_harness/test_k8s_payload.py (R4 + #312 pairs,
    the latter with a tracemalloc peak)."""
    pattern = (re.escape(begin_marker(nonce)) + r"\s*(.*?)\s*"
               + re.escape(end_marker(nonce)))
    blocks = re.findall(pattern, text, re.DOTALL)
    if len(blocks) != 1:
        return None
    # #312 (B1a): the budget starts at the gunzip — the decompressed stream
    # itself is capped (file bytes + tar structure overhead), so a bomb never
    # materializes; the b64 blob is already bounded by the input text.
    raw = _bounded_gunzip(base64.b64decode(blocks[0]),
                          PAYLOAD_MAX_DECOMPRESSED_BYTES
                          + PAYLOAD_TAR_OVERHEAD_BYTES)
    if raw is None:
        return None
    files = {}
    total = 0
    with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
        for m in tf.getmembers():
            if m.isfile():
                name = m.name
                if (not name or name == "."
                        or os.path.basename(name) != name
                        or name.startswith(("/", ".."))):
                    return None
                member_file = tf.extractfile(m)
                if member_file is None:  # fail-closed like the name checks above
                    return None
                # #312 (B1a): the R4 budget enforced per member — the read is
                # capped by what remains, so an over-cap total is rejected
                # BEFORE the bytes exist (not post-hoc after the loop).
                remaining = PAYLOAD_MAX_DECOMPRESSED_BYTES - total
                data = member_file.read(remaining + 1)
                if len(data) > remaining:
                    return None
                files[name] = data
                total += len(data)
    return files


# Wave A portion 4 (2026-10-21): the patch-gate cluster (_DIFF_HEADER_PREFIX
# and the mode/index regexes, _path_violations/_git_unquote/_numstat_paths/
# _zone_violation/patch_gate, patch_sha256/strict_patch_text/patch_identity_ok)
# moved verbatim to launcher/patchgate.py (strict from birth). Single patch
# home: k8s holds no def and no re-export; the remaining code calls them as
# patchgate._X — a test stub on a name there intercepts every call site.
# Guard: tests_harness/test_patchgate_facade.py. _live_tree_drift and the
# scratch cluster (apply_patch_scratch/scratch_contract_violations) stay here:
# they belong to the transport/contract machinery (unpack_tree,
# verify._compare_manifests, gates.dirty_tree_gate) of a later portion.


def _live_tree_drift(cfg) -> str | None:
    """B4 (external review 2026-10-17): the live-apply is only sound if the
    live tree is still the tree the run started from. The verdict was
    computed against the TRANSPORTED tree (`git archive HEAD` at snapshot
    time) + patch — never against the live tree; STANOK_START_COMMIT
    (cli._capture_start_commit, exported before launch) pins the commit the
    run started from. A moved HEAD or uncommitted changes mean something
    OUTSIDE this run changed the apply target between the snapshot and this
    moment — fail closed: a git error counts as drift (unknown state), an
    unset STANOK_START_COMMIT means the start commit is unknowable.
    Returns a drift description, or None when the tree is provably
    unchanged. Point-in-time by nature: drift appearing between this check
    and `git apply` is still caught by the apply itself (conflicting patch,
    scenario 13)."""
    start_commit = os.environ.get("STANOK_START_COMMIT", "")
    if not start_commit:
        return ("STANOK_START_COMMIT is unset — the run's start commit is "
                "unknown, the live tree cannot be proven unchanged")
    try:
        r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cfg.repo_root,
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError) as e:
        # Fail closed (the docstring above): a git call that RAISES is an
        # unknown tree state, same as a non-zero rc. Same shape as
        # cli._capture_start_commit (cli.py:635-644), the host's other
        # call to this exact command.
        return (f"git rev-parse HEAD raised {e} — the live tree cannot "
                "be proven unchanged")
    if r.returncode != 0:
        return (f"git rev-parse HEAD failed (rc={r.returncode}): "
                f"{r.stderr.strip()} — the live tree cannot be proven unchanged")
    head = r.stdout.strip()
    if head != start_commit:
        return (f"live tree HEAD {head} != run start commit {start_commit} — "
                "the tree moved since the run began")
    if gates.dirty_tree_gate(cfg):
        return ("live tree has uncommitted changes (git status --porcelain "
                "non-empty) — the tree was touched since the run began")
    return None


def apply_patch_scratch(tree_blob: str, patch_text: str) -> str:
    """The scratch tree the k8s-mode verdict is computed against: extracted
    transport tree + `git apply` of the Pod's patch (git apply works outside
    a repo — verified 2026-10-10). Returns the scratch dir.

    Wave C (operator 2026-10-20, the same failure class as the numstat
    mkdtemp case fixed by variant 2): `tempfile.mkdtemp` runs inside the
    try and an OSError from scratch setup is re-raised as RuntimeError —
    the channel the call site in host_launch_k8s already maps to
    PATCH-APPLY. Before this the mkdtemp was outside any try,
    host_launch_k8s has no `except Exception` (only KeyboardInterrupt +
    finally), and a failed mkdtemp escaped as a raw OSError: the run died
    with no published verdict. A scratch dir created before ANY failure
    (including the pre-existing `git apply` RuntimeError path, which used
    to leak it) is removed. The `scratch = None` sentinel and the
    `if scratch is not None` guard are load-bearing: rmtree(None) RAISES
    TypeError on the host runtime 3.13.13 (measured 2026-10-19)."""
    scratch = None
    try:
        scratch = tempfile.mkdtemp(prefix="stanok-scratch-")
        unpack_tree(tree_blob, scratch)
        if patch_text.strip():
            patch_file = os.path.join(scratch, ".changes.patch")
            with open(patch_file, "w", encoding="utf-8") as f:
                f.write(patch_text)
            r = subprocess.run(["git", "apply", ".changes.patch"],
                               cwd=scratch, capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"git apply failed (rc={r.returncode}): "
                                   f"{r.stderr.strip()}")
        return scratch  # success: caller owns the dir and removes it
    except OSError as e:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        raise RuntimeError(f"scratch setup failed: {e}") from e
    except BaseException:
        if scratch is not None:
            shutil.rmtree(scratch, ignore_errors=True)
        raise


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


# Wave A portion 2 (2026-10-21): render_template / _read_manifest and the
# kubectl plumbing (_kubectl, _kubectl_checked, _create_manifest,
# _kubectl_bin, _namespace, _k8s_name, _cluster_env) moved verbatim to
# launcher/kube.py (agreed T3 sequence). Every call below is kube._X —
# kube is the single patch home (guard: tests_harness/test_kube_facade.py).


# ==================================================================================
# Wave A portion 6 (2026-10-21): the lifecycle observation cluster
# (_pod_of_job, _pod_image_id, _stream_pod_logs, _job_rc_and_tail,
# _pod_infra_cause, _job_infra_cause, _wait_job_terminal, the observation
# graces _STREAM_GRACE_S/_TERMINAL_GRACE_S and _observation_timeout) moved
# verbatim to launcher/lifecycle.py (strict from birth). Single home: k8s
# holds no def, no constant and no re-export; the call sites here
# (host_launch_k8s, _fresh_job) call lifecycle._X. The Job-construction
# policy they are measured against stays here: _DEADLINE_MARGIN_S,
# job_deadline (activeDeadlineSeconds belongs to Job creation). Guard:
# tests_harness/test_lifecycle_facade.py.
# ==================================================================================


# Startup margin over the turn timeout: tree unpack, git init, settings
# rewrite, CLI start (external review 2026-10-16). The post-deadline
# observation graces and the shared-end window calculator moved with the
# observation cluster to launcher/lifecycle.py (wave A portion 6); the
# timer contract test now reaches them at their new home.
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


# ==================================================================================
# Wave A portion 5 (2026-10-21): the resource-sampling cluster
# (SAMPLE_INTERVAL_S, _node_of_pod, _kubelet_stats, _peak_from_stats,
# _ResourceSampler) moved verbatim to launcher/peaks.py (strict from birth).
# Single home: k8s holds no def, no constant and no re-export; the
# construction sites here call peaks._ResourceSampler. Guard:
# tests_harness/test_peaks_facade.py. (The Pod lifecycle helpers named as a
# "later portion" there moved to launcher/lifecycle.py with portion 6.)
# ==================================================================================


# ==================================================================================
# The fresh check as a deny-all Job (the same `run.sh list; run.sh test
# --all` pair as the worker, no model endpoint — the Docker-era
# fresh_verify_argv mirror is gone with the Docker path, CC-258)
# ==================================================================================
def _fresh_job(cfg, ns: str, fresh_name: str, cm_tree: str, cm_patch: str,
               patch_file: str, deadline: int, created: list,
               image_ref: str, peaks_out: dict | None = None) -> tuple:
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
        kube._kubectl_checked("create", "configmap", cm_patch, "-n", ns,
                        f"--from-file=changes.patch={patch_file}")
        created.append(("configmap", cm_patch))
        kube._create_manifest(kube.render_template(kube._read_manifest("fresh-job.yaml.tmpl"), {
            "JOB_NAME": fresh_name.removeprefix("stanok-fresh-"),
            "IMAGE": image_ref, "NAMESPACE": ns,
            "CM_TREE": cm_tree, "CM_PATCH": cm_patch, "DEADLINE": str(deadline),
            "RUNTIME_CLASS": kube._runtime_class(),
            "APPLY_FAIL_RC": str(FRESH_APPLY_FAIL_RC),
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
        fresh_pod = lifecycle._pod_of_job(fresh_name, ns, timeout_s=30)
        if fresh_pod is not None:
            sampler = peaks._ResourceSampler(fresh_pod, ns)
            sampler.start()
    completed = lifecycle._wait_job_terminal(fresh_name, ns,
                                  deadline + lifecycle._TERMINAL_GRACE_S) == "complete"
    if sampler is not None and peaks_out is not None:  # sampler is only built when a holder was provided — the second test is type-honesty, not behavior
        peaks_out["peaks"] = sampler.stop_and_peaks()
    if completed:
        return (0, "")
    # BL-4 (a2): a fresh Pod killed by an infrastructure cause (cgroup OOM /
    # eviction) is EXEC_ERROR — the caller maps it to rc=16 ENV-FAIL, not a
    # FRESH-FAIL that burns the ticket's 3 retries on an infrastructure defect.
    if fresh_pod is None:
        fresh_pod = lifecycle._pod_of_job(fresh_name, ns, timeout_s=30)
    cause = lifecycle._pod_infra_cause(fresh_pod, ns)
    if cause:
        return (1, f"EXEC_ERROR: fresh Pod {cause} — infrastructure defect")
    # A1 (review 2026-10-17): symmetry with the worker path — a fresh Job
    # killed by its own activeDeadlineSeconds is an infrastructure defect
    # (the caller maps EXEC_ERROR to rc=16), not a FRESH-FAIL that burns
    # the ticket's 3 retries. The Pod side shows only a bare SIGKILL; the
    # Job-level condition is the honest signal.
    job_cause = lifecycle._job_infra_cause(fresh_name, ns)
    if job_cause:
        return (1, f"EXEC_ERROR: fresh Job {job_cause} — infrastructure defect")
    exit_rc, tail = lifecycle._job_rc_and_tail(fresh_name, ns)
    # C3 (review 2026-10-17): the Pod-side apply guard exits with
    # FRESH_APPLY_FAIL_RC before any test runs. The host already applied the
    # identical verified bytes to the scratch tree — the same patch failing
    # on the same tree is a Pod anomaly (infrastructure), not a test failure.
    if exit_rc == FRESH_APPLY_FAIL_RC:
        return (1, f"EXEC_ERROR: fresh Job git apply of changes.patch failed "
                   f"(exit {FRESH_APPLY_FAIL_RC}) — infrastructure defect")
    if not tail.strip():
        tail = f"the fresh Job did not complete (exit {exit_rc})"
    return (exit_rc, verify._tail_output(cfg, tail))


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
    label = args.label
    ns = kube._namespace()
    kname = kube._k8s_name(label)
    job_name = f"stanok-job-{kname}"
    fresh_name = f"stanok-fresh-{kname}"
    cm_ticket = f"stanok-ticket-{kname}"
    cm_tree = f"stanok-tree-{kname}"
    cm_runner = f"stanok-runner-{kname}"
    cm_patch = f"stanok-patch-{kname}"

    if shutil.which(kube._kubectl_bin()) is None:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.ENV_FAIL,
                            f"ERROR: kubectl ({kube._kubectl_bin()}) not found — the "
                            "K8s runtime is unavailable (rc=16, infrastructure)")

    # The ticket gate (CC-133/CC-206) — before any cluster call: the machine
    # must not start for an unsatisfiable contract.
    try:
        with open(args.ticket_path, encoding="utf-8") as f:
            declared, edit_paths, reset_none, accept_paths, accept_mode = \
                parse_ticket_header(cfg, f.read())
        assert_create_paths_are_new(cfg, declared, edit_paths)
        assert_edit_paths_are_not_protected(cfg, edit_paths)
    except (OSError, ValueError) as e:
        return _early_abort(cfg, marker, label, args.ticket, ExitCode.TICKET,
                            f"ERROR: ticket parse error: {e}")
    # B5 (review 2026-10-17): the k8s path self-validates the ticket
    # contract — the cli.cmd_run gate is not assumed (host_launch_k8s is a
    # callable boundary in its own right). Same fail-closed rule as the cli
    # gate: an empty-declared ticket is only valid with an explicit
    # `reset: none`.
    if not declared and not reset_none:
        return _early_abort(
            cfg, marker, label, args.ticket, ExitCode.TICKET,
            "ERROR: ticket declares no `impl:`/`test:`/`docs:`/`edit:` "
            "line and no `reset: none` — the ticket-scoped invariant "
            "cannot be enforced (fail-closed)")

    # Unified launch preflight (operator spec 2026-10-12; CC-232 subsumed):
    # disk, image staleness, Opik reachability, cluster health + manifest
    # contract, RuntimeClass, dangling stanok resources — BEFORE any
    # ConfigMap/Job is created. Infrastructure defect: rc=16, no marker, no
    # evidence dir. Clean tree + start commit are enforced upstream in
    # cli.cmd_run (rc=22 / STANOK_START_COMMIT) — not duplicated here.
    reason = preflight._preflight(cfg)
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
            kube._kubectl_checked("create", "configmap", cm_ticket, "-n", ns,
                             f"--from-file=ticket.md={args.ticket_path}")
            created.append(("configmap", cm_ticket))
            kube._kubectl_checked("create", "configmap", cm_tree, "-n", ns,
                             f"--from-file=tree.tar.gz.b64={tree_file}")
            created.append(("configmap", cm_tree))
            kube._kubectl_checked("create", "configmap", cm_runner, "-n", ns,
                             "--from-file=pod_runner.py=" +
                             os.path.join(LAUNCHER_DIR, "pod_runner.py"))
            created.append(("configmap", cm_runner))
            kube._create_manifest(kube.render_template(
                kube._read_manifest("worker-job.yaml.tmpl"), {
                    "JOB_NAME": job_name, "LABEL": label, "NONCE": nonce,
                    "IMAGE": image_ref, "NAMESPACE": ns,
                    "SERVER_URL": cfg.server_url, "MODEL": cfg.model,
                    "OPIK_TRACE_URL": cfg.opik_trace_url,
                    "START_COMMIT": os.environ.get("STANOK_START_COMMIT", ""),
                    "DEADLINE": str(deadline),
                    "CM_TICKET": cm_ticket, "CM_TREE": cm_tree,
                    "CM_RUNNER": cm_runner,
                    "RUNTIME_CLASS": kube._runtime_class(),
                }))
            created.append(("job", job_name))
            obs_start = time.monotonic()  # A3: anchor of the observation chain
            pod = lifecycle._pod_of_job(job_name, ns)
            worker_peaks = None
            sampler = None
            stream_failed = False
            if pod is not None:
                # Resource measurement (operator decision 2026-10-16): read-only
                # kubelet sampling while the Job runs — it never changes the
                # Job's behavior; a sampler failure never affects the run it
                # observes (the sampler counts errors, never raises).
                sampler = peaks._ResourceSampler(pod, ns)
                sampler.start()
                stream_failed = not lifecycle._stream_pod_logs(
                    pod, ns, os.path.join(live_dir, "pod-stdout.log"),
                    lifecycle._observation_timeout(obs_start, deadline,
                                                  lifecycle._STREAM_GRACE_S))
            lifecycle._wait_job_terminal(job_name, ns, lifecycle._observation_timeout(
                obs_start, deadline,
                lifecycle._STREAM_GRACE_S + lifecycle._TERMINAL_GRACE_S))
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
            cause = lifecycle._pod_infra_cause(pod, ns)
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
            if lifecycle._job_infra_cause(job_name, ns) == "DeadlineExceeded":
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
                + (" (kubectl logs -f failed — pod-stdout.log incomplete)"
                   if stream_failed else "")
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
        patch_sha = patchgate.patch_sha256(patch_bytes)
        # Strict decode (encoding-gap micro-patch): a patch that is not
        # valid UTF-8 is a fail-closed contract violation BEFORE any
        # gate/scratch/fresh/apply operation — no U+FFFD substitution.
        try:
            patch_text = patchgate.strict_patch_text(patch_bytes)
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
            image_digest = lifecycle._pod_image_id(pod, ns)
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
            contract_violations = patchgate.patch_gate(patch_text)
            if contract_violations:
                log(f"K8S PATCH-GATE: {contract_violations}")
        if not contract_violations:
            if not patchgate.patch_identity_ok(patch_file, patch_sha):
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
            peaks_holder: dict = {}  # annotated: empty literal infers nothing usable
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
            # A5 (review 2026-10-17): both failure branches here were WARN —
            # the run still published rc=0/PASS with the patch UNAPPLIED. A
            # claimed PASS whose patch never landed is not a PASS: the verdict
            # is downgraded to rc=16 ENV-FAIL (the apply/identity machinery
            # failed, not the ticket — the 3 ticket retries are not burned),
            # the published summary is overwritten via write_env_fail_summary
            # (same pattern as the fresh_infra_error branch above), and the
            # live tree stays exactly as the run started: git apply is
            # atomic, and the identity branch applied nothing.
            if not patchgate.patch_identity_ok(patch_file, patch_sha):
                log(f"ERROR: final PASS but patch identity mismatch before "
                    f"live apply (expected {patch_sha}) — apply SKIPPED")
                rc = int(ExitCode.ENV_FAIL)
                write_env_fail_summary(
                    cfg, label,
                    f"final PASS but patch identity mismatch before live "
                    f"apply (expected {patch_sha}) — patch not applied")
            else:
                # B4 (external review 2026-10-17): the identity check above
                # proves the BYTES; this proves the TARGET — the patch may
                # only land on the tree the run started from (HEAD ==
                # STANOK_START_COMMIT, porcelain clean). Drift means the
                # apply target is not the tree the verdict was computed
                # against: same downgrade as the identity branch (rc=16
                # ENV-FAIL, summary overwritten via write_env_fail_summary).
                # Nothing is copied or deleted (operator decision 2026-10-17,
                # variant 1): changes.patch stays exactly where it was
                # written — live_dir under LOG_DIR (/tmp/stanok-logs on the
                # host, config.py:83) — temporary by design; the message
                # names the path from the `patch_file` variable itself, so
                # it cannot diverge from the real file.
                drift = _live_tree_drift(cfg)
                if drift is not None:
                    log(f"ERROR: final PASS but {drift} — apply SKIPPED")
                    rc = int(ExitCode.ENV_FAIL)
                    write_env_fail_summary(
                        cfg, label,
                        f"final PASS but {drift} — patch NOT applied; "
                        f"changes.patch retained at {patch_file} "
                        "(temporary, lives under /tmp)")
                else:
                    r = subprocess.run(["git", "apply", patch_file],
                                       cwd=cfg.repo_root,
                                       capture_output=True, text=True)
                    if r.returncode != 0:
                        log(f"ERROR: final PASS but git apply on the live tree "
                            f"failed (rc={r.returncode}): {r.stderr.strip()}")
                        rc = int(ExitCode.ENV_FAIL)
                        write_env_fail_summary(
                            cfg, label,
                            f"final PASS but git apply on the live tree failed "
                            f"(rc={r.returncode}): {r.stderr.strip()}")
        return rc
    except KeyboardInterrupt:
        return run_state.interrupted_rc or 130
    finally:
        # Best-effort cleanup of THIS run's artifacts only: every entry in
        # `created` was created by a successful create (ownership proven).
        # Resources this run never created are NOT touched — a foreign object
        # with a colliding name survives (operator P0 2026-10-11).
        for kind, name in created:
            kube._kubectl("delete", kind, name, "-n", ns, "--ignore-not-found",
                     "--wait=false")
        try:
            os.remove(marker)
        except OSError:
            pass
