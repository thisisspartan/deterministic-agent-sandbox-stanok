"""Pure 2D geometry utilities.

Three pure functions, no I/O, no state, stdlib only. Points are
2-tuples of ints or floats, e.g. ``(0.0, 0.0)``:

- ``distance(p1, p2)`` — Euclidean distance between two points,
  always a non-negative ``float``.
- ``midpoint(p1, p2)`` — the midpoint as a 2-tuple of ``float``s.
- ``triangle_area(a, b, c)`` — area of the triangle with vertices
  ``a``, ``b``, ``c`` via the shoelace formula; always a
  non-negative ``float`` (collinear points give ``0.0``).
"""

from __future__ import annotations

import math


def distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """Euclidean distance between points ``p1`` and ``p2``.

    ``distance((0, 0), (3, 4)) == 5.0``. Always returns a
    non-negative ``float``; identical points give ``0.0``.
    """
    dx = float(p2[0]) - float(p1[0])
    dy = float(p2[1]) - float(p1[1])
    return math.hypot(dx, dy)


def midpoint(p1: tuple[float, float], p2: tuple[float, float]) -> tuple[float, float]:
    """Midpoint of the segment ``p1``--``p2`` as a 2-tuple of floats.

    ``midpoint((0, 0), (4, 6)) == (2.0, 3.0)``. Integer inputs are
    converted to floats in the result.
    """
    return ((float(p1[0]) + float(p2[0])) / 2.0,
            (float(p1[1]) + float(p2[1])) / 2.0)


def triangle_area(a: tuple[float, float],
                  b: tuple[float, float],
                  c: tuple[float, float]) -> float:
    """Area of the triangle with vertices ``a``, ``b``, ``c``.

    Shoelace formula: ``abs(cross(b - a, c - a)) / 2``. Always
    non-negative and independent of vertex order; collinear points
    give ``0.0``. ``triangle_area((0, 0), (4, 0), (0, 3)) == 6.0``.
    """
    ax, ay = float(a[0]), float(a[1])
    bx, by = float(b[0]), float(b[1])
    cx, cy = float(c[0]), float(c[1])
    return abs((bx - ax) * (cy - ay) - (by - ay) * (cx - ax)) / 2.0
