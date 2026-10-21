"""CC-207: the launcher side of the circuit breaker — pure-function pins +
the trap-path telemetry pin (CC-237).

  _read_loop_trap(marker_path) -> dict | None
      missing / unreadable / non-JSON / directory -> None (best-effort read,
      never raises — the turn must not die on a broken marker).
  _loop_trap_verdict(job, loop_trap) -> int
      the verdict branch on a synthetic job dict, exactly the
      test_contract_lock_forced_fail_* pattern: probe_result "LOOP-TRAP",
      verifier FAIL, error string, rc=1. No fix prompt, no retries — a retry
      re-enters the same loop (the marker is cumulative for the session).

CC-237 added the session-level pin (the incident that justifies it: cc236 —
the real LOOP-TRAP run published bash_total=0/bash_ok=0 and tokens 0 because
_loop_trap_verdict returned BEFORE _record_turn_telemetry; the operator's
required proof: a trap run shows bash_total=5, bash_ok=4). A fake
ClaudeSDKClient drives run_continuous_session: 4 Bash calls with ok results,
the 5th identical call writes the marker (the hook's channel), the mid-turn
breaker ends the turn — the telemetry must be recorded BEFORE the trap
branch, and the published summary (schema v2) must carry the typed
loop_trap triple and the real tool_activity.
"""
import asyncio
import json
import types

import pytest

# R3 (#310, Z.ai review 2026-10-20 finding F3, operator order 2026-10-21):
# the session code paths exercised here reach claude_agent_sdk at call time;
# on a runner without the SDK this file must skip, not fail (guard pattern:
# test_compaction_telemetry.py:27).
pytest.importorskip("claude_agent_sdk")

from launcher import session, summary


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


# --- CC-237: the trap path records telemetry BEFORE the verdict ------------------
# Incident cc236: the real LOOP-TRAP run published tool_activity 0/0 and
# tokens 0 — _loop_trap_verdict returned before _record_turn_telemetry. The
# operator's required proof: a trap run shows bash_total=5, bash_ok=4.

TRAP_MARKER = {"tool": "Bash", "hash": "b" * 64, "n": 5,
               "ts": "2026-10-11T12:00:00"}


class _Cfg:
    """Minimal cfg for run_continuous_session with _agent_options patched out:
    repo_root (no .claude/settings.json -> the hook self-check passes) and
    turn_timeout_s."""

    def __init__(self, repo_root):
        self.repo_root = str(repo_root)
        self.turn_timeout_s = 30
        self.model = "test-model"


def test_trap_path_records_telemetry_before_verdict(tmp_path, monkeypatch):
    from claude_agent_sdk import (AssistantMessage, ToolResultBlock,
                                  ToolUseBlock, UserMessage)
    import claude_agent_sdk

    live = tmp_path / "live"
    live.mkdir()
    run_state = types.SimpleNamespace(live_dir=str(live))
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))  # Bash self-check
    monkeypatch.setattr(session, "_agent_options", lambda cfg, rs: None)

    clients = []

    class _FakeClient:
        def __init__(self, options=None):
            clients.append(self)
            self.interrupted = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def query(self, prompt):
            pass

        async def interrupt(self):
            self.interrupted = True

        async def receive_response(self):
            # 4 identical Bash calls, each with an ok result
            for i in range(1, 5):
                yield AssistantMessage(
                    content=[ToolUseBlock(id=f"b{i}", name="Bash",
                                          input={"command": "true"})],
                    model="m")
                yield UserMessage(content=[ToolResultBlock(
                    tool_use_id=f"b{i}", content="ok", is_error=False)])
            # the 5th identical call: the hook writes the marker (its channel
            # is live_dir/loop-trap.json), then the mid-turn breaker ends it
            (live / "loop-trap.json").write_text(json.dumps(TRAP_MARKER),
                                                 encoding="utf-8")
            yield AssistantMessage(
                content=[ToolUseBlock(id="b5", name="Bash",
                                      input={"command": "true"})],
                model="m")

    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", _FakeClient)

    job = {"label": "trap-telemetry"}
    rc = asyncio.run(session.run_continuous_session(
        _Cfg(tmp_path), run_state, job, "prompt", 0, None))

    # the trap verdict (CC-207) ...
    assert rc == 1
    assert job["probe_result"] == "LOOP-TRAP"
    assert job["verifier"] == "FAIL"
    assert job["turns"] == 1
    assert clients and clients[0].interrupted  # the session was interrupted
    # ... but the trap turn's telemetry was recorded FIRST (CC-237):
    # 5 Bash calls counted, 4 ok results — the 5th never returned
    assert job["tool_activity"] == {"bash_total": 5, "bash_ok": 4}
    assert job["turn_telemetry"][0]["bash_total"] == 5
    assert job["turn_telemetry"][0]["bash_ok"] == 4

    # the published summary (schema v2): typed loop_trap (ts dropped) +
    # the real tool_activity — the cc236 gap (0/0) is closed
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    s = summary.build_summary(_Cfg(tmp_path), job, 0)
    assert s["probe_result"] == "LOOP-TRAP"
    assert s["loop_trap"] == {"tool": "Bash", "hash": "b" * 64, "n": 5}
    assert s["tool_activity"] == {"bash_total": 5, "bash_ok": 4}
