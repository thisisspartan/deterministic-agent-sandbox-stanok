"""Accept fixture — host-authored contract oracle (frozen by the contract
lock; the machine must not edit it).

PROVENANCE of every expected literal and number: SPEC-FIRE-2026-10-22
(SPEC-F), sections C1, C2, C3, C5, C6, C7, C8, Q6. Program under test:
src/fire.py, invoked as a real subprocess with real arguments (black-box).

Covers C1..C3, C5..C8 and validation (C2/Q6). Interactive/PTY claims C9..C11
are NOT here — tests/fire_terminal_test.py owns them.
"""

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
FIRE = str(REPO / "src" / "fire.py")

# SPEC-F C5: PALETTE = " .:-=+*#%@" (10 chars)
PALETTE = " .:-=+*#%@"


def _run(*args):
    return subprocess.run([sys.executable, FIRE, *args],
                          capture_output=True, text=True)


def _parse_frames(raw, frames, height, width):
    """C6 structural contract: exactly `frames` frames separated by exactly
    one empty line; each frame exactly `height` lines of exactly `width`
    palette characters; zero control characters except '\n'; output ends with
    exactly one '\n' and no trailing empty line."""
    assert raw.endswith("\n"), "output must end with exactly one '\\n'"
    assert not raw.endswith("\n\n"), "no trailing empty line allowed"
    for ch in raw:
        assert ch == "\n" or ch in PALETTE, f"illegal character {ch!r}"
    lines = raw.split("\n")
    assert lines[-1] == ""  # artifact of the final single '\n'
    body = lines[:-1]
    expected = frames * height + (frames - 1)
    assert len(body) == expected, (
        f"expected {expected} content/separator lines, got {len(body)}")
    out = []
    for i in range(frames):
        start = i * (height + 1)
        block = body[start:start + height]
        assert len(block) == height
        for line in block:
            assert len(line) == width, f"line width {len(line)} != {width}"
        out.append(block)
        if i < frames - 1:
            assert body[start + height] == "", (
                "frame separator must be exactly one empty line")
    return out


def _energy(line):
    # SPEC-F C8a: energy of a character = its index in PALETTE
    return sum(PALETTE.index(ch) for ch in line)


# ---------------------------------------------------------------- C1 --help
def test_help_goes_to_stdout():
    r = _run("--help")
    assert r.returncode == 0, "C1: --help must exit 0"
    for flag in ("--frames", "--seed", "--no-color"):
        assert flag in r.stdout, f"C1: usage must mention {flag}"
    assert r.stderr == "", "C1: --help must keep stderr empty"


# ------------------------------------------------- C1/C6 batch structure
def test_batch_defaults():
    # C1 defaults: width 40, height 12 (SPEC-F C1/Q6)
    r = _run("--frames", "2")
    assert r.returncode == 0
    assert r.stderr == ""
    _parse_frames(r.stdout, frames=2, height=12, width=40)


def test_batch_custom_dims_and_seed():
    r = _run("--width", "20", "--height", "6", "--frames", "2", "--seed", "7")
    assert r.returncode == 0
    _parse_frames(r.stdout, frames=2, height=6, width=20)


# ------------------------------------------------------------ C3 determinism
def test_same_seed_identical_output():
    argv = ("--width", "12", "--height", "8", "--frames", "3", "--seed", "42")
    a = _run(*argv)
    b = _run(*argv)
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout != "", "output must not be empty"
    assert a.stdout == b.stdout, "C3: same seed must produce byte-identical stdout"


# ------------------------------------------------------------- C5/C7 bottom
def test_bottom_row_always_hot():
    # C4 seeds EVERY bottom cell in randint(224,255) -> indices 8..9 ("%@")
    # for every frame; C5 maps heat 224..255 to '%@' only. C7 requires at
    # least one '%@' per bottom line; C4+C5 imply the full line — asserted.
    r = _run("--width", "20", "--height", "6", "--frames", "2", "--seed", "3")
    assert r.returncode == 0
    frames = _parse_frames(r.stdout, frames=2, height=6, width=20)
    for idx, frame in enumerate(frames):
        bottom = frame[-1]
        assert set(bottom) <= {"%", "@"}, (
            f"C5/C7: frame {idx} bottom line {bottom!r} outside '%@'")
        assert any(ch in "%@" for ch in bottom), (
            f"C7: frame {idx} bottom line has no hot character")


# --------------------------------------------------------------- C8a gradient
def test_heat_concentrates_at_bottom():
    # C8a: window 40x15, frames 6; every frame with index >= 2 must have
    # sum_energy(bottom third) > 1.5 * sum_energy(top third).
    r = _run("--width", "40", "--height", "15", "--frames", "6", "--seed", "3")
    assert r.returncode == 0
    frames = _parse_frames(r.stdout, frames=6, height=15, width=40)
    for idx in range(2, 6):
        frame = frames[idx]
        top = sum(_energy(line) for line in frame[0:5])
        bottom = sum(_energy(line) for line in frame[10:15])
        assert bottom > 1.5 * top, (
            f"C8a: frame {idx} bottom={bottom} not > 1.5*top={top}")


# -------------------------------------------------------------- C8b darkness
def test_top_row_is_dark():
    # C8b: window 24x12, frames 3: row 0 of EVERY frame is all spaces.
    # Guaranteed by C4: max heat at 11 levels above the seeded bottom is
    # 255 - 21*11 = 24 < 26 -> palette index 0 (' '). Catches a palette
    # shifted by +1 and uniform noise.
    r = _run("--width", "24", "--height", "12", "--frames", "3", "--seed", "5")
    assert r.returncode == 0
    frames = _parse_frames(r.stdout, frames=3, height=12, width=24)
    for idx, frame in enumerate(frames):
        assert frame[0] == " " * 24, (
            f"C8b: frame {idx} top row not dark: {frame[0]!r}")


# ------------------------------------------------------------- C2/Q6 validation
_INVALID = [
    pytest.param(["--frames=1", "--width=7"], id="width-below-min"),
    pytest.param(["--frames=1", "--width=257"], id="width-above-max"),
    pytest.param(["--frames=1", "--height=4"], id="height-below-min"),
    pytest.param(["--frames=1", "--height=121"], id="height-above-max"),
    pytest.param(["--frames=0"], id="frames-zero"),
    pytest.param(["--frames=1001"], id="frames-above-max"),
    pytest.param(["--frames=1", "--fps=0"], id="fps-zero"),
    pytest.param(["--frames=1", "--fps=61"], id="fps-above-max"),
    pytest.param(["--frames=1", "--seed=-1"], id="seed-negative"),
    pytest.param(["--frames=1", "--width=abc"], id="width-not-int"),
    pytest.param([], id="frames-missing"),
]


@pytest.mark.parametrize("argv", _INVALID)
def test_invalid_arguments_rejected(argv):
    r = _run(*argv)
    assert r.returncode == 2, f"C2: {argv} must exit 2, got {r.returncode}"
    assert r.stderr != "", f"C2: {argv} must report on stderr"
    assert r.stdout == "", f"C2: {argv} must leave stdout empty"


# ------------------------------------------------- Q4: batch never colored
def test_batch_output_has_no_control_chars_beyond_newline():
    # C6 forbids control characters other than '\n' in batch output; a color
    # escape in batch is therefore a contract violation (SPEC-F Q4).
    r = _run("--width", "10", "--height", "6", "--frames", "1", "--seed", "0")
    assert r.returncode == 0
    assert "\x1b" not in r.stdout, "Q4/C6: batch output must contain no escapes"
