"""P1 (SPEC-STANOK-K8S-RUNTIME-2026-10-10 §5) — the payload protocol.

The Pod emits its evidence as ONE base64 gzip-tar block between
`__STANOK_EVIDENCE_BEGIN_<NONCE>__` / `__STANOK_EVIDENCE_END_<NONCE>__`
markers on stdout; NONCE is host-generated per run (uuid4) and passed to the
Pod. The host accepts EXACTLY ONE nonce-matching block — zero, two, or an
unclosed block means the run is treated as aborted (status `missing`), never
a verdict. Tests:
  1  build_payload/extract_payload round-trip (summary.json + changes.patch)
  2  a block with a foreign nonce is not accepted
  3  no markers -> None
  4  two nonce-matching blocks -> None (exactly-one rule)
  5  an unclosed block -> None
  6  decompressed-size cap: AT the cap accepted, one byte over -> None (R4, #311)
  7  a payload BOMB (decompressed total > cap) fails closed with a bounded
     tracemalloc peak — BEFORE materialization (#312 pair, B1a)
  8  header FLOOD: a headers-only stream over cap+1MiB -> None although its
     file-data total is ~0 (#313 pair); companion: in-budget structure accepted
  9  duplicate member names accumulate toward the per-member budget (#313 pair;
     pre-#312 the dict sum deduplicated them); companion: in-budget duplicate
     accepted, last-wins

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_payload.py -q
"""
import base64
import gzip
import io
import tarfile
import tracemalloc

from launcher import k8s


def test_roundtrip():
    files = {"summary.json": b'{"rc": 0}', "changes.patch": b"diff --git x\n"}
    blob = k8s.build_payload(files)
    text = ("noise\n" + k8s.begin_marker("N1") + "\n" + blob + "\n"
            + k8s.end_marker("N1") + "\nmore")
    assert k8s.extract_payload(text, "N1") == files


def test_foreign_nonce_rejected():
    blob = k8s.build_payload({"summary.json": b"x"})
    text = k8s.begin_marker("other") + blob + k8s.end_marker("other")
    assert k8s.extract_payload(text, "N1") is None


def test_no_markers_rejected():
    assert k8s.extract_payload("nothing here", "N1") is None


def test_two_blocks_rejected():
    blob = k8s.build_payload({"a": b"1"})
    text = (k8s.begin_marker("N1") + blob + k8s.end_marker("N1")
            + k8s.begin_marker("N1") + blob + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") is None


def test_unclosed_block_rejected():
    blob = k8s.build_payload({"a": b"1"})
    assert k8s.extract_payload(k8s.begin_marker("N1") + blob, "N1") is None


def test_member_names_are_flat_bare_filenames():
    # Operator guard 2026-10-20 (external-review finding: the Pod is an
    # external boundary and extract_payload returns its member names verbatim;
    # k8s.py writes os.path.join(live_dir, name) — a directory component or a
    # leading '/' would escape live_dir). Guard: a name must satisfy
    # os.path.basename(name) == name and not start with '/' or '..';
    # a violating block fails closed (None), like any malformed block.
    # pod_runner.py:154-161 emits only flat names — this guard never rejects
    # a real payload.
    # "" and "." also collapse os.path.join(live_dir, name) to live_dir
    # itself (B1a review 2026-10-20 finding: IsADirectoryError crash at the
    # write site instead of the clean abort) — closed in the same guard.
    for bad in ("../escape.txt", "sub/summary.json", "/abs/summary.json",
                "..leadingdot", "", "."):
        blob = k8s.build_payload({"summary.json": b"{}", bad: b"1"})
        text = (k8s.begin_marker("N1") + "\n" + blob + "\n"
                + k8s.end_marker("N1"))
        assert k8s.extract_payload(text, "N1") is None, bad
    # companion positive: flat names (the real producer's set) still pass
    good = {"summary.json": b"{}", "changes.patch": b"d", "internal_rc.txt": b"0\n",
            "launcher.stdout.log": b"", "failures.log": b""}
    text = (k8s.begin_marker("N1") + "\n" + k8s.build_payload(good) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") == good


def test_decompressed_size_cap():
    # R4 pair test (#311, operator order 2026-10-21): extraction is capped at
    # k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES; the limit itself is pinned from the
    # operator's spec (64MiB), the constant is the single source. A total AT
    # the limit is accepted ("превышает" is strict >); a total one byte over
    # fails closed — None, like every malformed block. The block payload
    # stays small because b"\0" compresses: the cap measures the DECOMPRESSED
    # total the host must not RETAIN unbounded (B1a 2026-10-21: extraction
    # materializes before the check — peak is not bounded; #312 candidate).
    # A real payload (pod_runner's five flat files) is orders of magnitude
    # below 64MiB — this guard bounds only pathological/adversarial blocks.
    assert k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES == 64 * 1024 * 1024
    limit = k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES
    at_limit = {"summary.json": b"{}{}", "big.bin": b"\0" * (limit - 4)}
    text = (k8s.begin_marker("N1") + "\n" + k8s.build_payload(at_limit) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") == at_limit
    over = {"big.bin": b"\0" * limit, "one.bin": b"1"}  # total == limit + 1
    text = (k8s.begin_marker("N1") + "\n" + k8s.build_payload(over) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") is None


class _NulStream:
    """#312 pair helper: a read()-only source of `size` NULs for
    tarfile.addfile — the fixture never holds more than one chunk."""

    def __init__(self, size: int):
        self._left = size

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            n = self._left
        n = min(n, self._left)
        self._left -= n
        return b"\0" * n


def _bomb_block(member_bytes: int) -> str:
    """#312 pair helper: ONE flat member `big.bin` of `member_bytes` NULs as
    a base64 gzip-tar block, built by STREAMING the member data through the
    gzipper (tar mode "w|", no seek) — the fixture itself never holds the
    bomb, so the tracemalloc peak in the bomb test measures extract_payload,
    not the test. build_payload is unusable here: it would materialize the
    full member in the test process first."""
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        with tarfile.open(fileobj=g, mode="w|") as tf:
            info = tarfile.TarInfo("big.bin")
            info.size = member_bytes
            tf.addfile(info, _NulStream(member_bytes))
    return base64.b64encode(gz.getvalue()).decode("ascii")


def test_payload_bomb_fails_closed_before_materialization():
    """#312 pair test (B1a 2026-10-21, host-side — precedent CC-266): a gzip
    bomb — ONE nonce-matching block whose single member claims TWICE the cap
    of NULs, compressing to a few hundred KB — must fail closed (None)
    WITHOUT materializing: the tracemalloc peak of the call stays under two
    caps. Calibration contract: on the pre-#312 code this goes RED — the
    bomb decompresses in full (raw + member copy, peak ~4x cap) before the
    post-hoc sum check rejects it; that unbounded peak is the B1a finding.
    On the #312 code the budget aborts the gunzip mid-stream (peak ~ cap +
    stream overhead). The block is built by streaming (_bomb_block), so the
    fixture holds neither the bomb nor its tar."""
    limit = k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES
    text = (k8s.begin_marker("N1") + "\n" + _bomb_block(limit * 2) + "\n"
            + k8s.end_marker("N1"))
    tracemalloc.start()
    tracemalloc.reset_peak()  # baseline: only `text` (+ the small fixture) is alive
    try:
        assert k8s.extract_payload(text, "N1") is None
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 2 * limit, (
        f"tracemalloc peak {peak} >= 2x cap ({2 * limit}): the bomb was "
        f"materialized before rejection — B1a (the #312 budget must abort "
        f"decompression in-stream)")


def _header_block(member_count: int) -> str:
    """#313 pair helper: `member_count` zero-size flat members (h000000.bin …)
    as a base64 gzip-tar block, streamed through the gzipper (tar mode "w|")
    like _bomb_block — the fixture holds neither the tar nor the header
    stream; the block is pure tar STRUCTURE, its file-data total is 0."""
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        with tarfile.open(fileobj=g, mode="w|") as tf:
            for i in range(member_count):
                info = tarfile.TarInfo("h%06d.bin" % i)
                info.size = 0
                tf.addfile(info)
    return base64.b64encode(gz.getvalue()).decode("ascii")


def test_header_flood_rejected():
    """#313 pair test (host-side): the #312 header-flood tightening — until
    now documented only in the k8s.py:94-98 comment — gets its test.
    140 000 zero-size members are 140 000 x 512-byte headers (POSIX tar
    block size) ≈ 71.7 MiB of pure STRUCTURE with a file-data total of
    ZERO: over the in-stream budget (PAYLOAD_MAX + PAYLOAD_TAR_OVERHEAD)
    the bounded gunzip aborts -> None, fail-closed like every malformed
    shape. Calibration contract: RED on the pre-#312 code (full
    decompression, post-hoc sum of file bytes ≈ 0 -> accepted).
    Provenance: budget = the two pinned k8s constants (k8s.py:92/:99; the
    1 MiB headroom is the #312 patch comment's rationale — characterization,
    not an external spec); 512 is the tar block size; the member count is
    chosen so the header stream crosses the budget under the 512 B/member
    floor — the structural precondition is asserted, not assumed."""
    budget = k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES + k8s.PAYLOAD_TAR_OVERHEAD_BYTES
    members = 140_000
    assert members * 512 > budget, "fixture must cross the stream budget"
    text = (k8s.begin_marker("N1") + "\n" + _header_block(members) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") is None


def test_in_budget_structure_accepted():
    """#313 companion: the same zero-size-member shape UNDER the budget —
    30 000 members cross the budget only at the 512 B/member floor
    (15.4 MiB; even a 2048 B/member worst case stays under 68.2 MiB) —
    is accepted with a ZERO file-data total: the cap bounds the stream,
    legal structure inside it is not a defect. Green on pre-#312 too
    (companion semantics, unchanged)."""
    members = 30_000
    text = (k8s.begin_marker("N1") + "\n" + _header_block(members) + "\n"
            + k8s.end_marker("N1"))
    files = k8s.extract_payload(text, "N1")
    assert files is not None and len(files) == members
    assert sum(len(v) for v in files.values()) == 0


def _dup_block(first: int, second: int) -> str:
    """#313 pair helper: TWO members named "big.bin" (sizes `first`, then
    `second`, streamed via _NulStream) in one base64 gzip-tar block. Both
    names are flat — the member-name guard accepts this block; only the
    budget can reject it."""
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0) as g:
        with tarfile.open(fileobj=g, mode="w|") as tf:
            for size in (first, second):
                info = tarfile.TarInfo("big.bin")
                info.size = size
                tf.addfile(info, _NulStream(size))
    return base64.b64encode(gz.getvalue()).decode("ascii")


def test_duplicate_member_names_accumulate_toward_the_cap():
    """#313 pair test (host-side): the #312 duplicate-name tightening —
    until now documented only in the B1a review note (k8s.py:249: `total`
    accumulates duplicates; pre-#312 the post-hoc sum(files.values())
    deduplicated them) — gets its test. Two members named "big.bin",
    40 MiB then 26 000 000 bytes: the per-member budget (k8s.py:244-247)
    leaves the second member remaining = 64 MiB - 40 MiB = 25 165 824, its
    read overshoots by one byte -> None, although the DEDUPLICATED (last-
    wins) total of 26 000 000 fits the cap. Calibration contract: RED on
    the pre-#312 code (accepted). Fixture sizes pinned so the RAW stream
    (≈67.95 MiB incl. headers/padding) stays INSIDE the gunzip budget
    (68.2 MiB) — the rejection must come from the member budget, not the
    stream budget; the boundary values are computed from the pinned
    constants, not copied from production behaviour."""
    cap = k8s.PAYLOAD_MAX_DECOMPRESSED_BYTES
    first, second = 40 * 1024 * 1024, 26_000_000
    assert first + second > cap, "fixture must cross the member budget"
    assert first + second < cap + k8s.PAYLOAD_TAR_OVERHEAD_BYTES, (
        "fixture must stay inside the gunzip budget")
    text = (k8s.begin_marker("N1") + "\n" + _dup_block(first, second) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") is None


def test_duplicate_names_in_budget_accepted_last_wins():
    """#313 companion: two 30 MiB members named "big.bin" — total 60 MiB,
    inside the cap, both members inside their remaining budgets — accepted,
    and the dict keeps the LAST member's bytes. `last-wins` is tarfile's
    documented duplicate semantics preserved through #312 — a
    characterization assertion (pinned so a future tightening of
    duplicates into an error would not pass unnoticed), not a contract.
    Green on pre-#312 too."""
    size = 30 * 1024 * 1024
    text = (k8s.begin_marker("N1") + "\n" + _dup_block(size, size) + "\n"
            + k8s.end_marker("N1"))
    assert k8s.extract_payload(text, "N1") == {"big.bin": b"\0" * size}
