"""TASK-STANOK-CC-272: --frames N and --frame K share one frame sequence.

Characterization tests: they pin the CURRENT, verified behaviour — for a fixed
seed and dimensions, `--frame K` is byte-identical to frame K inside
`--frames K+1`. Both flags drive the same seeded simulation
(`simulate(seed, w, h, ticks)`; `--frame K` runs `simulate(..., K+1)` and
renders `[-1]`), and the colour-jitter stream is derived from the seed per
frame, so rendering one frame never perturbs the heat field.

The CLI runs as a subprocess with stdin=DEVNULL — the same technique as the
`_cli` helper in tests/fire_test.py, re-declared here so this file is
self-contained. Fixed `--seed 7 --width 6 --height 3` keeps the output
deterministic and below any terminal clamp. Each frame is emitted as one
write ending in "\n", so prefix/suffix string comparisons are exact — no
frame splitting needed.
"""

import os
import subprocess
import sys
from pathlib import Path

import fire

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_FIRE = REPO_ROOT / "src" / "fire.py"

SEED = ("--seed", "7")
SIZE = ("--width", "6", "--height", "3")


def _cli(*args):
    env = os.environ.copy()
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return subprocess.run(
        [sys.executable, str(SRC_FIRE), *SEED, *SIZE, *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=30,
    )


def _stdout_ok(*args):
    result = _cli(*args)
    assert result.returncode == 0, (
        f"rc={result.returncode}\nstderr: {result.stderr!r}"
    )
    assert result.stdout.strip(), f"no frame on stdout for args={args!r}"
    return result.stdout


# --- CLI level: one shared frame sequence ----------------------------------


def test_frame_zero_is_byte_identical_to_frames_one():
    assert _stdout_ok("--frame", "0") == _stdout_ok("--frames", "1")


def test_frames_two_extends_frames_one():
    """Frame 0 of `--frames 2` is exactly the whole output of `--frames 1`."""
    assert _stdout_ok("--frames", "2").startswith(_stdout_ok("--frames", "1"))


def test_frames_two_ends_with_frame_one():
    """Frame 1 of `--frames 2` is exactly the whole output of `--frame 1`."""
    assert _stdout_ok("--frames", "2").endswith(_stdout_ok("--frame", "1"))


# --- API level: the simulation sequence is stable regardless of tick count --


def test_simulate_returns_exactly_the_requested_ticks():
    assert len(fire.simulate(7, 6, 3, 3)) == 3


def test_simulate_frames_do_not_depend_on_tick_count():
    """Frame K from a longer run equals frame K from the minimal run."""
    assert fire.simulate(7, 6, 3, 3)[1] == fire.simulate(7, 6, 3, 2)[-1]
