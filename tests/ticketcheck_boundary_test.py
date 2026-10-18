"""ticketcheck_boundary_test — the boundary acceptance for CC-296
(src/ticketcheck.py).

Host-authored trusted check (the agent cannot author its own boundary accept;
policy CC-286). The boundary is REAL: the tool runs as a separate process
(`sys.executable -m src.ticketcheck`) reading frozen tracked fixture tickets
under tests/fixtures/tickets/ and returning real exit codes — not an
in-process monkeypatch. Do not edit or delete from a ticket: this file is the
wave's acceptance boundary. Expected output strings are signed in
tests/fixtures/tickets/README.md.

Calibration record (host, 2026-10-18, before first use; etalon lived only
in /tmp/ticketcheck-ref*, transient copy in src/ per run, removed after —
FIRE-incident rule: the authoritative copy never lives only in a protected
zone):
  - RED on the live tree without src/ticketcheck.py: 6 failed, rc=1,
    signature "/usr/bin/python3: No module named src.ticketcheck".
  - GREEN on the /tmp/ticketcheck-ref reference: 6 passed in 0.23s.
  - RED on /tmp/ticketcheck-ref-bad-name (name rule disabled): exactly
    test_bad_test_name_rejected failed (1 failed, 5 passed).
  - RED on /tmp/ticketcheck-ref-bad-location: exactly
    test_bad_test_location_rejected failed.
  - RED on /tmp/ticketcheck-ref-bad-dup: exactly
    test_duplicate_ticket_number_rejected failed.
  - After every run src/ left clean (git status --porcelain -- src/ empty).
"""

import os
import subprocess
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_FIX = "tests/fixtures/tickets"


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "src.ticketcheck", *args],
        cwd=_REPO, capture_output=True, text=True, timeout=30)


def _check_fixtures():
    for name in ("TASK-STANOK-CC-900.md", "TASK-STANOK-CC-901.md",
                 "TASK-STANOK-CC-902.md", "TASK-STANOK-CC-903.md",
                 "TASK-STANOK-CC-903-dup.md", "TASK-STANOK-CC-904.md"):
        assert os.path.isfile(os.path.join(_REPO, _FIX, name)), (
            f"fixture {name} missing — frozen samples are tracked, they must "
            "be present before the boundary test runs")


def test_valid_ticket_exits_clean():
    """Good sample: valid header → rc 0, no output (non-vacuity is provided
    by the bad samples below)."""
    _check_fixtures()
    r = _run(f"{_FIX}/TASK-STANOK-CC-900.md")
    assert r.returncode == 0, f"rc={r.returncode} stderr={r.stderr}"
    assert r.stdout == ""
    assert r.stderr == ""


def test_bad_test_name_rejected():
    _check_fixtures()
    r = _run(f"{_FIX}/TASK-STANOK-CC-901.md")
    assert r.returncode == 1, f"rc={r.returncode}"
    assert r.stdout == (
        "VIOLATION UNCLAIMED-TEST-NAME: "
        f"{_FIX}/TASK-STANOK-CC-901.md: test path 'tests/test_preflight.py':"
        " basename 'test_preflight.py' matches no stack test_glob\n"), r.stdout
    assert r.stderr == ""


def test_bad_test_location_rejected():
    _check_fixtures()
    r = _run(f"{_FIX}/TASK-STANOK-CC-902.md")
    assert r.returncode == 1, f"rc={r.returncode}"
    assert r.stdout == (
        "VIOLATION UNCLAIMED-TEST-PATH: "
        f"{_FIX}/TASK-STANOK-CC-902.md: test path "
        "'src/preflight_mod_test.py': must live under tests/\n"), r.stdout
    assert r.stderr == ""


def test_duplicate_ticket_number_rejected():
    _check_fixtures()
    r = _run(f"{_FIX}/TASK-STANOK-CC-903.md", f"{_FIX}/TASK-STANOK-CC-903-dup.md")
    assert r.returncode == 1, f"rc={r.returncode}"
    assert r.stdout == (
        "VIOLATION DUPLICATE-TICKET-NUMBER: "
        f"{_FIX}/TASK-STANOK-CC-903.md: ticket number 903 also claimed by "
        f"{_FIX}/TASK-STANOK-CC-903-dup.md\n"
        "VIOLATION DUPLICATE-TICKET-NUMBER: "
        f"{_FIX}/TASK-STANOK-CC-903-dup.md: ticket number 903 also claimed by "
        f"{_FIX}/TASK-STANOK-CC-903.md\n"), r.stdout
    assert r.stderr == ""


def test_malformed_header_is_parse_error():
    _check_fixtures()
    r = _run(f"{_FIX}/TASK-STANOK-CC-904.md")
    assert r.returncode == 2, f"rc={r.returncode} stdout={r.stdout}"
    assert r.stdout == ""
    assert r.stderr.startswith(
        f"PARSE: {_FIX}/TASK-STANOK-CC-904.md: invalid header:"), r.stderr


def test_missing_file_is_parse_error():
    r = _run(f"{_FIX}/TASK-STANOK-CC-999.md")
    assert r.returncode == 2, f"rc={r.returncode}"
    assert r.stdout == ""
    assert r.stderr.startswith(
        f"PARSE: {_FIX}/TASK-STANOK-CC-999.md: unreadable:"), r.stderr
