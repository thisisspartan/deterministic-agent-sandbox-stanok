"""payload — the transport/codec cluster of the K8s evidence channel
(#316, 2026-10-22, host-side — precedent CC-266; moved verbatim from
launcher/k8s.py, strict from birth).

Single home: k8s.py holds no def, no constant and no re-export of these
names; the host orchestration calls them as payload._X / payload.CONSTANT —
a test stub on a name here intercepts every call site (guard:
tests_harness/test_payload_facade.py).

Why a separate module (the layer finding of the 2026-10-22 pre-flight review,
adopted as #316): pod_runner.py runs INSIDE the Pod and needs exactly four
pure-codec helpers (begin_marker / build_payload / end_marker /
rewrite_tracing_endpoint); importing them through k8s pulled the whole
1159-line host orchestrator — kubectl, Job construction, the patch gate —
into the Pod runtime. This module is pure stdlib on purpose: it imports
nothing from launcher and stays Pod-importable. The host-side counterpart
that reads the payload (k8s.host_launch_k8s, apply_patch_scratch) imports it
as any other leaf module.

The contract of the channel, unchanged from the k8s era (SPEC-STANOK-K8S-
RUNTIME-2026-10-10): the tree travels as `git archive HEAD | gzip | base64`
through a ConfigMap (TRANSPORT_MAX_B64 fail-closed before any kubectl call);
the Pod returns its evidence as ONE base64 gzip-tar block between nonce
markers; the host accepts EXACTLY ONE nonce-matching block (zero/two/
unclosed = aborted, never a verdict); member names must be flat; the
decompressed stream is bounded in-stream (R4/#312).
"""

import base64
import gzip
import io
import json
import os
import re
import subprocess
import tarfile
import uuid

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


def build_payload(files: dict[str, bytes]) -> str:
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


def extract_payload(text: str, nonce: str) -> "dict[str, bytes] | None":
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
    files: dict[str, bytes] = {}
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
