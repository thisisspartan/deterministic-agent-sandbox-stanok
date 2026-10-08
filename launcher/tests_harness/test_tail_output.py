"""CC-138: `_tail_output` is a RAW TAIL, not a heuristic.

The audit §1#1 called out the leftover `node_modules/` noise filter: the
docstring directly above it claimed "No pattern heuristics" while the code
dropped lines by substring — a JS-era W10 remainder that could hide a line the
model needs. The filter is deleted; the raw tail is the contract (REVIEW-KISS-
CLI-FIRST §3.3). These tests pin that a `node_modules/` line survives verbatim
and that only the two length guards remain.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_tail_output.py -q
"""
from launcher import verify
from launcher.config import Config

CFG = Config()


def test_node_modules_line_is_not_filtered():
    raw = ("/repo/node_modules/left-pad/index.js:12:1: Error: boom\n"
           "  at left-pad/index.js:12\n"
           "AssertionError: expected 1\n")
    out = verify._tail_output(CFG, raw)
    assert "node_modules/" in out
    assert out == raw.strip()


def test_no_noise_registry_remains():
    # The registry itself is gone — one less policy list to drift.
    assert not hasattr(verify, "NOISE_LINE_PATTERNS")


def test_tail_keeps_the_last_max_test_lines():
    raw = "\n".join(f"line-{i}" for i in range(CFG.max_test_lines + 25))
    out = verify._tail_output(CFG, raw)
    lines = out.splitlines()
    assert lines[0] == "... [25 lines skipped above] ..."
    assert lines[-1] == f"line-{CFG.max_test_lines + 24}"
    # The kept window is exactly max_test_lines payload lines.
    assert len(lines) == CFG.max_test_lines + 1


def test_byte_limit_still_truncates():
    raw = "x" * (CFG.max_test_bytes + 500)
    out = verify._tail_output(CFG, raw)
    assert out.endswith("... [output truncated at the byte limit] ...")
    assert len(out.encode("utf-8")) <= CFG.max_test_bytes + 64
