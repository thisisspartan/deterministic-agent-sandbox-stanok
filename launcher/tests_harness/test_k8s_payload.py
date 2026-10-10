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
