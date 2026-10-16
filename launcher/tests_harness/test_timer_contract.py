"""Timer contract (red-team review 2026-10-08, item 1; extended by the
deadline contract, external review 2026-10-16).

Pins the DELIBERATE relationship of the timers:
  - the machine's worst case: TURN_TIMEOUT_S * (1 + DEFAULT_RETRIES) = 5400 s;
  - the supervisor's wait cap: WAIT_TIMEOUT_S = 2700 s — SHORTER on purpose:
    at rc=124 the supervisor protocol (CLAUDE.supervisor.md §3) runs
    `status` then `stop` — the cap is a kill-switch, not a mismatch bug.
  - the Job deadline (job_deadline): STRICTLY between the turn timeout and
    the wait cap. Below the turn timeout the Job would SIGKILL the Pod at
    the exact moment the in-Pod turn timer would produce a clean
    TURN-TIMEOUT verdict (the old default 1800 == turn timeout — the
    incident this extension closes); above the cap the supervisor's
    kill-switch would fire before the Job could self-terminate with a
    classifiable DeadlineExceeded.
  - the observation chain (A3, review 2026-10-17): the host's log stream
    (+_STREAM_GRACE_S) and terminal wait (+_TERMINAL_GRACE_S) run in
    sequence AFTER the Job deadline; the whole chain from Job creation
    must stay under the wait cap, else the supervisor's kill-switch
    (rc=124) fires while the host is still legitimately collecting the
    Pod's evidence.
Evidence: no rc=124 in any evidence/summary.json; the longest real run is
far below the cap. A silent drift of either constant (e.g. "fixing" the
mismatch by raising the cap) must fail this test and force an explicit
decision together with the protocol text.
"""
from pathlib import Path

import pytest

from launcher import cli, k8s
from launcher.config import Config

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


def test_job_deadline_sits_between_turn_timeout_and_cap(monkeypatch):
    # Deadline contract (external review 2026-10-16): the Job deadline must
    # outlive the turn timer (else the insurance SIGKILLs the Pod exactly
    # when the clean TURN-TIMEOUT verdict would fire) and stay under the
    # supervisor's wait cap (else the supervisor's kill-switch beats the
    # Job's self-termination with a classifiable DeadlineExceeded).
    monkeypatch.delenv("STANOK_K8S_JOB_DEADLINE_S", raising=False)
    d = k8s.job_deadline(CFG)
    assert d > CFG.turn_timeout_s
    assert d < cli.WAIT_TIMEOUT_S


def test_observation_chain_stays_under_the_cap(monkeypatch):
    # A3 (review 2026-10-17): the host's post-deadline windows run in
    # sequence after the Job deadline (log stream, then terminal wait).
    # The whole chain from Job creation must stay strictly under the
    # supervisor's wait cap: at the cap the supervisor's kill-switch
    # (rc=124, CLAUDE.supervisor.md §4) would fire while the host is
    # still legitimately collecting the Pod's evidence. The exact sum is
    # pinned so that raising any grace forces an explicit decision.
    monkeypatch.delenv("STANOK_K8S_JOB_DEADLINE_S", raising=False)
    chain = (k8s.job_deadline(CFG) + k8s._STREAM_GRACE_S
             + k8s._TERMINAL_GRACE_S)
    assert chain == 2340  # 2100 + 180 + 60 (turn-timeout default already
                          # pinned by the 5400 worst-case test above)
    assert chain < cli.WAIT_TIMEOUT_S


def test_protocol_documents_the_kill_switch():
    if not SUPERVISOR_PROTOCOL.is_file():
        pytest.skip("supervisor protocol not present (bare clone)")
    text = SUPERVISOR_PROTOCOL.read_text(encoding="utf-8")
    assert "45-min cap" in text
    assert "rc=124" in text
    assert "launch.sh stop" in text
