"""CC-261: the runtime-contract doc and the transport invariants it depends on.

The repo root is derived from this file's own location: tests/ is one level
below the root, so parents[1] is the root.
"""

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / "docs" / "runtime-contract.md"
RUN_SH = REPO_ROOT / "scripts" / "run.sh"
PY_MANIFEST = REPO_ROOT / "scripts" / "stacks" / "py.toml"

MAX_LINES = 30


def test_runtime_contract_doc_exists():
    assert DOC.is_file(), f"missing docs file: {DOC}"


def test_runtime_contract_doc_is_utf8_and_short():
    raw = DOC.read_bytes()
    text = raw.decode("utf-8")  # raises UnicodeDecodeError if not valid UTF-8
    lines = text.splitlines()
    assert lines, f"{DOC} is empty"
    assert len(lines) <= MAX_LINES, (
        f"{DOC} has {len(lines)} lines, contract allows at most {MAX_LINES}"
    )


def test_runtime_contract_doc_names_all_four_contract_points():
    text = DOC.read_text(encoding="utf-8")
    for needle in ("ConfigMap", "NetworkPolicy", "rc=16", "stacks"):
        assert needle in text, f"{DOC} does not mention the contract point {needle!r}"


def test_entrypoint_travels_with_the_tree():
    assert RUN_SH.is_file(), f"missing entrypoint: {RUN_SH}"
    assert os.access(RUN_SH, os.X_OK), f"entrypoint is not executable: {RUN_SH}"


def test_stack_registry_travels_with_the_tree():
    assert PY_MANIFEST.is_file(), (
        f"missing stack manifest {PY_MANIFEST}: the registry, not the ticket, "
        "picks the test framework"
    )
