"""W13 — CLI integrity in setup.sh (hermetic, no docker, no checkout).

Pins the staging contract in setup.sh:
  1  no hardcoded default checkout path — STANOK_CLI_DIR is required
     (the old default /home/hermes/git/claude-code-2.1.88 is gone);
  2  an unset STANOK_CLI_DIR fails closed (exit 1) with a clear message;
  3  the pinned sha256 of cli.js / package.json / rg is present in
     setup.sh (a tampered or wrong checkout must fail the build).

Run: <venv>/bin/python -m pytest launcher/tests_harness/test_setup_cli_integrity.py -q
"""
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP_SH = REPO_ROOT / "setup.sh"


def test_setup_sh_exists():
    assert SETUP_SH.is_file()


def test_no_hardcoded_default_cli_path():
    text = SETUP_SH.read_text(encoding="utf-8")
    # The old default path must not appear anywhere (not even in a comment
    # that would suggest it is still a fallback).
    assert "/home/hermes/git/claude-code-2.1.88" not in text
    # STANOK_CLI_DIR must be required, not defaulted: the assignment uses
    # the :? (fail-closed) form, not :- (default) form.
    assert "STANOK_CLI_DIR:?ERROR" in text
    assert 'CLI_SRC="${STANOK_CLI_DIR:-' not in text


def test_unset_stanok_cli_dir_fails_closed(tmp_path):
    # Extract the CLI_SRC assignment line from setup.sh and run it in a
    # clean environment: unset STANOK_CLI_DIR must exit 1 with the
    # operator-facing message (not a silent fallback, not a crash).
    text = SETUP_SH.read_text(encoding="utf-8")
    line = next(l for l in text.splitlines() if l.startswith("CLI_SRC="))
    env = {k: v for k, v in os.environ.items() if k != "STANOK_CLI_DIR"}
    proc = subprocess.run(
        ["bash", "-c", "set -euo pipefail\n" + line + "\necho UNREACHABLE"],
        env=env, capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "UNREACHABLE" not in proc.stdout
    assert "STANOK_CLI_DIR" in proc.stderr


def test_pinned_sha256s_present():
    text = SETUP_SH.read_text(encoding="utf-8")
    for var in ("CLI_JS_SHA", "PKG_JSON_SHA", "RG_SHA"):
        assert f'{var}="' in text, var
        # 64 hex chars
        val = next(
            l.split('"')[1] for l in text.splitlines()
            if l.startswith(var + '="')
        )
        assert len(val) == 64 and all(c in "0123456789abcdef" for c in val), \
            f"{var} is not a sha256 hex string"
