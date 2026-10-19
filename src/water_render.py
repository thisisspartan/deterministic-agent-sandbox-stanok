"""water_render — pure renderer: frame state -> ANSI-truecolor frame (CC-300).

stdlib only; the engine is NOT imported — the state is read duck-typed
(`heights`, `light`, `foam`, `glint`). render_frame(state, width, height)
returns exactly `height` lines joined by "\\n", no trailing newline: line 0
sky, line 1 the waterline (half-block cells), lines >= 2 depth rows. Pure:
the state is never mutated; identical input -> byte-identical output.
See docs/water_render.md.
"""

from __future__ import annotations

import math

MIN_WIDTH = 12
MIN_HEIGHT = 4

# Depth ramp geometry (R2): r in [0, 8] maps to DEPTH_BANDS bands over DEEP.
DEPTH_SPAN = 8
DEPTH_BANDS = 4

# Waterline glyph selection (R3): f = frac(height + 1.0); f >= 0.5 is the crest.
CREST_FRACTION = 0.5


def _rgb(literal: str) -> tuple:
    """Hex literal -> (r, g, b)."""
    return tuple(int(literal[i:i + 2], 16) for i in (1, 3, 5))


# Palette (R1): exactly eight stops, in this order — relative luminance
# strictly increases P0 -> P1 -> ... -> P5 -> FOAM -> GLINT.
P0 = _rgb("#03121e")
P1 = _rgb("#07294a")
P2 = _rgb("#0d4f70")
P3 = _rgb("#16799c")
P4 = _rgb("#27a3c0")
P5 = _rgb("#7fd4e0")
FOAM = _rgb("#e9f6fa")
GLINT = _rgb("#ffffff")

# Depth ramp (R2): P4 at the surface, P0 at r >= 8.
_DEEP = [P4, P3, P2, P1, P0]

_TOP = "▀"  # ▀
_BOTTOM = "▄"  # ▄
_RESET = "\x1b[0m"
_SPACE = " "


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _mix(a, b, u) -> tuple:
    """Channel-wise blend at u in [0, 1]; half-up rounding per channel."""
    return tuple(math.floor(a_c + (b_c - a_c) * u + 0.5) for a_c, b_c in zip(a, b))


def depth_color(r) -> tuple:
    """Color of the water `r` cells below the surface (R2).

    r = 0 is the cell directly under the surface; r >= 8 clamps to P0.
    Neighbouring depths differ by at most 32 per channel (anti-banding).
    """
    r = min(r, DEPTH_SPAN)
    position = r / DEPTH_SPAN * DEPTH_BANDS
    s = min(DEPTH_BANDS - 1, int(position))
    return _mix(_DEEP[s], _DEEP[s + 1], position - s)


def water_color(l: float) -> tuple:
    """Surface color at light level l (R3): P4 at l = 0, P5 at l = 1."""
    return _mix(P4, P5, _clamp01(l))


def render_frame(state, width: int, height: int) -> str:
    """Render the state as a truecolor frame (see docs/water_render.md).

    width < 12 or height < 4 -> ValueError. The state is read duck-typed and
    never mutated.
    """
    if width < MIN_WIDTH:
        raise ValueError(f"width must be >= {MIN_WIDTH}, got {width}")
    if height < MIN_HEIGHT:
        raise ValueError(f"height must be >= {MIN_HEIGHT}, got {height}")
    lines = []
    for row in range(height):
        if row == 0:
            cells = [_cell(P0, P0, _SPACE) for _ in range(width)]
        elif row == 1:
            cells = [_waterline_cell(state, x) for x in range(width)]
        else:
            deep = depth_color(row - 1)
            cells = [_cell(deep, deep, _SPACE) for _ in range(width)]
        lines.append("".join(cells) + _RESET)
    return "\n".join(lines)


def _waterline_cell(state, x: int) -> str:
    """One waterline cell: the surface half-block of column x (R3)."""
    fg = water_color(state.light[x])
    if state.foam[x]:
        fg = FOAM
    if state.glint[x]:  # glint is stronger than foam
        fg = GLINT
    if _is_crest(state.heights[x]):
        return _cell(fg, depth_color(1), _TOP)
    return _cell(fg, P0, _BOTTOM)


def _is_crest(height: float) -> bool:
    """True when the surface in this column shows its upper half."""
    shifted = height + 1.0
    return (shifted - math.floor(shifted)) >= CREST_FRACTION


def _sgr(fg, bg) -> str:
    return f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"


def _cell(fg, bg, glyph: str) -> str:
    return _sgr(fg, bg) + glyph
