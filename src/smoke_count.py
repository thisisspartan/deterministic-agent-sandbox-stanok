"""Small counting utilities over lists of ints.

Three pure functions, no imports, no I/O, no state, no randomness.
Each takes a list of ints (possibly empty) and returns a count (or a
tuple of counts). Inputs are never mutated.

- ``count_greater(nums, x)`` — number of elements strictly greater than
  ``x``; empty list -> 0.
- ``count_between(nums, lo, hi)`` — number of elements ``v`` with
  ``lo <= v <= hi`` (inclusive); empty list -> 0.
- ``count_signs(nums)`` — ``(negatives, zeros, positives)``; empty list
  -> ``(0, 0, 0)``.
"""

from __future__ import annotations


def count_greater(nums: list, x: int) -> int:
    """Number of elements strictly greater than ``x``.

    ``count_greater([1, 2, 3], 2) == 1``; ``count_greater([], 0) == 0``.
    The input is not mutated.
    """
    return sum(1 for v in nums if v > x)


def count_between(nums: list, lo: int, hi: int) -> int:
    """Number of elements ``v`` with ``lo <= v <= hi`` (inclusive).

    ``count_between([1, 2, 3, 4], 2, 3) == 2``;
    ``count_between([], 0, 1) == 0``. The input is not mutated.
    """
    return sum(1 for v in nums if lo <= v <= hi)


def count_signs(nums: list) -> tuple:
    """Split ``nums`` into ``(negatives, zeros, positives)`` counts.

    ``count_signs([-1, 0, 2]) == (1, 1, 1)``;
    ``count_signs([]) == (0, 0, 0)``. The input is not mutated.
    """
    neg = sum(1 for v in nums if v < 0)
    zero = sum(1 for v in nums if v == 0)
    pos = sum(1 for v in nums if v > 0)
    return (neg, zero, pos)
