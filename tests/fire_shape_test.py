"""Shape contract tests for src/fire.py (CC-111: flame tapers, not a block).

The flame must render as a cone/triangle: WIDE AT THE BASE, NARROWING TO
A POINT at the top, with a ragged silhouette and large blank areas around
it -- not a solid rectangular block of cells.
"""

import re

import fire  # src is on sys.path via pythonpath=src in run.sh

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
BLOCK = "\u2580"

W, H = 40, 12          # frame grid: 12 rows of flame body
SEED = 42             # fixed seed -> deterministic frames
TICKS = 60            # run to steady state


def _frame():
    """Steady-state frame (list of rendered rows, top to bottom) plus the
    simulation that produced it."""
    sim = fire.FireSim(W, H, seed=SEED)
    for _ in range(TICKS):
        sim.tick()
    frame = fire.render(sim)
    lines = frame.split("\n")
    assert len(lines) == H, f"frame has {len(lines)} rows, expected {H}"
    for line in lines:
        assert len(ANSI_RE.sub("", line)) == W, "row width != grid width"
    return lines, sim


def _visible(line):
    """Number of non-space (colored half-block) cells in a rendered row."""
    return ANSI_RE.sub("", line).count(BLOCK)


# --- taper -----------------------------------------------------------------------

def test_flame_tapers_top_is_half_of_base():
    """Mean non-space cells over the TOP 6 flame-body rows must be less
    than HALF the mean over the BOTTOM 6 flame-body rows: the flame
    narrows toward its tip instead of filling a rectangular block."""
    lines, _ = _frame()
    top_mean = sum(_visible(l) for l in lines[:6]) / 6.0
    bottom_mean = sum(_visible(l) for l in lines[-6:]) / 6.0
    assert bottom_mean > 0.0, "bottom flame-body rows are empty: no flame"
    assert top_mean < bottom_mean / 2.0, (
        f"flame does not taper: top-6 mean {top_mean:.1f} cells must be "
        f"under half the bottom-6 mean {bottom_mean:.1f}"
    )


def test_top_rows_mostly_blank():
    """At least 50% of the cells in the top 6 flame-body rows are blank
    (plain spaces): the flame dies out before reaching the top corners."""
    lines, _ = _frame()
    total = 6 * W
    blank = sum(len(ANSI_RE.sub("", l)) - _visible(l) for l in lines[:6])
    assert blank / total >= 0.50, (
        f"top 6 rows are {100.0 * (total - blank) / total:.1f}% filled; "
        f"at least 50% of those cells must be blank"
    )


# --- non-solid base ----------------------------------------------------------------

def test_base_row_is_not_solid():
    """Fewer than 90% of the base-row cells may be above the blank
    threshold: base-row injection must leave gaps (turbulence), so the
    base is a ragged line, not a solid one."""
    _, sim = _frame()
    base_row = sim.heat[sim.h - 1]
    lit = sum(1 for v in base_row if v > fire.BLANK_THRESHOLD)
    assert lit / len(base_row) < 0.90, (
        f"{100.0 * lit / len(base_row):.1f}% of the base row is lit; "
        f"fewer than 90% may be above the blank threshold"
    )


# --- cold is blank -----------------------------------------------------------------

def test_cold_heat_renders_blank():
    """Near-dead heat must render as a blank cell: below the blank
    threshold (at most 0.10) the palette returns None, so cold cells
    never fill the grid."""
    assert fire.BLANK_THRESHOLD <= 0.10, (
        f"blank threshold {fire.BLANK_THRESHOLD} exceeds the 0.10 limit"
    )
    assert fire.palette(0.05, False, fire.BLANK_THRESHOLD) is None, (
        "heat 0.05 below the blank threshold must render blank (None)"
    )
    assert fire.palette(0.0, False, fire.BLANK_THRESHOLD) is None, (
        "zero heat must render blank (None)"
    )
