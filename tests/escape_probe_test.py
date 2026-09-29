"""Reference tests for the container-escape probe report (TASK-STANOK-CC-178).

Structural contract for ``docs/container-escape-probe.md``:
- the report file exists;
- it contains the required section headings:
  ``## Verdict summary``, ``## A. Filesystem writes``,
  ``## B. Filesystem reads``, ``## C. Network``,
  ``## D. Process/namespace/privileges``, ``## Findings``;
- it carries at least 25 probe rows — table rows (lines starting with
  ``| ``) that contain one of the four verdict words;
- the ``## Verdict summary`` section mentions all four verdict words
  (ESCAPE, LEAK, BY-DESIGN, BLOCKED).
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
REPORT = REPO_ROOT / "docs" / "container-escape-probe.md"

REQUIRED_HEADINGS = (
    "## Verdict summary",
    "## A. Filesystem writes",
    "## B. Filesystem reads",
    "## C. Network",
    "## D. Process/namespace/privileges",
    "## Findings",
)

VERDICTS = ("ESCAPE", "LEAK", "BY-DESIGN", "BLOCKED")


def _text() -> str:
    return REPORT.read_text(encoding="utf-8")


def test_report_exists():
    assert REPORT.is_file(), f"missing report: {REPORT}"


def test_required_headings_present():
    text = _text()
    for heading in REQUIRED_HEADINGS:
        pattern = rf"^{re.escape(heading)}\s*$"
        assert re.search(pattern, text, re.MULTILINE), (
            f"missing heading: {heading!r}"
        )


def test_at_least_25_probe_rows_with_verdicts():
    text = _text()
    rows = [
        line
        for line in text.splitlines()
        if line.startswith("| ") and any(v in line for v in VERDICTS)
    ]
    assert len(rows) >= 25, f"expected >= 25 probe rows, got {len(rows)}"


def test_verdict_summary_mentions_all_verdicts():
    text = _text()
    match = re.search(
        r"^## Verdict summary\s*$(.*?)(?=^## |\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    assert match, "missing '## Verdict summary' section"
    section = match.group(1)
    for verdict in VERDICTS:
        assert verdict in section, (
            f"Verdict summary does not mention verdict word: {verdict}"
        )
