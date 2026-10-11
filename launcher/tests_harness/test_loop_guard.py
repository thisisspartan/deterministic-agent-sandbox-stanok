"""Loop-guard hook contract (consecutive-repetition semantics).

The hook (stanok/.claude/hooks/loop-guard.py) is a PreToolUse hook for ALL
tools: it counts only CONSECUTIVE identical calls — any different tool call
resets the counter. A TDD cycle (run.sh test -> Edit -> run.sh test) must
never be denied.

CC-207 (incident CC-204-retry3: 31 identical Reads, the denial text entered
context as just another line and did not break the loop): the threshold drops
10 -> 5 AND the denial becomes a termination signal — at the 5th consecutive
identical call the hook denies AND writes a JSON marker
{"tool","hash","n","ts"} to the path in env STANOK_LOOP_TRAP_FILE (unset ->
no marker: outside a stanok session the hook stays a pure warning). The
launcher reads the marker and ends the run with probe_result "LOOP-TRAP"
(pinned in test_loop_trap.py).
Fail-open: a parse failure = exit 0; a marker write failure never blocks the
deny. CC-234: the state path follows TMPDIR (the Pod's writable emptyDir —
the old hardcoded /tmp was dead under readOnlyRootFilesystem) and a STATE
write failure is fail-CLOSED (exit 2): a guard that cannot persist state is
dead. Tests are hermetic: the sid fixture points TMPDIR at pytest's tmp_path.
"""
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

HOOK = Path(__file__).resolve().parents[2] / ".claude" / "hooks" / "loop-guard.py"


@pytest.fixture
def sid(tmp_path, monkeypatch):
    # CC-234 hermetic: state lives under tmp_path (auto-cleaned), never /tmp.
    s = uuid.uuid4().hex
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    yield s


def _clean_env(extra=None):
    """Hermetic env: never inherit a stray STANOK_LOOP_TRAP_FILE."""
    env = dict(os.environ)
    env.pop("STANOK_LOOP_TRAP_FILE", None)
    if extra:
        env.update(extra)
    return env


def call_hook(payload, env=None):
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True, text=True, timeout=10,
        env=_clean_env(env),
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


def test_fifth_identical_denied(sid):
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    for i in range(4):
        r = call_hook(p)
        assert r.returncode == 0, f"call {i + 1} denied early: {r.stderr}"
    r = call_hook(p)
    assert r.returncode == 2
    assert "подряд" in r.stderr


def test_counter_resets_on_different_call(sid):
    a = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    b = {"tool_name": "Bash", "tool_input": {"command": "pwd"}, "session_id": sid}
    for _ in range(4):
        assert call_hook(a).returncode == 0
    assert call_hook(b).returncode == 0
    for _ in range(4):
        assert call_hook(a).returncode == 0


def test_non_bash_tools_counted(sid):
    p = {"tool_name": "Read", "tool_input": {"file_path": "/tmp/f.txt"},
         "session_id": sid}
    for i in range(4):
        assert call_hook(p).returncode == 0
    r = call_hook(p)
    assert r.returncode == 2


def test_garbage_stdin_fail_open():
    r = subprocess.run(
        [sys.executable, str(HOOK)],
        input="not json", capture_output=True, text=True, timeout=10,
        env=_clean_env(),
    )
    assert r.returncode == 0


# --- CC-207: the termination marker ------------------------------------------------

def test_marker_written_at_fifth(sid, tmp_path):
    marker = tmp_path / "live" / "loop-trap.json"  # parent dir absent -> hook creates it
    env = {"STANOK_LOOP_TRAP_FILE": str(marker)}
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    for i in range(4):
        r = call_hook(p, env)
        assert r.returncode == 0, f"call {i + 1} denied early: {r.stderr}"
        assert not marker.exists(), f"marker written already on call {i + 1}"
    r = call_hook(p, env)
    assert r.returncode == 2
    data = json.loads(marker.read_text(encoding="utf-8"))
    assert data["tool"] == "Bash"
    assert data["n"] == 5
    assert data["hash"]
    assert data["ts"]


def test_marker_fail_open(sid, tmp_path):
    # A directory in the marker's place: the write fails, the DENY still happens.
    marker_dir = tmp_path / "loop-trap.json"
    marker_dir.mkdir()
    env = {"STANOK_LOOP_TRAP_FILE": str(marker_dir)}
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    for i in range(4):
        assert call_hook(p, env).returncode == 0, f"call {i + 1} denied early"
    r = call_hook(p, env)
    assert r.returncode == 2
    assert "подряд" in r.stderr
    assert "Traceback" not in r.stderr


def test_no_env_no_marker(sid, tmp_path):
    # STANOK_LOOP_TRAP_FILE unset: the deny still happens, no marker anywhere.
    # (tmp_path now legitimately holds the state dir — only markers are
    # asserted absent.)
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": sid}
    for i in range(4):
        assert call_hook(p).returncode == 0, f"call {i + 1} denied early"
    r = call_hook(p)
    assert r.returncode == 2
    assert not [p for p in tmp_path.rglob("*") if "loop-trap" in p.name]


# --- CC-234: TMPDIR-based state path + fail-closed on state-write failure ----

def test_state_path_follows_tmpdir(tmp_path, monkeypatch):
    s = uuid.uuid4().hex
    state_root = tmp_path / "custom-tmp"  # does not exist: the hook creates it
    monkeypatch.setenv("TMPDIR", str(state_root))
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"}, "session_id": s}
    assert call_hook(p).returncode == 0
    state = state_root / "claude-loop-guard" / f"{s}.state"
    assert state.is_file(), "state must live under $TMPDIR/claude-loop-guard"
    st = json.loads(state.read_text(encoding="utf-8"))
    assert st["n"] == 1
    # the old hardcoded /tmp path must NOT be used
    assert not Path(f"/tmp/claude-loop-guard/{s}.state").exists()


def test_state_write_failure_fail_closed(tmp_path, monkeypatch):
    # A read-only TMPDIR (the Pod pre-CC-234 situation): the state cannot be
    # persisted -> the guard is dead -> deny loudly, never a silent pass.
    ro = tmp_path / "ro-tmp"
    ro.mkdir()
    ro.chmod(0o500)
    monkeypatch.setenv("TMPDIR", str(ro))
    p = {"tool_name": "Bash", "tool_input": {"command": "ls"},
         "session_id": uuid.uuid4().hex}
    r = call_hook(p)
    ro.chmod(0o700)  # let pytest clean up
    assert r.returncode == 2
    assert "не записано" in r.stderr
