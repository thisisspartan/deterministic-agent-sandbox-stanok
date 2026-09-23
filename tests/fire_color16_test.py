"""16-color fallback contract tests for src/fire.py (CC-116).

For terminals that drop BOTH 24-bit truecolor (``\\x1b[38;2;...``) and
256-color (``\\x1b[38;5;N``, N>15) escapes, the last-resort fallback is a
16-color mode using only the basic ANSI palette (indices 0..15,
understood by every terminal).

- ``rgb_to_16``: nearest of the 16 basic ANSI colors, deterministic,
  returns an int in 0..15.
- ``render(sim, color_mode="16")``: colored cell =
  ``\\x1b[38;5;Nm\\x1b[0m\\u2580`` with N in 0..15; blank cell = space.
- CLI ``--color 16`` is accepted.

All other color modes keep their exact behavior (regression guards below).

Run via:  bash scripts/run.sh test tests/fire_color16_test.py
"""

import re
import subprocess
import sys

import fire  # src is on sys.path via pythonpath=src in run.sh

# One 16-mode cell: an escape-indexed (0..15) half-block or a plain space.
CELL16_RE = re.compile(r"(\x1b\[38;5;([0-9]+)m\x1b\[0m\u2580| )")
# One truecolor cell (default renderer) or a plain space.
CELLTC_RE = re.compile(r"(\x1b\[38;2;\d+;\d+;\d+m\x1b\[0m\u2580| )")
# One 256-mode cell or a plain space.
CELL256_RE = re.compile(r"(\x1b\[38;5;(\d+)m\x1b\[0m\u2580| )")
BLOCK = "\u2580"
SEED = 42
TICKS = 30


def _render16(w=24, h=12, seed=SEED, ticks=TICKS):
    """Frame rendered in 16-color mode after ``ticks`` ticks."""
    sim = fire.FireSim(w, h, seed=seed)
    for _ in range(ticks):
        sim.tick()
    return fire.render(sim, color_mode="16")


# --- rgb_to_16 ---------------------------------------------------------------

def test_rgb_to_16_black_is_0():
    assert fire.rgb_to_16((0, 0, 0)) == 0


def test_rgb_to_16_red_is_red_family():
    """(255,0,0) is nearest the basic red: index 1 or the bright red 9."""
    assert fire.rgb_to_16((255, 0, 0)) in (1, 9)


def test_rgb_to_16_blue_is_blue_family():
    """(0,0,255) is nearest the basic blue: index 4 or the bright blue 12."""
    assert fire.rgb_to_16((0, 0, 255)) in (4, 12)


def test_rgb_to_16_white_is_white_family():
    """(255,255,255) is nearest the basic white: index 7 or bright 15."""
    assert fire.rgb_to_16((255, 255, 255)) in (7, 15)


def test_rgb_to_16_range_and_determinism():
    """Every plausible palette rgb maps to an int in 0..15 and the
    mapping is deterministic (same input -> same output)."""
    sample = ((0, 0, 0), (255, 0, 0), (0, 0, 255), (255, 255, 255),
              (1, 1, 1), (90, 15, 8), (160, 30, 10), (220, 60, 20),
              (255, 140, 0), (255, 220, 80), (255, 255, 240),
              (25, 45, 90), (80, 130, 220), (150, 200, 255),
              (60, 60, 65), (200, 100, 50), (0, 196, 0), (196, 196, 0))
    first = {}
    for rgb in sample:
        idx = fire.rgb_to_16(rgb)
        assert isinstance(idx, int)
        assert 0 <= idx <= 15, f"rgb_to_16({rgb}) = {idx} out of range"
        first[rgb] = idx
    for rgb in sample:
        assert fire.rgb_to_16(rgb) == first[rgb], (
            f"rgb_to_16({rgb}) is not deterministic"
        )


# --- renderer: 16 mode ---------------------------------------------------------

def test_render_16_mode_cell_alignment():
    """Every line of a 16-mode frame is exactly cell-aligned runs of
    16-color cells or spaces, every index in 0..15, and at least one
    colored cell is present."""
    w, h = 24, 12
    frame = _render16(w, h)
    assert "\x1b[38;2;" not in frame, "16 mode must not emit truecolor escapes"
    lines = frame.split("\n")
    assert len(lines) == h
    saw_block = False
    for line in lines:
        pos = 0
        cells = 0
        for m in CELL16_RE.finditer(line):
            assert m.start() == pos, "16-mode frame is not cell-aligned"
            pos = m.end()
            cells += 1
            idx = m.group(2)
            if idx is not None:
                saw_block = True
                assert 0 <= int(idx) <= 15, f"16-mode index {idx} out of range"
        assert pos == len(line), "trailing garbage in 16-mode line"
        assert cells == w, f"16-mode line has {cells} cells, expected {w}"
    assert saw_block, "16-mode frame has no colored cells"


def test_render_16_mode_is_deterministic():
    a = fire.FireSim(24, 12, seed=42)
    b = fire.FireSim(24, 12, seed=42)
    for _ in range(8):
        a.tick()
        b.tick()
    assert fire.render(a, color_mode="16") == fire.render(b, color_mode="16")


def test_render_default_still_truecolor():
    """Regression guard: the default renderer keeps emitting 24-bit
    truecolor escapes, never 16-mode escape indices."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    lines = frame.split("\n")
    assert len(lines) == 12
    for line in lines:
        pos = 0
        for m in CELLTC_RE.finditer(line):
            assert m.start() == pos, "default frame is not cell-aligned"
            pos = m.end()
        assert pos == len(line), "trailing garbage in default-mode line"
    assert "\x1b[38;2;" in frame
    assert BLOCK in frame


def test_render_256_still_256():
    """Regression guard: 256 mode is unchanged -- 256 cell regex, indices
    0..255."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="256")
    assert "\x1b[38;2;" not in frame
    saw_block = False
    for line in frame.split("\n"):
        pos = 0
        for m in CELL256_RE.finditer(line):
            assert m.start() == pos, "256-mode frame is not cell-aligned"
            pos = m.end()
            idx = m.group(2)
            if idx is not None:
                saw_block = True
                assert 0 <= int(idx) <= 255
        assert pos == len(line), "trailing garbage in 256-mode line"
    assert saw_block


# --- CLI -----------------------------------------------------------------------

def test_cli_color_16_accepted():
    """``python3 src/fire.py --color 16 --frames 1 --width 20 --height 8``
    exits 0, emits 16-color escapes (index 0..15), and NO truecolor
    escapes."""
    proc = subprocess.run(
        ["python3", "src/fire.py", "--color", "16",
         "--frames", "1", "--width", "20", "--height", "8"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"rc={proc.returncode} stderr={proc.stderr}"
    out = proc.stdout
    assert "\x1b[38;2;" not in out, "--color 16 must not emit truecolor escapes"
    m = re.search(r"\x1b\[38;5;([0-9]+)m", out)
    assert m is not None, "--color 16 output has no \\x1b[38;5; escape"
    idx = int(m.group(1))
    assert 0 <= idx <= 15, f"--color 16 emitted index {idx} out of 0..15"
