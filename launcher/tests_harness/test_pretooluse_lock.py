"""contract_lock first echelon (CC-104): PreToolUse deny before write.

_pretooluse_lock_hook denies Edit/Write/MultiEdit on PRE-EXISTING manifest
files (tests/*, scripts/run.sh) before the write hits disk. New files
(TDD red phase) and paths outside the manifest stay writable — a blanket
deny would break TDD. The post-turn SHA256 manifest diff remains the
independent second echelon (Bash bypass).

Live-verified: CLI 2.1.88 honors permissionDecision=deny from an SDK
callback hook (focused run 2026-09-22: hook denied, file not created).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_pretooluse_lock.py -q
"""
import asyncio
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]
if str(LAUNCHER_DIR) not in sys.path:
    sys.path.insert(0, str(LAUNCHER_DIR))
import stanok  # noqa: E402

from conftest import repo, write


def _hook(repo, tool_name, file_path):
    return asyncio.run(stanok._pretooluse_lock_hook(
        {"tool_name": tool_name, "tool_input": {"file_path": file_path}},
        "hook-id", None,
    ))


def _decision(result):
    return (result.get("hookSpecificOutput") or {}).get("permissionDecision")


_UNSET = object()


def _arm(repo, monkeypatch, manifest=_UNSET):
    monkeypatch.setattr(stanok, "REPO_ROOT", str(repo))
    monkeypatch.setitem(
        stanok._CONTRACT_LOCK_STATE, "manifest",
        stanok._tests_manifest() if manifest is _UNSET else manifest,
    )


def test_deny_edit_pre_existing_test(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    _arm(repo, monkeypatch)
    res = _hook(repo, "Edit", str(repo / "tests" / "x_test.py"))
    assert _decision(res) == "deny"
    reason = res["hookSpecificOutput"]["permissionDecisionReason"]
    assert "CONTRACT-LOCK" in reason
    assert "tests/x_test.py" in reason


def test_deny_write_runsh(repo, monkeypatch):
    # The repo fixture installs the live scripts/run.sh -> in the manifest.
    _arm(repo, monkeypatch)
    res = _hook(repo, "Write", str(repo / "scripts" / "run.sh"))
    assert _decision(res) == "deny"


def test_deny_relative_path(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    _arm(repo, monkeypatch)
    res = _hook(repo, "Edit", "tests/x_test.py")
    assert _decision(res) == "deny"


def test_deny_symlink_escape(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    link = repo / "src" / "x_link.py"
    link.symlink_to(repo / "tests" / "x_test.py")
    _arm(repo, monkeypatch)
    res = _hook(repo, "Write", str(link))
    assert _decision(res) == "deny"


def test_allow_new_test_file(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    _arm(repo, monkeypatch)
    res = _hook(repo, "Write", str(repo / "tests" / "new_test.py"))
    assert _decision(res) is None


def test_allow_src_file(repo, monkeypatch):
    _arm(repo, monkeypatch)
    res = _hook(repo, "Write", str(repo / "src" / "mod.js"))
    assert _decision(res) is None


def test_no_manifest_allows(repo, monkeypatch):
    write(repo / "tests" / "x_test.py", "def test_x():\n    assert 1\n")
    _arm(repo, monkeypatch, manifest=None)
    res = _hook(repo, "Edit", str(repo / "tests" / "x_test.py"))
    assert _decision(res) is None
