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

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_k8s_payload.py -q
"""
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
