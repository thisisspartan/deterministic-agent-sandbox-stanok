"""TASK-STANOK-CC-271: the CLI rejects invalid --frame / --frames values.

The CLI runs as a subprocess with stdin=DEVNULL — the same technique as the
`_cli` helper in tests/fire_test.py, re-declared here so this file is
self-contained. Small fixed dimensions keep the output deterministic and below
any terminal clamp.

Contract: an invalid frame count fails exactly the way an invalid --width /
--height already does — a clean argparse usage error (rc=2, message on stderr,
no traceback). Valid boundaries (--frame 0, --frames 1) still render a frame.
"""

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_FIRE = REPO_ROOT / "src" / "fire.py"

SIZE = ("--width", "6", "--height", "3")


def _cli(*args):
    env = os.environ.copy()
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return subprocess.run(
        [sys.executable, str(SRC_FIRE), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=30,
    )


def _assert_usage_error(result, flag):
    assert result.returncode == 2, (
        f"expected a usage error (rc=2), got rc={result.returncode}\n"
        f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
    )
    assert "Traceback" not in result.stderr, f"traceback leaked: {result.stderr!r}"
    assert flag in result.stderr, f"{flag} not named in stderr: {result.stderr!r}"


# --- invalid frame counts: a usage error, not a crash or silence -----------


def test_frame_negative_is_a_usage_error():
    _assert_usage_error(_cli("--frame", "-1", *SIZE), "--frame")


def test_frames_zero_is_a_usage_error():
    _assert_usage_error(_cli("--frames", "0", *SIZE), "--frames")


def test_frames_negative_is_a_usage_error():
    _assert_usage_error(_cli("--frames", "-1", *SIZE), "--frames")


# --- valid boundaries: unchanged behaviour ---------------------------------


def test_frame_zero_renders_one_frame_and_exits_zero():
    result = _cli("--frame", "0", *SIZE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "no frame on stdout"


def test_frames_one_renders_one_frame_and_exits_zero():
    result = _cli("--frames", "1", *SIZE)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip(), "no frame on stdout"
