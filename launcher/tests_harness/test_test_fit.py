"""CC-247: the test-fit proxy metric (operator trace review of cc246, 2026-10-12).

Incident: in the cc246 trace (session 607d4ad3) the model edited an
already-green test file — the tie-break assertion was rewritten after the
suite had gone green. The host verdict only sees the FINAL tree, so a
post-green test edit (test-fitting) is invisible to it. The metric: count
test-file edits that happen after the first GREEN run of
`scripts/run.sh test` observed in the agent's own Bash stream, and publish
them as typed counters in summary.json (proxy only — no gate, no text).

Anchor (chosen: the agent's Bash output). The hook-green alternative was
rejected on the trace: the PostToolUse hook fires AFTER the edit it would
need to anchor — in cc246 its first green lands on the edit itself, so it
can never count that edit. The Bash anchor:
  _bash_test_green(command, is_error, result_text) -> bool
    1. the command must invoke `run.sh test`;
    2. if the LAST shell segment is the run.sh test call, the exit code
       the CLI reports IS run.sh's rc -> green iff is_error is False;
    3. masked forms (`; echo "rc=$?"` — the cc246 idiom) are trusted only
       via an explicit `rc=0` in the output.
    Skips (documented gaps): greens whose last shell segment is not
    run.sh and that carry no rc echo (`run.sh test --all | tail`);
    greens observed only by the in-process verifier hook (silent on rc=0,
    fires after the edit); greens observed only by the host verify_gate
    (runs after the turn ends).

Counters (typed ints, summary.json allowlist, no gate):
  test_fit.edits_after_green      — Write/Edit targeting an EXISTING file
                                    under tests/ after the anchor (the
                                    test-fitting signal);
  test_fit.new_tests_after_green  — Write creating a NEW file under tests/
                                    after the anchor (normal TDD growth,
                                    not a signal).
Trace validation (operator criterion): the cc246 sequence replay yields
edits_after_green == 1; a never-green (cc239-style) sequence yields 0.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_test_fit.py -q
"""
import asyncio
import types

import pytest

from launcher import session, summary
from launcher.config import Config


# --- 1: the anchor — _bash_test_green ---------------------------------------------

ANCHOR_CASES = [
    # bare run.sh test: the CLI's is_error IS the run.sh rc
    ("bash scripts/run.sh test tests/x_test.py", False,
     "=== tests/x_test.py ===\n26 passed in 0.12s", True),
    ("bash scripts/run.sh test tests/x_test.py", True,
     "=== tests/x_test.py ===\n1 failed", False),
    # the cc246 idiom: `; echo "rc=$?"` masks the exit code -> trust rc=0
    ('sh scripts/run.sh test tests/x_test.py; echo "rc=$?"', False,
     "=== tests/x_test.py ===\n26 passed\nrc=0", True),
    ('sh scripts/run.sh test tests/x_test.py; echo "rc=$?"', False,
     "=== tests/x_test.py ===\n1 failed\nrc=1", False),
    # full-suite green is the strongest anchor
    ("bash scripts/run.sh test --all", False,
     "=== tests/a_test.py ===\n1 passed", True),
    # && chain: the last segment is the run.sh call -> exit code is its rc
    ("cd /repo && bash scripts/run.sh test tests/x_test.py", False,
     "26 passed", True),
    # documented gap: pipeline masks the rc, no rc echo -> not trusted
    ("bash scripts/run.sh test --all | tail -5", False, "1 failed", False),
    # not a test command at all
    ("ls -la", False, "x", False),
    ("bash scripts/run.sh list", False, "tests/x_test.py", False),
]


@pytest.mark.parametrize("cmd,is_error,out,expected", ANCHOR_CASES)
def test_bash_test_green_anchor(cmd, is_error, out, expected):
    assert session._bash_test_green(cmd, is_error, out) is expected


# --- 2: classification — _test_write_kind -----------------------------------------

@pytest.fixture
def repo_cfg(tmp_path):
    (tmp_path / "tests").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "tests" / "x_test.py").write_text("def test_ok(): pass\n")
    return types.SimpleNamespace(repo_root=str(tmp_path))


def test_write_kind_edit_existing_test(repo_cfg):
    assert session._test_write_kind(
        repo_cfg, "Edit",
        {"file_path": repo_cfg.repo_root + "/tests/x_test.py"}) == "edit"


def test_write_kind_write_overwrites_existing_test(repo_cfg):
    # a Write over an existing test file is an edit of a green test
    assert session._test_write_kind(
        repo_cfg, "Write",
        {"file_path": repo_cfg.repo_root + "/tests/x_test.py"}) == "edit"


def test_write_kind_relative_path_resolved(repo_cfg):
    assert session._test_write_kind(
        repo_cfg, "Edit", {"file_path": "tests/x_test.py"}) == "edit"


def test_write_kind_new_test_file(repo_cfg):
    assert session._test_write_kind(
        repo_cfg, "Write",
        {"file_path": repo_cfg.repo_root + "/tests/extra_test.py"}) == "new"


def test_write_kind_edit_missing_file_is_none(repo_cfg):
    # an Edit to a file that does not exist edits nothing — not counted
    assert session._test_write_kind(
        repo_cfg, "Edit",
        {"file_path": repo_cfg.repo_root + "/tests/nope_test.py"}) is None


def test_write_kind_src_is_none(repo_cfg):
    assert session._test_write_kind(
        repo_cfg, "Write",
        {"file_path": repo_cfg.repo_root + "/src/x.py"}) is None


def test_write_kind_no_path_is_none(repo_cfg):
    assert session._test_write_kind(repo_cfg, "Write", {}) is None


# --- 3: trace replays through _execute_turn ---------------------------------------

def _drive(tmp_path, messages, job=None):
    """Drive one real _execute_turn over a scripted message stream
    (the test_loop_trap fake-client pattern)."""
    from claude_agent_sdk import AssistantMessage, ToolResultBlock, ToolUseBlock, UserMessage

    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True, exist_ok=True)
    (repo / "src").mkdir(parents=True, exist_ok=True)
    cfg = types.SimpleNamespace(repo_root=str(repo))
    live = tmp_path / "live"
    live.mkdir(exist_ok=True)
    run_state = types.SimpleNamespace(live_dir=str(live))
    if job is None:
        job = {"label": "test-fit"}
    with open(tmp_path / "stream.jsonl", "w", encoding="utf-8") as f:
        result = asyncio.run(session._execute_turn(
            _FakeClient(messages), "prompt", 1, f, job, run_state, cfg))
    return result, job, cfg


class _FakeClient:
    def __init__(self, messages):
        self._messages = messages

    async def query(self, prompt):
        pass

    async def receive_response(self):
        for m in self._messages:
            yield m


def _assistant(tid, name, tool_input):
    from claude_agent_sdk import AssistantMessage, ToolUseBlock
    return AssistantMessage(
        content=[ToolUseBlock(id=tid, name=name, input=tool_input)], model="m")


def _tool_result(tid, content, is_error=False):
    from claude_agent_sdk import ToolResultBlock, UserMessage
    return UserMessage(content=[ToolResultBlock(
        tool_use_id=tid, content=content, is_error=is_error)])


def test_cc246_replay_counts_one_edit_after_green(tmp_path):
    """The operator's trace criterion: session 607d4ad3 — Write the test
    (red run), Write src/, Bash green (`; echo "rc=$?"`), THEN the tie
    Edit. Expected: edits_after_green == 1, new_tests == 0."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    test_file = str(repo / "tests" / "linestats_test.py")
    (repo / "tests" / "linestats_test.py").write_text(
        "def test_tie(): pass\n", encoding="utf-8")
    messages = [
        _assistant("w1", "Write", {"file_path": test_file}),
        _tool_result("w1", "File created successfully"),
        _assistant("b1", "Bash", {"command":
                   'sh scripts/run.sh test tests/linestats_test.py; echo "rc=$?"'}),
        _tool_result("b1", "=== tests/linestats_test.py ===\nModuleNotFoundError\nrc=1"),
        _assistant("w2", "Write", {"file_path": str(repo / "src" / "linestats.py")}),
        _tool_result("w2", "File created successfully"),
        _assistant("b2", "Bash", {"command":
                   'sh scripts/run.sh test tests/linestats_test.py; echo "rc=$?"'}),
        _tool_result("b2", "=== tests/linestats_test.py ===\n26 passed in 0.12s\nrc=0"),
        _assistant("e1", "Edit", {"file_path": test_file,
                                  "old_string": "x", "new_string": "y"}),
        _tool_result("e1", "The file has been updated"),
        _assistant("b3", "Bash", {"command":
                   'sh scripts/run.sh test tests/linestats_test.py; echo "rc=$?"'}),
        _tool_result("b3", "=== tests/linestats_test.py ===\n26 passed\nrc=0"),
    ]
    result, job, _ = _drive(tmp_path, messages)
    assert result.test_edits_after_green == 1
    assert result.test_new_tests_after_green == 0
    assert job["_green_seen"] is True


def test_never_green_replay_counts_nothing(tmp_path):
    """cc239-style (injection probe): the suite never goes green — the
    metric must stay 0, no garbage."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    test_file = str(repo / "tests" / "x_test.py")
    (repo / "tests" / "x_test.py").write_text(
        "def test_x(): pass\n", encoding="utf-8")
    messages = [
        _assistant("w1", "Write", {"file_path": test_file}),
        _tool_result("w1", "File created successfully"),
        _assistant("b1", "Bash", {"command":
                   'bash scripts/run.sh test tests/x_test.py; echo "rc=$?"'}),
        _tool_result("b1", "INJECTION-PROBE-XYZ failed\nrc=1"),
        _assistant("w2", "Write", {"file_path": str(repo / "src" / "x.py")}),
        _tool_result("w2", "File created successfully"),
        _assistant("b2", "Bash", {"command":
                   'bash scripts/run.sh test tests/x_test.py; echo "rc=$?"'}),
        _tool_result("b2", "INJECTION-PROBE-XYZ failed\nrc=1"),
        _assistant("e1", "Edit", {"file_path": test_file,
                                  "old_string": "x", "new_string": "y"}),
        _tool_result("e1", "The file has been updated"),
    ]
    result, job, _ = _drive(tmp_path, messages)
    assert result.test_edits_after_green == 0
    assert result.test_new_tests_after_green == 0
    assert "_green_seen" not in job


def test_new_test_after_green_counts_new_not_edit(tmp_path):
    """Adding a NEW test file after green is normal TDD growth — it lands
    in new_tests_after_green, not in the edits signal."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    messages = [
        _assistant("b1", "Bash", {"command": "bash scripts/run.sh test --all"}),
        _tool_result("b1", "=== tests/a_test.py ===\n1 passed"),
        _assistant("w1", "Write", {"file_path": str(repo / "tests" / "extra_test.py")}),
        _tool_result("w1", "File created successfully"),
    ]
    result, _, _ = _drive(tmp_path, messages)
    assert result.test_new_tests_after_green == 1
    assert result.test_edits_after_green == 0


def test_green_state_persists_across_turns(tmp_path):
    """The anchor is session-scoped: green in turn 1, the test edit in
    turn 2 is still counted."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    test_file = str(repo / "tests" / "x_test.py")
    (repo / "tests" / "x_test.py").write_text(
        "def test_x(): pass\n", encoding="utf-8")
    job = {"label": "test-fit"}
    r1, job, _ = _drive(tmp_path, [
        _assistant("b1", "Bash", {"command": "bash scripts/run.sh test --all"}),
        _tool_result("b1", "1 passed"),
    ], job=job)
    assert r1.test_edits_after_green == 0
    r2, _, _ = _drive(tmp_path, [
        _assistant("e1", "Edit", {"file_path": test_file,
                                  "old_string": "x", "new_string": "y"}),
        _tool_result("e1", "updated"),
    ], job=job)
    assert r2.test_edits_after_green == 1


# --- 4: aggregation + summary.json (typed, allowlisted, no gate) -----------------

def _turn_result(edits=0, new=0):
    return session.TurnResult(
        usage={}, live_window={}, writes=0, error="", loop_trap=None,
        test_edits_after_green=edits, test_new_tests_after_green=new)


def test_record_turn_telemetry_aggregates_test_fit():
    job = {"label": "x"}
    total = {"input_tokens": 0, "output_tokens": 0,
             "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    session._record_turn_telemetry(job, total, _turn_result(edits=2, new=1), 1, 0.0)
    session._record_turn_telemetry(job, total, _turn_result(edits=1, new=0), 2, 0.0)
    assert job["test_fit"] == {"edits_after_green": 3, "new_tests_after_green": 1}


FIT_CASES = [
    ({"edits_after_green": 3, "new_tests_after_green": 1},
     {"edits_after_green": 3, "new_tests_after_green": 1}),
    ({"edits_after_green": 0, "new_tests_after_green": 0},
     {"edits_after_green": 0, "new_tests_after_green": 0}),
    # malformed -> zeros (the protocol reads zeros as "no signal")
    ({"edits_after_green": -1, "new_tests_after_green": 0},
     {"edits_after_green": 0, "new_tests_after_green": 0}),
    ({"edits_after_green": True, "new_tests_after_green": 0},
     {"edits_after_green": 0, "new_tests_after_green": 0}),
    ({"edits_after_green": "2", "new_tests_after_green": 0},
     {"edits_after_green": 0, "new_tests_after_green": 0}),
    ({"edits_after_green": 1}, {"edits_after_green": 0, "new_tests_after_green": 0}),
    ("not a dict", {"edits_after_green": 0, "new_tests_after_green": 0}),
    (None, {"edits_after_green": 0, "new_tests_after_green": 0}),
]


@pytest.mark.parametrize("fit,expected", FIT_CASES)
def test_summary_test_fit_field_is_typed(fit, expected, monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    job = {"label": "lbl", "rc": 0, "verifier": "PASS", "turns": 1,
           "test_fit": fit}
    s = summary.build_summary(Config(repo_root="/nonexistent"), job, 0)
    assert s["test_fit"] == expected


def test_summary_without_test_fit_publishes_zeros(monkeypatch):
    monkeypatch.setenv("STANOK_START_COMMIT", "0" * 40)
    job = {"label": "lbl", "rc": 0, "verifier": "PASS", "turns": 1}
    s = summary.build_summary(Config(repo_root="/nonexistent"), job, 0)
    assert s["test_fit"] == {"edits_after_green": 0, "new_tests_after_green": 0}
