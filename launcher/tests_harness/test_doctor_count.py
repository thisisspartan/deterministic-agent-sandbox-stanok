"""W11 — the doctor check count must never drift from the harness.

The reviewer found prose drift: doctor.sh said "15 checks", test_doctor.py
said "16", README said "16 passed" — three different numbers for the same
suite. Rule: NO file in the repo may state a hardcoded doctor check count;
the count is derived from `pytest --collect-only` (see README Setup).

This test scans the repo for a "<N> checks" / "<N> passed" style claim and
fails if the number does not equal the live collected count. A new test
added to the harness without a prose update can no longer rot silently —
and prose that hardcodes a number fails here instead.

Run: .venv/bin/python -m pytest launcher/tests_harness/test_doctor_count.py -q
"""
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

# Files where a hardcoded count claim would be prose drift. Code files in
# launcher/tests_harness/ are excluded (they ARE the count source); evidence/
# is run output, not prose.
SCAN_DIRS = ("README.md", "hooks", "launcher", "docs", "scripts")
SKIP_DIRS = {"tests_harness", "__pycache__", "evidence"}

# A count claim: a number followed by "checks" or "passed" (doctor context).
CLAIM_RE = re.compile(r"\b(\d{1,3})\s+(?:checks?|passed)\b", re.I)


def _live_count() -> int:
    out = subprocess.run(
        [sys.executable, "-m", "pytest", "launcher/tests_harness",
         "--collect-only", "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=120,
    )
    m = re.search(r"(\d+) tests? collected", out.stdout + out.stderr)
    assert m, f"cannot collect tests: {out.stdout} {out.stderr}"
    return int(m.group(1))


def test_no_hardcoded_doctor_count_drift():
    live = _live_count()
    offenders = []
    for d in SCAN_DIRS:
        base = REPO_ROOT / d
        if base.is_file():
            files = [base]
        elif base.is_dir():
            files = [
                f for f in base.rglob("*")
                if f.is_file()
                and not any(part in SKIP_DIRS for part in f.parts)
                and f.suffix in {".md", ".sh", ".py", ".txt"}
            ]
        else:
            continue
        for f in files:
            try:
                text = f.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for m in CLAIM_RE.finditer(text):
                n = int(m.group(1))
                if n != live:
                    line = text[:m.start()].count("\n") + 1
                    offenders.append(f"{f.relative_to(REPO_ROOT)}:{line}: "
                                     f"claims {n}, live count is {live}")
    assert not offenders, "doctor count drift:\n" + "\n".join(offenders)
