"""CC-284 — reference tests for src/tetris_cli.py.

Covers the ticket contract: main(argv) -> int exit codes (--help 0, bad
flag/value/odd height 2), the bounded --ticks mode (truecolor frames, no
ESC[H, empty/DEVNULL stdin allowed), immediate quit on 'q' in a pipe,
determinism of identical bounded runs, direct main() invocation, and the
isatty gate for in-place redraw (ESC[H before every frame after the first,
only when stdout.isatty(); pipe output byte-identical without home).

Tests 1-7 need no TTY: subprocess with piped or DEVNULL stdin, plus
in-process calls with fake streams. Visual quality is not tested.
"""
import io
import os
import subprocess
import sys
import time

import pytest

import tetris_cli as cli

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = "\x1b[H"  # CUP home sequence — the in-place redraw marker
FG_PREFIX = "\x1b[38;2;"  # truecolor foreground prefix (tetris_render macro)
GLYPH = "▀"  # U+2580 half-block glyph


# ---------------------------------------------------------------- helpers

def run_cli(args, stdin_bytes=None, devnull=False):
    """Run `python -m src.tetris_cli <args>` from the repo root.

    stdin_bytes=None with devnull=False gives an empty pipe; devnull=True
    uses stdin=DEVNULL. Returns (returncode, stdout_text).
    """
    if devnull:
        feed, stdin_kwargs = None, {"stdin": subprocess.DEVNULL}
    else:
        feed, stdin_kwargs = (stdin_bytes if stdin_bytes is not None else b""), {}
    proc = subprocess.run(
        [sys.executable, "-m", "src.tetris_cli", *args],
        input=feed,
        capture_output=True,
        cwd=REPO_ROOT,
        timeout=30,
        **stdin_kwargs,
    )
    return proc.returncode, proc.stdout.decode("utf-8", "replace")


def frame_count(text):
    """Number of rendered frames in an output stream (frames are fixed-size:
    every frame contains the truecolor prefix; count per-frame markers by
    counting the border glyph runs of the top border line)."""
    return text.count(GLYPH)


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


BOUNDED_ARGS = ["--seed", "1", "--width", "6", "--height", "4"]


# ---------------------------------------------------------------- 1. --help

def test_help_exits_zero():
    rc, _ = run_cli(["--help"])
    assert rc == 0


# ---------------------------------------------------------------- 2. bad flags

def test_unknown_flag_rejected():
    rc, _ = run_cli(["--nope"])
    assert rc == 2


def test_odd_height_rejected():
    rc, _ = run_cli(["--height", "7", "--ticks", "1"])
    assert rc == 2


def test_invalid_values_rejected():
    assert run_cli(["--width", "abc"])[0] == 2
    assert run_cli(["--seed", "1.5"])[0] == 2
    assert run_cli(["--fps", "0"])[0] == 2
    assert run_cli(["--ticks", "0"])[0] == 2


# ---------------------------------------------------------------- 3. bounded mode

def test_bounded_mode_prints_frames_without_home():
    rc, out = run_cli(
        BOUNDED_ARGS + ["--ticks", "2"], stdin_bytes=b"a\nd\nq\n"
    )
    assert rc == 0
    assert FG_PREFIX in out, "expected ANSI truecolor frames"
    assert GLYPH in out, "expected half-block frames"
    assert HOME not in out, "--ticks mode must never emit ESC[H"


# ---------------------------------------------------------------- 4. empty stdin

def test_bounded_mode_accepts_empty_stdin():
    rc, _ = run_cli(BOUNDED_ARGS + ["--ticks", "1"], devnull=True)
    assert rc == 0
    rc, _ = run_cli(BOUNDED_ARGS + ["--ticks", "1"], stdin_bytes=b"")
    assert rc == 0


# ---------------------------------------------------------------- 5. q quits early

def test_quit_in_pipe_stops_before_ticks_complete():
    args = BOUNDED_ARGS + ["--fps", "100", "--ticks", "5"]
    start = time.monotonic()
    rc_q, out_q = run_cli(args, stdin_bytes=b"a\nd\nq\n")
    elapsed_q = time.monotonic() - start
    rc_full, out_full = run_cli(args, stdin_bytes=b"a\nd\n")

    assert rc_q == 0
    assert rc_full == 0
    # q-run produced strictly fewer frames than the full 5-tick run...
    assert 0 < frame_count(out_q) < frame_count(out_full)
    # ...and finished well below what an fps-paced run would need.
    assert elapsed_q < 1.0


# ---------------------------------------------------------------- 6. determinism

def test_bounded_runs_are_deterministic():
    args = BOUNDED_ARGS + ["--ticks", "3"]
    feed = b"a\nd\nw\ns\n \n"
    rc1, out1 = run_cli(args, stdin_bytes=feed)
    rc2, out2 = run_cli(args, stdin_bytes=feed)
    assert rc1 == 0 and rc2 == 0
    assert out1 == out2
    assert FG_PREFIX in out1


# ---------------------------------------------------------------- 7. direct main()

def test_main_called_directly_returns_zero(monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))  # DEVNULL-equivalent
    assert cli.main(["--ticks", "1", "--width", "6", "--height", "4"]) == 0


# ---------------------------------------------------------------- 8. isatty gate

def _run_loop_frames(isatty_value, max_frames=3):
    out = FakeStdout(isatty_value)
    inp = FakeStdin("")  # no commands available, never a TTY
    rc = cli.run_loop(
        inp,
        out,
        seed=1,
        width=6,
        height=4,
        fps=1000,
        max_frames=max_frames,
        sleep=lambda s: None,
    )
    assert rc == 0
    return out.getvalue()


def test_tty_stdout_emits_home_before_every_frame_but_the_first():
    text = _run_loop_frames(True, max_frames=3)
    # ESC[H appears exactly before frames 2..3 — never before the first.
    assert text.count(HOME) == 2
    assert not text.startswith(HOME)
    parts = text.split(HOME)
    assert len(parts) == 3
    for part in parts:
        assert FG_PREFIX in part and GLYPH in part, "every frame must be rendered"


def test_pipe_stdout_never_emits_home_and_is_byte_identical_without_it():
    tty_text = _run_loop_frames(True, max_frames=3)
    pipe_text = _run_loop_frames(False, max_frames=3)
    assert HOME not in pipe_text
    # The pipe stream is byte-identical to the TTY stream with the home
    # sequences removed — the home sequence is the ONLY difference.
    assert pipe_text == tty_text.replace(HOME, "")
