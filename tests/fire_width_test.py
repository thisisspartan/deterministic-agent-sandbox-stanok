"""Flame-width contract tests for src/fire.py (CC-114: flame, not mountain).

The flame must be a central cone that scales with the terminal:

- base injection only in the central third of the width, with internal
  gaps (a ragged band, not a solid one);
- the colored span of every bottom-6 row is capped at half the width;
- on a wide terminal the flame scales with the width, it does not fill it.
"""

import re

import fire  # src is on sys.path via pythonpath=src in run.sh

# One cell: a truecolor half-block or a plain space (default renderer).
CELL_RE = re.compile(r"(\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[0m▀| )")
SEED = 42
TICKS = 30


def _grid(w, h, seed=SEED, ticks=TICKS):
    """Frame rendered after ``ticks`` ticks -> list of rows (top to
    bottom); each cell is True (colored) or False (blank)."""
    sim = fire.FireSim(w, h, seed=seed)
    for _ in range(ticks):
        sim.tick()
    grid = []
    for line in fire.render(sim).split("\n"):
        row = []
        pos = 0
        for m in CELL_RE.finditer(line):
            assert m.start() == pos, "frame is not cell-aligned"
            pos = m.end()
            row.append(m.group(2) is not None)
        assert pos == len(line), "trailing garbage in line"
        grid.append(row)
    return grid


def _span(row):
    """(leftmost, rightmost) colored column of a row, or None if blank."""
    lit = [x for x, c in enumerate(row) if c]
    if not lit:
        return None
    return lit[0], lit[-1]


# --- 80x24: central base, half-width span cap, ragged base ----------------------

def test_base_row_confined_to_central_third():
    """At 80x24 (seed 42, 30 ticks) the base row's leftmost colored cell
    sits at column >= 80//3 - 2 and the rightmost at column <= 2*80//3 + 2:
    the flame is a central cone, not a mountain reaching the edges."""
    grid = _grid(80, 24)
    lo, hi = _span(grid[23])
    assert lo is not None, "base row is empty: no flame at all"
    assert lo >= 80 // 3 - 2, (
        f"leftmost base cell at col {lo}; must be >= {80 // 3 - 2}"
    )
    assert hi <= 2 * 80 // 3 + 2, (
        f"rightmost base cell at col {hi}; must be <= {2 * 80 // 3 + 2}"
    )


def test_bottom_six_rows_span_at_most_half_width():
    """At 80x24 (seed 42, 30 ticks) every one of the bottom 6 rows has a
    colored span (rightmost - leftmost + 1) of at most 80//2: proper flame
    proportions, the base is not nearly-solid full-width."""
    grid = _grid(80, 24)
    for y in range(24 - 6, 24):
        span = _span(grid[y])
        if span is None:
            continue  # fully blank row: span 0, trivially capped
        lo, hi = span
        assert hi - lo + 1 <= 80 // 2, (
            f"row {y} colored span {hi - lo + 1} exceeds 80//2 = {80 // 2}"
        )


def test_base_row_has_internal_gaps():
    """At 80x24 (seed 42, 30 ticks) the base row's span is a ragged band,
    not a solid one: within the leftmost..rightmost colored cells, at
    least 25% are blank (turbulence inside the central third)."""
    grid = _grid(80, 24)
    lo, hi = _span(grid[23])
    assert lo is not None
    span = hi - lo + 1
    blank = sum(1 for x in range(lo, hi + 1) if not grid[23][x])
    assert blank / span >= 0.25, (
        f"only {100.0 * blank / span:.1f}% of the base span is blank; "
        f"at least 25% must be (span {span}, blank {blank})"
    )


# --- 130x24: wide terminal, the flame scales, it does not fill -------------------

def test_wide_terminal_bottom_six_rows_span_capped():
    """At 130x24 (seed 42, 30 ticks) every one of the bottom 6 rows has a
    colored span of at most 130//2: on a wide terminal the flame scales
    with the width instead of stretching to fill it."""
    grid = _grid(130, 24)
    lo, hi = _span(grid[23])
    assert lo is not None, "wide-terminal base row is empty: no flame at all"
    for y in range(24 - 6, 24):
        span = _span(grid[y])
        if span is None:
            continue
        lo, hi = span
        assert hi - lo + 1 <= 130 // 2, (
            f"row {y} colored span {hi - lo + 1} exceeds 130//2 = {130 // 2}"
        )
