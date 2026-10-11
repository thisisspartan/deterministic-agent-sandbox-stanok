"""CC-236 startup hook self-check (session._hook_selfcheck).

Incident cc235 (operator trace review 2026-10-11): the CLI does NOT export
CLAUDE_PROJECT_DIR for hooks (cli.js 2.1.88 exports it only in plugin
context); the PreToolUse command registered in .claude/settings.json
("$CLAUDE_PROJECT_DIR/.claude/hooks/loop-guard.py") expanded to
/.claude/hooks/... -> exit 127 on EVERY tool call (num_non_blocking_error=1
in the trace) — the loop guard was dead and the verdict was still
CLEAN-FIRST. The self-check expands the registered commands exactly as the
CLI's hook shell would (CLAUDE_PROJECT_DIR == cfg.repo_root, exported by
build_agent_env) and requires every absolute path token to be an executable
file. Failure = ENV-FAIL (rc=16), no model token spent.
"""
import asyncio
import json
import subprocess
from pathlib import Path

from launcher import session
from launcher.config import Config

REPO_ROOT = Path(__file__).resolve().parents[2]


class _Cfg:
    def __init__(self, repo_root):
        self.repo_root = str(repo_root)


def _settings(repo, commands):
    hooks = {"PreToolUse": [{"hooks": [
        {"type": "command", "command": c} for c in commands]}]}
    d = repo / ".claude"
    d.mkdir(parents=True, exist_ok=True)
    (d / "settings.json").write_text(json.dumps({"hooks": hooks}))


def test_real_repo_hooks_resolve():
    # The operator's test (CC-236): the hook command registered in the REAL
    # .claude/settings.json resolves to a real executable file.
    cfg = Config()
    job = {}
    assert session._hook_selfcheck(cfg, job) is None
    assert job == {}  # a passing self-check writes nothing into the job


def test_hook_executable_in_git_index():
    # The tree transport is `git archive HEAD` — it carries the INDEX mode.
    # Found while implementing CC-236: the hook was 100644 in the index
    # (working tree 0755) — the Pod copy would be non-executable -> exit 126
    # on every tool call, the same dead-guard class as cc235. Pin: 100755.
    out = subprocess.run(
        ["git", "ls-files", "-s", ".claude/hooks/loop-guard.py"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    assert out.split()[0] == "100755"


def test_expanded_command_resolves(tmp_path):
    hook = tmp_path / ".claude" / "hooks" / "guard.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/usr/bin/env python3\n")
    hook.chmod(0o755)
    _settings(tmp_path, ["$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py"])
    job = {}
    assert session._hook_selfcheck(_Cfg(tmp_path), job) is None
    assert job == {}


def test_missing_hook_file_is_envfail(tmp_path):
    # The cc235 situation: $CLAUDE_PROJECT_DIR unset -> /.claude/hooks/...
    # — here modelled as a path that resolves to no file at all.
    _settings(tmp_path, ["$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py"])
    job = {}
    rc = session._hook_selfcheck(_Cfg(tmp_path), job)
    assert rc == 16  # ExitCode.ENV_FAIL
    assert job["verifier"] == "FAIL"
    assert "ENV-FAIL" in job["error"]
    assert job["turns"] == 0  # no turn was ever started


def test_non_executable_hook_is_envfail(tmp_path):
    hook = tmp_path / ".claude" / "hooks" / "guard.py"
    hook.parent.mkdir(parents=True)
    hook.write_text("#!/usr/bin/env python3\n")
    hook.chmod(0o644)  # exists but not executable -> exit 126 at call time
    _settings(tmp_path, ["${CLAUDE_PROJECT_DIR}/.claude/hooks/guard.py"])
    job = {}
    assert session._hook_selfcheck(_Cfg(tmp_path), job) == 16


def test_settings_without_hooks_is_ok(tmp_path):
    d = tmp_path / ".claude"
    d.mkdir()
    (d / "settings.json").write_text(json.dumps({"permissions": {}}))
    job = {}
    assert session._hook_selfcheck(_Cfg(tmp_path), job) is None
    assert job == {}


def test_session_stops_before_model_on_hook_envfail(tmp_path, monkeypatch):
    # Wiring: run_continuous_session runs the hook self-check BEFORE the
    # client is created. The Bash self-check passes first (writable
    # CLAUDE_CODE_TMPDIR), then the broken hook registration aborts.
    monkeypatch.setenv("CLAUDE_CODE_TMPDIR", str(tmp_path))
    _settings(tmp_path, ["$CLAUDE_PROJECT_DIR/.claude/hooks/guard.py"])

    class _NoClient:
        def __init__(self, *a, **k):
            raise AssertionError("client created despite ENV-FAIL")

    import claude_agent_sdk
    monkeypatch.setattr(claude_agent_sdk, "ClaudeSDKClient", _NoClient)
    job = {"label": "hook-selfcheck-wiring"}
    rc = asyncio.run(session.run_continuous_session(
        _Cfg(tmp_path), None, job, "prompt", 0, None))
    assert rc == 16
