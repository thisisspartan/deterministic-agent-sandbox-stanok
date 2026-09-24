"""CC-138: `_extract_smart_diff` is a RAW TAIL, not a heuristic.

The audit §1#1 called out the leftover `node_modules/` noise filter: the
docstring directly above it claimed "No pattern heuristics" while the code
dropped lines by substring — a JS-era W10 remainder that could hide a line the
model needs. The filter is deleted; the raw tail is the contract (REVIEW-KISS-
CLI-FIRST §3.3). These tests pin that a `node_modules/` line survives verbatim
and that only the two length guards remain.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_smart_diff_tail.py -q
"""
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402


def test_node_modules_line_is_not_filtered():
    raw = ("/repo/node_modules/left-pad/index.js:12:1: Error: boom\n"
           "  at left-pad/index.js:12\n"
           "AssertionError: expected 1\n")
    out = stanok._extract_smart_diff(raw)
    assert "node_modules/" in out
    assert out == raw.strip()


def test_no_noise_registry_remains():
    # The registry itself is gone — one less policy list to drift.
    assert not hasattr(stanok, "NOISE_LINE_PATTERNS")


def test_tail_keeps_the_last_max_test_lines():
    raw = "\n".join(f"line-{i}" for i in range(stanok.MAX_TEST_LINES + 25))
    out = stanok._extract_smart_diff(raw)
    lines = out.splitlines()
    assert lines[0] == "... [25 lines skipped above] ..."
    assert lines[-1] == f"line-{stanok.MAX_TEST_LINES + 24}"
    # The kept window is exactly MAX_TEST_LINES payload lines.
    assert len(lines) == stanok.MAX_TEST_LINES + 1


def test_byte_limit_still_truncates():
    raw = "x" * (stanok.MAX_TEST_BYTES + 500)
    out = stanok._extract_smart_diff(raw)
    assert out.endswith("... [output truncated at the byte limit] ...")
    assert len(out.encode("utf-8")) <= stanok.MAX_TEST_BYTES + 64
