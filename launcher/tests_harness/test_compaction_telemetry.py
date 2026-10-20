"""P1 telemetry (Opik analysis CC-302/CC-304, 2026-10-20): compact_boundary
is a NATIVE event of the pinned CLI (cli.js 2.1.88):
  {"type":"system","subtype":"compact_boundary",
   "compact_metadata":{"trigger": str, "pre_tokens": int, ...}}
The Agent SDK routes unknown system subtypes to a generic SystemMessage with
the raw dict on .data (message_parser.py `case _`). This harness pins the
whole typed path: parser entry -> TurnResult.compactions ->
job["compactions"] (turn-tagged) -> summary.json "compactions".

Provenance of expected literals: the compact_metadata field names are read
from the pinned bundle (cli.js: function MU8 -> {trigger, pre_tokens,
preserved_segment}); the 110285 value mirrors the real cc304 window size
recorded in specs/STATUS.md («Разбор Opik-трейсов»). Token totals are
asserted UNCHANGED by this path — this feature records events, it must not
move numbers.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_compaction_telemetry.py -q
"""
import asyncio
import json

import pytest

# Bare environments without the SDK: skip the module, never break collection
# (operator decision 2026-10-20; the CI installs the SDK from the pinned lock,
# so the published skip-set contract is unchanged by this guard).
pytest.importorskip("claude_agent_sdk")
from claude_agent_sdk import ResultMessage, SystemMessage  # noqa: E402

from launcher import session, summary
from launcher.config import Config

# the real wire shape (cli.js MU8 output), kept verbatim as the positive case
COMPACT_DATA = {
    "type": "system",
    "subtype": "compact_boundary",
    "session_id": "s-1",
    "uuid": "u-1",
    "compact_metadata": {"trigger": "auto", "pre_tokens": 110285},
}

ENTRY = {"trigger": "auto", "pre_tokens": 110285}


def _result_msg(usage):
    return ResultMessage(
        subtype="success", duration_ms=100, duration_api_ms=90,
        is_error=False, num_turns=1, session_id="s-1", usage=usage,
    )


class _FakeClient:
    def __init__(self, msgs):
        self._msgs = msgs

    async def query(self, prompt):
        pass

    async def receive_response(self):
        for m in self._msgs:
            yield m


# --- 1: _compaction_entry is typed, only for the real event ---------------------

def test_entry_positive():
    msg = SystemMessage(subtype="compact_boundary", data=COMPACT_DATA)
    assert session._compaction_entry(msg) == ENTRY


def test_entry_negatives():
    usage_msg = _result_msg({"input_tokens": 1})
    cases = [
        SystemMessage(subtype="init", data=COMPACT_DATA),            # other subtype
        SystemMessage(subtype="compact_boundary", data=None),         # no data
        SystemMessage(subtype="compact_boundary", data="not a dict"), # malformed data
        SystemMessage(subtype="compact_boundary",
                      data={**COMPACT_DATA, "compact_metadata": "junk"}),  # malformed payload
        SystemMessage(subtype="compact_boundary",
                      data={**COMPACT_DATA,
                            "compact_metadata": {"trigger": "auto"}}),  # missing pre_tokens
        SystemMessage(subtype="compact_boundary",
                      data={**COMPACT_DATA,
                            "compact_metadata": {"trigger": "auto", "pre_tokens": True}}),  # bool is not int
        usage_msg,                                                   # ResultMessage
    ]
    for msg in cases:
        assert session._compaction_entry(msg) is None, msg


# --- 2: _execute_turn collects the events it sees in the turn -------------------

def _run_turn(tmp_path, msgs):
    run_state = type("RS", (), {"live_dir": str(tmp_path)})()
    stream_f = open(tmp_path / "stream.jsonl", "w", encoding="utf-8")
    result = asyncio.run(session._execute_turn(
        _FakeClient(msgs), "prompt", 1, stream_f, {}, run_state, None))
    stream_f.close()
    return result


def test_execute_turn_collects_compactions(tmp_path):
    result = _run_turn(tmp_path, [
        SystemMessage(subtype="compact_boundary", data=COMPACT_DATA),
        _result_msg({"input_tokens": 10, "output_tokens": 5}),
    ])
    assert result.compactions == [ENTRY]
    # token totals are NOT touched by the compaction path
    assert result.usage == {"input_tokens": 10, "output_tokens": 5}


def test_execute_turn_no_event_empty_list(tmp_path):
    result = _run_turn(tmp_path, [_result_msg({"input_tokens": 10})])
    assert result.compactions == []


# --- 3: _record_turn_telemetry tags entries with the turn -----------------------

def _turn_result(compactions):
    return session.TurnResult(
        usage={"input_tokens": 10, "output_tokens": 5,
               "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        live_window={"input_tokens": 10}, writes=0, error="", loop_trap=None,
        compactions=compactions,
    )


def _zeros():
    return {"input_tokens": 0, "output_tokens": 0,
            "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}


def test_record_tags_turn_and_extends():
    job = {}
    session._record_turn_telemetry(job, _zeros(), _turn_result([ENTRY]), 2, 1.0)
    assert job["compactions"] == [{"turn": 2, **ENTRY}]
    # second turn appends, never replaces
    session._record_turn_telemetry(job, _zeros(), _turn_result([ENTRY]), 3, 1.0)
    assert job["compactions"] == [{"turn": 2, **ENTRY}, {"turn": 3, **ENTRY}]


def test_record_absent_without_events():
    job = {}
    session._record_turn_telemetry(job, _zeros(), _turn_result([]), 1, 1.0)
    assert "compactions" not in job  # absence stays absence, no fabricated entry


# --- 4: summary passthrough is typed; malformed entries drop ---------------------

def _summary(job, monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    return summary.build_summary(Config(repo_root="/nonexistent"), job, 0)


def test_summary_field_typed_and_filtered(monkeypatch):
    job = {"label": "lbl", "compactions": [
        {"turn": 1, "trigger": "auto", "pre_tokens": 110285},
        {"turn": True, "trigger": "auto", "pre_tokens": 1},   # bool turn
        {"turn": 0, "trigger": "auto", "pre_tokens": 1},      # turn must be >=1
        {"turn": 2, "trigger": None, "pre_tokens": 1},        # trigger must be str
        {"turn": 2, "trigger": "manual", "pre_tokens": -1},   # pre_tokens >= 0
        "not a dict",
    ]}
    s = _summary(job, monkeypatch)
    assert s["compactions"] == [
        {"turn": 1, "trigger": "auto", "pre_tokens": 110285}]
    # no free text ever enters the field
    json.dumps(s["compactions"])


def test_summary_default_is_empty_list(monkeypatch):
    assert _summary({"label": "lbl"}, monkeypatch)["compactions"] == []
