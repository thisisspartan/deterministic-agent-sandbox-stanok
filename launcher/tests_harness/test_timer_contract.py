"""Timer contract (red-team review 2026-10-08, item 1).

Pins the DELIBERATE relationship of the two timers:
  - the machine's worst case: TURN_TIMEOUT_S * (1 + DEFAULT_RETRIES) = 5400 s;
  - the supervisor's wait cap: WAIT_TIMEOUT_S = 2700 s — SHORTER on purpose:
    at rc=124 the supervisor protocol (CLAUDE.supervisor.md §3) runs
    `status` then `stop` — the cap is a kill-switch, not a mismatch bug.
Evidence: no rc=124 in any evidence/summary.json; the longest real run is
far below the cap. A silent drift of either constant (e.g. "fixing" the
mismatch by raising the cap) must fail this test and force an explicit
decision together with the protocol text.
"""
import sys
from pathlib import Path

import pytest

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import cli  # noqa: E402
from config import Config  # noqa: E402

# from_env() replicates the former hub env logic (STANOK_REPO included), so
# the protocol path and the timer values resolve exactly as before C.
CFG = Config.from_env()
SUPERVISOR_PROTOCOL = Path(CFG.repo_root).parent / "CLAUDE.supervisor.md"


def test_wait_cap_is_2700():
    assert cli.WAIT_TIMEOUT_S == 2700


def test_machine_worst_case_5400_and_cap_shorter_on_purpose():
    worst = CFG.turn_timeout_s * (1 + CFG.default_retries)
    assert worst == 5400.0
    # Deliberate kill-switch. Raising the cap = editing the protocol AND
    # this test in the same change — never one without the other.
    assert cli.WAIT_TIMEOUT_S < worst


def test_protocol_documents_the_kill_switch():
    if not SUPERVISOR_PROTOCOL.is_file():
        pytest.skip("supervisor protocol not present (bare clone)")
    text = SUPERVISOR_PROTOCOL.read_text(encoding="utf-8")
    assert "45-min cap" in text
    assert "rc=124" in text
    assert "launch.sh stop" in text
