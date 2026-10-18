"""CC-289 — reference tests for src/fire_cli.py.

Covers the ticket contract: exit codes (--help 0; unknown flag / bad
value 2), bounded --frames mode over a pipe (exactly frames*height
lines, truecolor cells, NO ESC[H and no cursor sequences outside a
TTY), DEVNULL stdin, immediate quit on 'q' in a pipe, byte-determinism
of identical bounded runs, direct main(), the isatty segment (hide
cursor + CUP before EVERY frame including the first + show cursor at
exit; nothing of it outside a TTY), and a clean SIGINT exit.

Tests 1-8 need no real PTY — the live-terminal invariants are already
the protected acceptance contract in tests/fire_terminal_test.py.
"""
import io
import os
import signal
import subprocess
import sys
import time

import pytest

import fire_cli as cli

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = "\x1b[H"  # CUP home — the in-place redraw marker (TTY stdout only)
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CURSOR_PREFIX = "\x1b[?25"
FG_PREFIX = "\x1b[48;2;"  # SGR truecolor background prefix (fire_render cells)


# ---------------------------------------------------------------- helpers

def run_cli(args, stdin_bytes=None, devnull=False):
    """Run `python -m src.fire_cli <args>` from the repo root.

    stdin_bytes=None with devnull=False gives an empty pipe; devnull=True
    uses stdin=DEVNULL. Returns (returncode, stdout_text).
    """
    if devnull:
        feed, stdin_kwargs = None, {"stdin": subprocess.DEVNULL}
    else:
        feed, stdin_kwargs = (stdin_bytes if stdin_bytes is not None else b""), {}
    proc = subprocess.run(
        [sys.executable, "-m", "src.fire_cli", *args],
        input=feed,
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=30,
        **stdin_kwargs,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def line_count(text):
    """Number of output lines (render joins frame lines with \\r\\n; frames
    are separated by \\n — splitlines counts both)."""
    return len(text.splitlines())


class FakeStdout(io.StringIO):
    """In-memory stdout with a controllable isatty() answer."""

    def __init__(self, isatty_value):
        super().__init__()
        self._isatty = isatty_value

    def isatty(self):
        return self._isatty


class FakeStdin(io.StringIO):
    """In-memory stdin: never a TTY, EOF once drained."""

    def isatty(self):
        return False


# ---------------------------------------------------------------- 1. flags

def test_help_exits_zero():
    rc, _ = run_cli(["--help"])
    assert rc == 0


def test_unknown_flag_rejected():
    rc, _ = run_cli(["--nope"])
    assert rc == 2


def test_invalid_flag_values_rejected():
    assert run_cli(["--frames", "0", "--width", "6", "--height", "4"])[0] == 2
    assert run_cli(["--frames", "abc", "--width", "6", "--height", "4"])[0] == 2
    assert run_cli(["--width", "1", "--height", "4", "--frames", "1"])[0] == 2
    assert run_cli(["--width", "6", "--height", "0", "--frames", "1"])[0] == 2
    assert run_cli(["--width", "6", "--height", "4", "--fps", "0"])[0] == 2


# ---------------------------------------------------------------- 2. bounded pipe

def test_bounded_pipe_prints_exact_frames_without_terminal_segment():
    rc, out = run_cli(
        ["--seed", "1", "--width", "10", "--height", "4",
         "--frames", "3", "--fps", "1000"],
        stdin_bytes=b"",
    )
    assert rc == 0
    assert line_count(out) == 12, "exactly 3 frames x 4 lines"
    assert FG_PREFIX in out, "expected SGR truecolor frames"
    assert HOME not in out, "pipe stdout must not contain ESC[H"
    assert CURSOR_PREFIX not in out, "pipe stdout must not touch the cursor"


# ---------------------------------------------------------------- 3. DEVNULL stdin

def test_bounded_mode_accepts_devnull_stdin():
    rc, out = run_cli(
        ["--seed", "1", "--width", "6", "--height", "4",
         "--frames", "2", "--fps", "1000"],
        devnull=True,
    )
    assert rc == 0
    assert line_count(out) == 8


# ---------------------------------------------------------------- 4. q quits early

def test_quit_in_pipe_stops_before_frames_complete():
    args = ["--seed", "1", "--width", "6", "--height", "4",
            "--frames", "300", "--fps", "1000"]
    start = time.monotonic()
    rc_q, out_q = run_cli(args, stdin_bytes=b"q\n")
    elapsed_q = time.monotonic() - start
    rc_full, out_full = run_cli(args, stdin_bytes=b"")

    assert rc_q == 0
    assert rc_full == 0
    # The q-run is noticeably shorter than the full 300-frame run...
    assert 0 < line_count(out_q) < line_count(out_full)
    # ...and it quit immediately, not after pacing out 300 frames.
    assert elapsed_q < 1.0


# ---------------------------------------------------------------- 5. determinism

def test_bounded_runs_are_deterministic():
    args = ["--seed", "7", "--width", "8", "--height", "3",
            "--frames", "4", "--fps", "1000"]
    feed = b"hello\n"  # no q: the full bounded run must complete
    rc1, out1 = run_cli(args, stdin_bytes=feed)
    rc2, out2 = run_cli(args, stdin_bytes=feed)
    assert rc1 == 0 and rc2 == 0
    assert out1 == out2
    assert FG_PREFIX in out1


# ---------------------------------------------------------------- 6. direct main()

def test_main_called_directly_returns_zero(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # DEVNULL-equivalent
    assert cli.main(["--frames", "1", "--width", "6", "--height", "4",
                     "--fps", "1000"]) == 0


# ---------------------------------------------------------------- 7. isatty segment

def _run_loop_captured(isatty_value, frames=3):
    out = FakeStdout(isatty_value)
    inp = FakeStdin("")  # no commands available, never a TTY
    rc = cli.run_loop(
        inp,
        out,
        seed=1,
        width=6,
        height=4,
        fps=1000,
        frames=frames,
        sleep=lambda s: None,
    )
    assert rc == 0
    return out.getvalue()


def test_tty_stdout_runs_the_full_terminal_segment():
    text = _run_loop_captured(True, frames=3)
    # Cursor hidden before the first frame, shown after the last.
    assert text.count(HIDE_CURSOR) == 1 and text.count(SHOW_CURSOR) == 1
    assert text.startswith(HIDE_CURSOR)
    assert text.endswith(SHOW_CURSOR)
    # CUP before EVERY frame, including the first: 3 homes, 3 frames.
    assert text.count(HOME) == 3
    parts = text.split(HOME)
    assert len(parts) == 4
    assert parts[0] == HIDE_CURSOR  # nothing was drawn before the first home
    for part in parts[1:]:
        assert FG_PREFIX in part, "every frame must be rendered"
    assert parts[-1].endswith(SHOW_CURSOR)


def test_pipe_stdout_has_no_terminal_segment_at_all():
    text = _run_loop_captured(False, frames=3)
    assert HOME not in text
    assert CURSOR_PREFIX not in text
    assert line_count(text) == 12


# ---------------------------------------------------------------- 8. SIGINT

def test_sigint_stops_interactive_run_cleanly():
    proc = subprocess.Popen(
        [sys.executable, "-m", "src.fire_cli", "--seed", "1",
         "--width", "6", "--height", "4", "--fps", "15"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=REPO_ROOT,
    )
    try:
        time.sleep(1.0)  # the interactive loop is running (no --frames)
        proc.send_signal(signal.SIGINT)
        out, _err = proc.communicate(timeout=10)
        assert proc.returncode == 0, "SIGINT must exit cleanly with rc 0"
        assert FG_PREFIX in out.decode("utf-8", "replace"), \
            "the loop was actually drawing frames"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
