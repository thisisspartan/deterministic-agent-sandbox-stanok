"""fire_render — pure DOOM-palette fire renderer (CC-288).

Pure functions: heat grid -> ANSI frame string. No I/O, no global mutable
state, and NO import of src/fire_engine — the renderer takes plain data
(list[list[int]], int heat 0..255).

A frame is exactly len(grid) lines joined by "\\r\\n" with no trailing line
break and no home/clear/cursor sequences (that is the CLI's job). Each cell
is an SGR truecolor background plus a space: "\\x1b[48;2;R;G;Bm ".

Contract documentation: docs/fire_render.md.
"""
from __future__ import annotations

from typing import Sequence

CELL_PREFIX = "\x1b[48;2;"  # SGR truecolor background prefix
CELL_PIXEL = " "  # U+0020 SPACE — the painted pixel of a cell
LINE_SEPARATOR = "\r\n"

# DOOM fire palette anchors: heat -> (r, g, b), linearly interpolated
# between neighbors. R and G are non-decreasing across the anchors, so
# every interpolated ramp is monotonic.
_ANCHORS = (
    (0, (0, 0, 0)),
    (64, (135, 0, 0)),
    (128, (255, 60, 0)),
    (192, (255, 160, 0)),
    (255, (255, 255, 0)),
)


def palette(heat: int) -> tuple[int, int, int]:
    """DOOM-palette color for a heat value.

    Input is clamped to [0, 255] — negative and >255 never raise. The
    color is a linear interpolation between the two nearest anchors
    (integer round-half-up, so anchors reproduce exactly and the R and G
    components are non-decreasing in heat).
    """
    h = max(0, min(255, int(heat)))
    for i in range(len(_ANCHORS) - 1):
        lo, lo_color = _ANCHORS[i]
        hi, hi_color = _ANCHORS[i + 1]
        if h <= hi:
            span = hi - lo
            t = h - lo
            return tuple(
                lo_c + (2 * (hi_c - lo_c) * t + span) // (2 * span)
                for lo_c, hi_c in zip(lo_color, hi_color)
            )
    return _ANCHORS[-1][1]  # unreachable: h <= 255 == last anchor


def render(grid: Sequence[Sequence[int]]) -> str:
    """Heat grid -> ANSI frame string.

    grid: sequence of equal-length rows of int heat (equal row length is
    a precondition, not checked). The frame has exactly len(grid) lines
    joined by "\\r\\n", no trailing line break, no home/clear/cursor
    sequences; each line has exactly len(row) cells of the form
    "\\x1b[48;2;R;G;Bm ". The input is never mutated; the output depends
    only on the grid (no hidden state).
    """
    lines = []
    for row in grid:
        cells = []
        for heat in row:
            r, g, b = palette(heat)
            cells.append(f"{CELL_PREFIX}{r};{g};{b}m{CELL_PIXEL}")
        lines.append("".join(cells))
    return LINE_SEPARATOR.join(lines)
