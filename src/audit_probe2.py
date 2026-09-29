"""Numeric clamp helper (TASK-STANOK-CC-177).

One pure function, no I/O, no state:

- ``clamp(value, lo, hi)`` — clamp ``value`` into the closed interval
  ``[lo, hi]``; ``value``, ``lo`` and ``hi`` are ``int`` or ``float``;
  ``lo > hi`` raises ``ValueError``.
"""

from __future__ import annotations


def clamp(value: int | float, lo: int | float, hi: int | float) -> int | float:
    """Clamp ``value`` into the closed interval ``[lo, hi]``.

    - ``value < lo`` -> ``lo``;
    - ``value > hi`` -> ``hi``;
    - ``lo <= value <= hi`` -> ``value`` unchanged;
    - ``lo > hi`` -> ``ValueError``.
    """
    if lo > hi:
        raise ValueError(f"lo ({lo}) must be <= hi ({hi})")
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value
