"""Verifier hook timeout: partial output + TIMEOUT-ABORT classification.

When `run.sh test` hangs past _HOOK_TEST_TIMEOUT_S, the hook kills it and
must surface what the test printed before the hang (the old code discarded
the partial output: rc, out = 124, b"").

A hung test (rc=124) is NOT a red test: the hook must classify it as
TIMEOUT-ABORT and point the model at the hang (infinite loop / blocking
call), never as "RED CONFIRMED / Implement src/ to make it GREEN" — that
wording is a retry-loop DoS (the model iterates on src/, the test hangs
again, the hook fires again).

The hanging test is a JS test: node --test passes a top-level console.log
through to stdout (as a TAP comment), while pytest captures module-level
and per-test output into its own buffer — a py test's output would never
reach run.sh's pipe. The test hangs on a pending promise backed by a
ref'd timer, which --test-force-exit does not cut (it only fires after
the tests have COMPLETED).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_verifier_hook.py -q
"""
import asyncio
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402

from conftest import repo, write

MARKER = "PARTIAL-OUTPUT-MARKER"
HANG_JS = (
    f'console.log("{MARKER}");\n'
    "const test = require('node:test');\n"
    "test('hang', () => new Promise((resolve) => setTimeout(resolve, 8000)));\n"
)


def test_hook_timeout_includes_partial_output(repo, monkeypatch):
    write(repo / "tests" / "hang.test.js", HANG_JS)
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    monkeypatch.setattr(stanok, "_HOOK_TEST_TIMEOUT_S", 3)
    result = asyncio.run(stanok._verifier_hook(
        {"tool_input": {"file_path": str(repo / "tests" / "hang.test.js")}},
        "test-hook-id", None,
    ))
    ctx = result["hookSpecificOutput"]["additionalContext"]
    assert "rc=124" in ctx
    assert MARKER in ctx
    # A hang is classified as TIMEOUT-ABORT, never as a red test.
    assert "TIMEOUT-ABORT" in ctx
    assert "RED CONFIRMED" not in ctx
