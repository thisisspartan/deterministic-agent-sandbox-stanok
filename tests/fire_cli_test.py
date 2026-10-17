"""Reference tests for src/fire_cli.py — ticket TASK-STANOK-CC-276.

Stage 3 of the console-fire pipeline: the IO layer (argparse, stdout writes,
terminal probing, sleeps) composing fire_sim + fire_render into a program.

The CLI is exercised as a SUBPROCESS — `[sys.executable, "src/fire_cli.py", ...]`
from the repo root, stdin=DEVNULL — because its contract is a command line:
exit codes, stdout bytes, argparse usage errors on stderr. The no-flag
animation mode is NOT run here: it loops until SIGINT, so it would block.

Every run uses the same small fixed grid (--width 6 --height 4) and a pinned
COLUMNS/LINES (what shutil.get_terminal_size reads), so output is
deterministic whatever the test environment's terminal looks like.

Frame stream format (docs/fire_cli.md): each frame is a block of
`height // 2` lines; blocks are separated by a blank line (the frame
separator, "\n\n"); stdout ends with a newline.
"""

import os
import subprocess
import sys

HALF = "▀"  # U+2580

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CLI = os.path.join("src", "fire_cli.py")

# Small fixed grid: deterministic, and small enough that no terminal clamp
# can cut the flame (the CLI renders the whole grid whatever the canvas).
SMALL = ["--width", "6", "--height", "4"]

FRAME_LINES = 4 // 2  # --height 4 -> 2 character lines per frame


def _run(*args):
    """Run the CLI as a subprocess. Returns (returncode, stdout, stderr)."""
    env = dict(os.environ)
    env["COLUMNS"] = "80"  # pinned canvas: get_terminal_size prefers these
    env["LINES"] = "24"
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, CLI, *args],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        encoding="utf-8",
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _blocks(stdout_text):
    """Split a --frames stream into frame blocks on the frame separator."""
    assert stdout_text.endswith("\n"), "the frame stream must end with a newline"
    return stdout_text[:-1].split("\n\n")


# --- --frames: one frame ------------------------------------------------------


def test_frames_one_prints_one_frame_of_half_blocks():
    rc, out, err = _run("--frames", "1", *SMALL)
    assert rc == 0
    assert "Traceback" not in err, f"the CLI crashed: {err}"
    assert HALF in out
    blocks = _blocks(out)
    assert len(blocks) == 1
    assert len(blocks[0].split("\n")) == FRAME_LINES
    assert blocks[0].count(HALF) == 6 * FRAME_LINES


# --- --frames: exactly N blocks -----------------------------------------------


def test_frames_two_is_exactly_two_blocks_of_the_same_shape():
    rc1, out1, _ = _run("--frames", "1", *SMALL)
    rc2, out2, err2 = _run("--frames", "2", *SMALL)
    assert rc1 == 0 and rc2 == 0
    assert "Traceback" not in err2, f"the CLI crashed: {err2}"

    reference_lines = len(out1[:-1].split("\n"))  # --frames 1 -> one block
    blocks = _blocks(out2)
    assert len(blocks) == 2, "two frames must produce exactly two blocks"
    for block in blocks:
        assert len(block.split("\n")) == reference_lines == FRAME_LINES
        assert block.count(HALF) == 6 * FRAME_LINES
    assert blocks[0] != blocks[1], "consecutive frames of a fire are not identical"


# --- --frame N == frame N of the same seeded sequence (prefix property) -------


def test_frame_zero_is_the_first_block_of_frames_two():
    _, stream, _ = _run("--frames", "2", *SMALL)
    rc, single, err = _run("--frame", "0", *SMALL)
    assert rc == 0
    assert "Traceback" not in err, f"the CLI crashed: {err}"
    assert single == _blocks(stream)[0] + "\n"


def test_frame_one_is_the_last_block_of_frames_two():
    _, stream, _ = _run("--frames", "2", *SMALL)
    rc, single, err = _run("--frame", "1", *SMALL)
    assert rc == 0
    assert "Traceback" not in err, f"the CLI crashed: {err}"
    assert single == _blocks(stream)[1] + "\n"


def test_frame_n_is_the_last_block_of_frames_n_plus_one():
    # The general prefix property, at a non-default seed: --frame N equals the
    # last frame of --frames N+1 with the same seed/width/height.
    seed = ["--seed", "42"]
    for n in (0, 1, 2):
        _, stream, _ = _run("--frames", str(n + 1), *seed, *SMALL)
        rc, single, err = _run("--frame", str(n), *seed, *SMALL)
        assert rc == 0, f"--frame {n} failed: {err}"
        assert "Traceback" not in err, f"the CLI crashed: {err}"
        assert single == _blocks(stream)[-1] + "\n", f"prefix property broken at frame {n}"


# --- invalid inputs: argparse usage error, rc 2, no traceback -----------------


def test_invalid_values_reject_with_usage_error():
    cases = [
        ["--width", "0"],
        ["--height", "3"],  # odd: the renderer pairs rows
        ["--height", "0"],
        ["--fps", "0"],
        ["--frames", "0"],
        ["--frames", "-1"],
        ["--frame", "-1"],
    ]
    for args in cases:
        rc, out, err = _run(*args)
        flag = args[0]
        assert rc == 2, f"{' '.join(args)}: expected rc 2, got {rc} (stderr: {err})"
        assert "Traceback" not in err, f"{flag}: expected a usage error, got a traceback: {err}"
        assert flag in err, f"{flag}: the offending flag must be named on stderr: {err}"
        assert out == "", f"{flag}: nothing may be printed before a usage error"


def test_frames_and_frame_are_mutually_exclusive():
    rc, out, err = _run("--frames", "1", "--frame", "0", *SMALL)
    assert rc == 2
    assert "Traceback" not in err, f"expected a usage error, got a traceback: {err}"
    assert "--frames" in err and "--frame" in err
    assert out == ""


# --- determinism --------------------------------------------------------------


def test_two_runs_with_the_same_seed_are_byte_identical():
    rc_a, out_a, _ = _run("--frames", "2", "--seed", "42", *SMALL)
    rc_b, out_b, _ = _run("--frames", "2", "--seed", "42", *SMALL)
    assert rc_a == 0 and rc_b == 0
    assert out_a == out_b, "the same seed must produce byte-identical output"
    assert out_a != ""


def test_the_seed_changes_the_flame():
    # --seed is honored: the color stream and the simulation both derive from it.
    _, out_a, _ = _run("--frames", "2", "--seed", "42", *SMALL)
    _, out_b, _ = _run("--frames", "2", "--seed", "43", *SMALL)
    assert out_a != out_b, "different seeds must render different flames"
