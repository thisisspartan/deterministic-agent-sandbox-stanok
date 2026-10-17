"""CC-279 — contract tests for src/tetris_cli.py.

CLI + interactive loop (hybrid input) over src/tetris_engine and
src/tetris_render. The CLI is driven as a subprocess (`python -m
src.tetris_cli`, stdin = DEVNULL or piped command lines) and never requires
a TTY; one test calls main() directly. Fixtures are defined in this file
(no conftest.py, per project rules).

Module contract: see docs/tetris_cli.md.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

import tetris_cli as cli
import tetris_render as tr

# ---------------------------------------------------------------- fixtures

REPO_ROOT = Path(__file__).resolve().parents[1]
PYTHON = sys.executable
CHILD_ENV = {**os.environ, "PYTHONIOENCODING": "utf-8"}

TRUECOLOR = "\x1b[38;2;"
HALF_BLOCK = "▀"


def run_cli(args, stdin_text=None, timeout=60):
    """Run `python -m src.tetris_cli <args>` from the repo root.

    stdin_text=None -> stdin=DEVNULL; otherwise the text is piped and closed.
    Returns (rc, stdout_text, elapsed_seconds).
    """
    kwargs = {
        "cwd": str(REPO_ROOT),
        "env": CHILD_ENV,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "timeout": timeout,
    }
    if stdin_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin_text.encode("utf-8")
    started = time.monotonic()
    proc = subprocess.run([PYTHON, "-m", "src.tetris_cli", *args], **kwargs)
    elapsed = time.monotonic() - started
    out = proc.stdout.decode("utf-8", "replace")
    return proc.returncode, out, elapsed


def border_row(width):
    """The top/bottom border row of a frame of the given board width."""
    return tr.render_cell(tr.BORDER_COLOR, tr.BORDER_COLOR) * (width + 2)


def frame_count(out, width):
    """Number of frames in a CLI stdout: every frame contains its border row
    exactly twice (top and bottom); content rows never do."""
    return out.count(border_row(width)) // 2


# ---------------------------------------------------------------- 1. --help

def test_help_exits_zero():
    rc, out, _ = run_cli(["--help"])
    assert rc == 0
    assert "usage" in out.lower()


# ---------------------------------------------------------------- 2. bad flags

def test_unknown_flag_is_refused():
    rc, _, _ = run_cli(["--nope"])
    assert rc == 2


def test_odd_height_is_refused():
    rc, _, _ = run_cli(["--height", "7", "--ticks", "1"])
    assert rc == 2


def test_invalid_values_are_refused():
    bad = [
        ["--width", "0"],
        ["--width", "-3"],
        ["--height", "0"],
        ["--height", "21"],
        ["--fps", "0"],
        ["--fps", "-1"],
        ["--fps", "abc"],
        ["--ticks", "0"],
        ["--ticks", "-2"],
        ["--seed", "abc"],
        ["--seed", "1", "--width", "6", "--height", "5", "--ticks", "1"],
    ]
    for args in bad:
        rc, _, _ = run_cli(args)
        assert rc == 2, f"expected rc 2 for {args}"


# ---------------------------------------------------------------- 3. bounded mode

def test_bounded_mode_prints_truecolor_frames():
    rc, out, _ = run_cli(
        ["--seed", "1", "--width", "6", "--height", "4", "--ticks", "2"],
        stdin_text="a\nd\nq\n",
    )
    assert rc == 0
    assert TRUECOLOR in out
    assert HALF_BLOCK in out
    assert frame_count(out, 6) >= 1


# ---------------------------------------------------------------- 4. empty stdin

def test_bounded_mode_with_empty_stdin():
    rc, out, _ = run_cli(
        ["--seed", "1", "--width", "6", "--height", "4", "--ticks", "2", "--fps", "100"]
    )
    assert rc == 0
    assert TRUECOLOR in out
    # exactly one frame per gravity tick
    assert frame_count(out, 6) == 2


# ---------------------------------------------------------------- 5. q in pipe

def test_quit_in_pipe_exits_before_the_ticks_complete():
    args = ["--seed", "1", "--width", "6", "--height", "4", "--ticks", "40", "--fps", "100"]
    rc_q, out_q, elapsed_q = run_cli(args, stdin_text="a\nd\nq\n")
    rc_full, out_full, elapsed_full = run_cli(args, stdin_text="a\nd\n")

    assert rc_q == 0
    assert rc_full == 0
    # the run stopped at q: fewer frames than the full N-tick run
    assert frame_count(out_q, 6) < frame_count(out_full, 6)
    assert len(out_q) < len(out_full)
    # the full run is paced at 1/fps (40 ticks * 0.01 s); the q-run does no
    # pacing at all — it exits long before the tick budget is spent
    assert elapsed_full >= 40 / 100.0
    assert elapsed_q < elapsed_full / 2.0


# ---------------------------------------------------------------- 6. determinism

def test_bounded_runs_are_deterministic():
    args = ["--seed", "7", "--width", "8", "--height", "6", "--ticks", "3", "--fps", "100"]
    script = "a\nw\nd\ns\n"
    rc1, out1, _ = run_cli(args, stdin_text=script)
    rc2, out2, _ = run_cli(args, stdin_text=script)
    assert rc1 == 0 and rc2 == 0
    assert out1 != ""
    assert out1 == out2
    assert frame_count(out1, 8) == 3


def test_different_seed_gives_a_different_frame():
    args = ["--width", "6", "--height", "4", "--ticks", "1", "--fps", "100"]
    rc1, out1, _ = run_cli(["--seed", "1", *args])
    rc2, out2, _ = run_cli(["--seed", "2", *args])
    assert rc1 == 0 and rc2 == 0
    assert out1 != out2


# ---------------------------------------------------------------- 7. main() direct

def test_main_called_directly_returns_zero(capsys):
    # pytest's captured stdin has no fileno() and raises on read: the CLI
    # must treat it as end-of-input (a DEVNULL equivalent).
    rc = cli.main(["--ticks", "1", "--width", "6", "--height", "4", "--fps", "100"])
    assert rc == 0
    captured = capsys.readouterr()
    assert TRUECOLOR in captured.out
    assert HALF_BLOCK in captured.out
    assert frame_count(captured.out, 6) == 1


def test_main_rejects_bad_arguments_without_exiting():
    assert cli.main(["--nope"]) == 2
    assert cli.main(["--height", "7", "--ticks", "1"]) == 2
    assert cli.main(["--ticks", "0"]) == 2
    assert cli.main(["--help"]) == 0


# ---------------------------------------------------------------- 8. piped run without --ticks

def test_piped_run_without_ticks_ends_at_eof():
    # No --ticks: the paced loop reads piped command lines; when stdin is
    # exhausted (EOF) it ends cleanly with rc 0 — it must not hang.
    rc, out, elapsed = run_cli(
        ["--seed", "1", "--width", "6", "--height", "4", "--fps", "100"],
        stdin_text="a\nd\n",
        timeout=30,
    )
    assert rc == 0
    assert TRUECOLOR in out
    assert elapsed < 10.0
