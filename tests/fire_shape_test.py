"""Shape contract tests for src/fire.py (CC-111: flame must taper).

Run via:  bash scripts/run.sh test tests/fire_shape_test.py

The defect under test: the fire used to render as a SOLID RECTANGULAR
BLOCK of half-block cells. This file asserts that the flame is a
tapering cone instead: WIDE AT THE BASE, NARROWING TOWARD A POINT at the
top, with a mostly-blank crown, ragged (non-solid) base injection, and a
palette that blanks cold heat.

All checks use the module's public API exactly as the other contract
tests do: seeded FireSim, fixed ticks, fire.render(sim), fire.palette().
"""

import re

import fire  # src is on sys.path via pythonpath=src in run.sh

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

WIDTH = 30
HEIGHT = 16
SEED = 42
TICKS = 30


def _steady_state():
    """Simulate a fixed seed to a settled flame and return (sim, frame)."""
    sim = fire.FireSim(WIDTH, HEIGHT, seed=SEED)
    for _ in range(TICKS):
        sim.tick()
    return sim, fire.render(sim)


def _visible_cells(frame):
    """Rendered frame -> list of per-row counts of non-space (colored)
    cells; the whole frame is the flame body (height rows)."""
    counts = []
    for line in frame.split("\n"):
        visible = ANSI_RE.sub("", line)
        counts.append(len(visible) - visible.count(" "))
    return counts


# --- taper: wide base, narrow top ------------------------------------------------

def test_flame_tapers_wide_at_base_narrow_at_top():
    _, frame = _steady_state()
    counts = _visible_cells(frame)
    assert len(counts) == HEIGHT
    top6 = sum(counts[:6]) / 6.0
    bottom6 = sum(counts[-6:]) / 6.0
    assert bottom6 > 0, "flame body has no visible base rows"
    assert top6 < bottom6 / 2, (
        f"flame does not taper: mean of TOP 6 rows {top6:.2f} visible cells "
        f"must be < half of the BOTTOM 6 rows mean {bottom6:.2f}"
    )


# --- blank crown -------------------------------------------------------------------

def test_top_rows_of_flame_body_are_mostly_blank():
    _, frame = _steady_state()
    counts = _visible_cells(frame)
    lit = sum(counts[:6])
    assert lit * 2 <= 6 * WIDTH, (
        f"top 6 flame-body rows are {lit}/{6 * WIDTH} lit; at least 50% "
        f"must be blank spaces"
    )


def test_topmost_heat_row_is_mostly_cold():
    sim, _ = _steady_state()
    top = sim.heat[0]
    lit = sum(1 for v in top if v >= fire.BLANK_THRESHOLD)
    assert lit < WIDTH / 2, (
        f"heat row 0 has {lit}/{WIDTH} cells above the blank threshold "
        f"({fire.BLANK_THRESHOLD}); the crown must be mostly cold"
    )


# --- non-solid base ------------------------------------------------------------------

def test_base_row_is_not_solid():
    sim, _ = _steady_state()
    base = sim.heat[sim.h - 1]
    lit = sum(1 for v in base if v >= fire.BLANK_THRESHOLD)
    assert lit < 0.9 * len(base), (
        f"base row has {lit}/{len(base)} cells above the blank threshold; "
        f"base injection must leave gaps (< 90% lit)"
    )


# --- cold heat is blank ---------------------------------------------------------------

def test_palette_blanks_cold_heat():
    # The renderer's blank threshold is at most 0.10: anything below it
    # is a blank cell (no ANSI escape at all).
    assert fire.palette(0.05, False, 0.10) is None
    assert fire.palette(0.0, False, 0.10) is None
    # ...and hot flame heat still colors.
    assert fire.palette(0.5, False, 0.10) is not None
