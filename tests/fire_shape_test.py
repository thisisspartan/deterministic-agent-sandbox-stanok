"""Flame-shape contract tests for src/fire_color.py (ticket TASK-STANOK-CC-105).

The rendered flame must be WIDE AT THE BASE and NARROW TO A POINT at the top
(cone/triangle silhouette, ragged edges), with large blank areas around it —
not a solid rectangular block.

Deterministic setup per the ticket: new_state(40, 18, 42) + 30 step() calls,
frame = render(st). The bottom `height` rows of the frame are the flame body
(the frame is exactly grid_height rows; grid row 0 = base = bottom frame row).
"""
import re

import fire_color as fc

WIDTH, HEIGHT, SEED = 40, 18, 42
BLANK = 0.10  # palette() must return None below this threshold

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ ]?[A-Za-z]")


def _frame():
    st = fc.new_state(WIDTH, HEIGHT, SEED)
    for _ in range(30):
        st = fc.step(st)
    # strip ANSI escapes: one visible character per cell
    return st, [ANSI_RE.sub("", line) for line in fc.render(st).split("\n")]


def _non_space(line):
    """Non-space character count of a stripped frame line (one char per cell)."""
    return sum(1 for ch in line if ch != " ")


def test_flame_tapers_wide_at_base_narrow_at_top():
    """Mean non-space cells over the TOP 6 body rows < half of the BOTTOM 6."""
    _, lines = _frame()
    top = lines[:6]
    bottom = lines[-6:]
    top_mean = sum(_non_space(l) for l in top) / len(top)
    bottom_mean = sum(_non_space(l) for l in bottom) / len(bottom)
    assert bottom_mean > 0, "flame body must exist near the base"
    assert top_mean < 0.5 * bottom_mean, (
        "flame must taper to a point at the top (top6=%.1f bottom6=%.1f)"
        % (top_mean, bottom_mean)
    )


def test_top_of_flame_is_mostly_blank():
    """At least 50% of the cells in the top 6 body rows are spaces."""
    _, lines = _frame()
    top = lines[:6]
    total = len(top) * WIDTH
    spaces = sum(WIDTH - _non_space(l) for l in top)
    assert spaces >= 0.5 * total, (
        "top 6 flame-body rows must be mostly blank (%.0f%% spaces)"
        % (100.0 * spaces / total)
    )


def test_base_row_is_not_solid():
    """Fewer than 90% of base-row heat cells are above the blank threshold."""
    st, _ = _frame()
    above = sum(1 for v in st.heat[0] if v > BLANK)
    assert above < 0.9 * WIDTH, (
        "base-row injection must leave turbulence gaps (%d/%d above threshold)"
        % (above, WIDTH)
    )


def test_cold_heat_is_blank():
    """Below the blank threshold the palette yields no cell at all."""
    assert fc.palette(0.05, False, 0.0) is None
    assert fc.palette(0.0, False, 0.0) is None
    # and just above the threshold (<= 0.10) a cell is produced
    assert fc.palette(0.15, False, 0.0) is not None
