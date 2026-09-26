"""Pure numeric helpers: range clamping and linear interpolation.

Two pure functions, no I/O, no state:

- ``clamp(v, lo, hi)`` — restrict ``v`` to the closed interval ``[lo, hi]``.
- ``lerp(a, b, t)`` — linear interpolation between ``a`` and ``b``; the
  parameter ``t`` is first clamped to ``[0, 1]`` via ``clamp``.
"""

from __future__ import annotations


def clamp(v: float, lo: float, hi: float) -> float:
    """Restrict ``v`` to the closed interval ``[lo, hi]``.

    - ``lo <= v <= hi`` -> ``v`` unchanged;
    - ``v < lo`` -> ``lo``;
    - ``v > hi`` -> ``hi``;
    - degenerate ``lo == hi`` -> that value for any ``v``.
    """
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def lerp(a: float, b: float, t: float) -> float:
    """Linear interpolation between ``a`` and ``b``.

    ``t`` is clamped to ``[0, 1]`` first, so ``t < 0`` behaves as ``0``
    (result ``a``) and ``t > 1`` behaves as ``1`` (result ``b``).
    """
    return a + (b - a) * clamp(t, 0, 1)
