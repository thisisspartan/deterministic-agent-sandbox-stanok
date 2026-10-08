"""--help is documentation (modernization batch 1, 2026-10-08).

The top-level parser must say what the system does and where the verdict
lives (evidence/<label>/summary.json), point to ARCHITECTURE.md and the
ExitCode namespace, and every subcommand (run/status/wait/stop) must carry a
one-line help. Pinned through the real CLI (subprocess), not the parser
object — the contract is what a user sees in the terminal.

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_cli_help.py -q
"""
import os
import re
import subprocess
import sys
from pathlib import Path

LAUNCHER_DIR = Path(__file__).resolve().parents[1]


def _cli(*args, tmp_repo):
    env = dict(os.environ, STANOK_REPO=str(tmp_repo))
    return subprocess.run(
        [sys.executable, str(LAUNCHER_DIR / "stanok.py"), *args],
        env=env, capture_output=True, text=True, timeout=60,
    )


def test_help_names_architecture_and_verdict_file(tmp_path):
    proc = _cli("--help", tmp_repo=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "ARCHITECTURE.md" in out
    assert "summary.json" in out
    assert "ExitCode" in out


def test_help_lists_all_four_subcommands(tmp_path):
    proc = _cli("--help", tmp_repo=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    out = proc.stdout
    assert "{run,status,wait,stop}" in out  # the usage metavar list
    for cmd in ("run", "status", "wait", "stop"):
        # a subcommand entry: indented name followed by its help text
        assert re.search(rf"^\s+{cmd}\s{{2,}}\S", out, re.MULTILINE), cmd


def test_run_help_documents_follow(tmp_path):
    proc = _cli("run", "--help", tmp_repo=tmp_path)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "--follow" in proc.stdout
