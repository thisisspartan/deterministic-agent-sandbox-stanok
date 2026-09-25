"""TrueColor (256-entry) palette generator for fire effects.

A palette is a list of exactly 256 ``(r, g, b)`` tuples with integer
channels in ``[0..255]``. Index 0 is strictly ``(0, 0, 0)`` (cold /
background). Colors are obtained by piecewise linear interpolation
between control points:

    index 0    (0, 0, 0)        black / background
    index 32   (140, 0, 0)      dark red
    index 96   (255, 100, 0)    bright orange
    index 180  (255, 220, 50)   golden yellow
    index 240  (255, 255, 230)  white
    index 255  (220, 240, 255)  white-blue hot sparks

Brightness (``r + g + b``) is monotonically non-decreasing from index 0
to 240; the final 241..255 segment cools slightly toward blue sparks.
"""

from __future__ import annotations

from typing import List, Tuple

RGB = Tuple[int, int, int]
Node = Tuple[int, RGB]

_FIRE_NODES: Tuple[Node, ...] = (
    (0, (0, 0, 0)),
    (32, (140, 0, 0)),
    (96, (255, 100, 0)),
    (180, (255, 220, 50)),
    (240, (255, 255, 230)),
    (255, (220, 240, 255)),
)

_BLUE_FIRE_NODES: Tuple[Node, ...] = (
    (0, (0, 0, 0)),
    (32, (0, 0, 140)),
    (96, (0, 100, 255)),
    (180, (50, 220, 255)),
    (240, (230, 255, 255)),
    (255, (200, 230, 255)),
)


def _build_palette(nodes: Tuple[Node, ...]) -> List[RGB]:
    """Piecewise-linear interpolation over ``nodes`` -> 256 RGB tuples."""
    palette: List[RGB] = []
    for (i0, c0), (i1, c1) in zip(nodes, nodes[1:]):
        span = i1 - i0
        first = i0 if not palette else i0 + 1
        for i in range(first, i1 + 1):
            t = (i - i0) / span
            palette.append(
                (
                    round(c0[0] + (c1[0] - c0[0]) * t),
                    round(c0[1] + (c1[1] - c0[1]) * t),
                    round(c0[2] + (c1[2] - c0[2]) * t),
                )
            )
    return palette


def generate_fire_palette() -> List[RGB]:
    """Return the 256-entry TrueColor fire palette.

    Black -> dark red -> bright orange -> golden yellow -> white ->
    white-blue hot sparks, with smooth linear interpolation between the
    control points.
    """
    return _build_palette(_FIRE_NODES)


def generate_blue_fire_palette() -> List[RGB]:
    """Return the 256-entry TrueColor blue-fire (gas) palette.

    Same structure as the fire palette, shifted to the blue/cyan range:
    black -> dark blue -> bright blue -> cyan -> white -> blue sparks.
    """
    return _build_palette(_BLUE_FIRE_NODES)
