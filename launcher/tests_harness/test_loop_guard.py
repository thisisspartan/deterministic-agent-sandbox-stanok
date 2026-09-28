"""Loop-guard hook contract (consecutive-repetition semantics).

The hook (stanok/.claude/hooks/loop-guard.py) is a PreToolUse hook for ALL
tools: it counts only CONSECUTIVE identical calls — any different tool call
resets the counter. A TDD cycle (run.sh test -> Edit -> run.sh test) must
never be denied; 10 identical calls in a row are denied on the 10th.
Fail-open: any parse/IO failure = exit 0.
"""
import json
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "loop-guard.py"


@pytest.fixture
def sid():
    s = uuid.uuid4().hex
    yield s
    Path(f"/tmp/claude-loop-guard/{s}.state").unlink(missing_ok=True)


def call_hook(payload):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
    )


def test_tdd_cycle_not_denied(sid):
    bash = {"tool_name": "Bash",
            "tool_input": {"command": "bash scripts/run.sh test tests/x_test.py"},
            "session_id": sid}
    edit = {"tool_name": "Edit",
            "tool_input": {"file_path": "/tmp/x", "old_string": "a", "new_string": "b"},
            "session_id": sid}
    for i in range(10):
        r = call_hook(bash)
        assert r.returncode == 0, f"bash call {i + 1} denied: {r.stderr}"
        r = call_hook(edit)
        assert r.returncode == 0, f"edit call {i + 1} denied: {r.stderr}"


def test_tenth_identical_denied(sid):
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    for i in range(9):
        r = call_hook(p)
        assert r.returncode == 0, f"call {i + 1} denied early: {r.stderr}"
    r = call_hook(p)
    assert r.returncode == 2
    assert "подряд" in r.stderr


def test_counter_resets_on_different_call(sid):
    a = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    b = {"tool_name": "Bash", "tool_input": {"command": "pwd"}, "session_id": sid}
    for _ in range(9):
        assert call_hook(a).returncode == 0
    assert call_hook(b).returncode == 0
    for _ in range(9):
        assert call_hook(a).returncode == 0


def test_non_bash_tools_counted(sid):
    p = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/f.txt"},
         "session_id": sid}
    for i in range(9):
        assert call_hook(p).returncode == 0
    r = call_hook(p)
    assert r.returncode == 2


def test_garbage_stdin_fail_open():
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json", capture_output=True, text=True, timeout=10,
    )
    assert r.returncode == 0
