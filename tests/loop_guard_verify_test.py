"""Loop-guard hook verification (TASK-STANOK-CC-164).

A PreToolUse(Bash) loop-guard hook counts literal repetitions of each Bash
command per session and DENIES the 10th identical call (exit 2, Russian
stderr message fed to the model). This ticket verifies that the hook fires
in a real machine run: the report ``docs/loop-guard-verify.md`` must exist
and must record the exact deny message plus the number of the series call
that was denied.
"""
import re
from pathlib import Path

REPORT = Path(__file__).resolve().parent.parent / "docs" / "loop-guard-verify.md"
DENY_SUBSTRING = "Эта команда уже выполнялась"


def test_report_exists():
    assert REPORT.is_file(), f"report missing: {REPORT}"


def test_report_records_deny():
    text = REPORT.read_text(encoding="utf-8")
    assert DENY_SUBSTRING in text, (
        f"deny message {DENY_SUBSTRING!r} not found in {REPORT}"
    )
    m = re.search(r"^denied_call: (\d+)$", text, re.MULTILINE)
    assert m is not None, f"no 'denied_call: <N>' line in {REPORT}"
    n = int(m.group(1))
    assert 1 <= n <= 10, f"denied_call {n} outside 1..10"
