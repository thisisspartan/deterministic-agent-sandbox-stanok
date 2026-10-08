"""CC-207: the launcher side of the circuit breaker — pure-function pins.

The e2e proof is the first real run that trips the breaker (ticket acceptance
#3); inventing a session stub harness would be a new mechanism without an
incident. What is pinned here are the two pure helpers the session code uses:

  _read_loop_trap(marker_path) -> dict | None
      missing / unreadable / non-JSON / directory -> None (best-effort read,
      never raises — the turn must not die on a broken marker).
  _loop_trap_verdict(job, loop_trap) -> int
      the verdict branch on a synthetic job dict, exactly the
      test_contract_lock_forced_fail_* pattern: probe_result "LOOP-TRAP",
      verifier FAIL, error string, rc=1. No fix prompt, no retries — a retry
      re-enters the same loop (the marker is cumulative for the session).
"""
import json

from launcher import session


MARKER = {"tool": "Read", "hash": "a" * 64, "n": 5, "ts": "2026-10-07T12:00:00"}


# --- _read_loop_trap ---------------------------------------------------------------

def test_read_loop_trap_missing(tmp_path):
    assert session._read_loop_trap(tmp_path / "nope.json") is None


def test_read_loop_trap_unreadable(tmp_path):
    p = tmp_path / "loop-trap.json"
    p.write_text("not json", encoding="utf-8")
    assert session._read_loop_trap(p) is None


def test_read_loop_trap_directory_is_none(tmp_path):
    p = tmp_path / "loop-trap.json"
    p.mkdir()
    assert session._read_loop_trap(p) is None


def test_read_loop_trap_valid(tmp_path):
    p = tmp_path / "loop-trap.json"
    p.write_text(json.dumps(MARKER), encoding="utf-8")
    assert session._read_loop_trap(p) == MARKER


# --- _loop_trap_verdict ------------------------------------------------------------

def test_loop_trap_verdict_sets_defect_fields():
    job: dict = {}
    rc = session._loop_trap_verdict(job, MARKER)
    assert rc == 1
    assert job["probe_result"] == "LOOP-TRAP"
    assert job["loop_trap"] == MARKER
    assert job["verifier"] == "FAIL"
    assert job["error"] == (
        "LOOP-TRAP: Read repeated 5x consecutively — "
        "session terminated by the circuit breaker"
    )
