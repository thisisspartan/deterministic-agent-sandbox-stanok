"""Small bounds-statistics utilities.

Three pure functions, no imports, no randomness, no I/O, no state. Each
takes a list of numbers (ints or floats) and never mutates it:

- ``min_max(nums)`` — ``(min(nums), max(nums))``; ``(None, None)`` for an
  empty list.
- ``span(nums)`` — ``max(nums) - min(nums)``; ``None`` for an empty list.
- ``within(value, lo, hi)`` — inclusive bounds check ``lo <= value <= hi``.
"""

from __future__ import annotations


def min_max(nums: list) -> tuple:
    """Return ``(min(nums), max(nums))``.

    An empty list yields ``(None, None)``. The input is not mutated.

    - ``min_max([]) == (None, None)``
    - ``min_max([5]) == (5, 5)``
    - ``min_max([3, 1, 2]) == (1, 3)``
    - ``min_max([-4, 7, -4]) == (-4, 7)``
    """
    if not nums:
        return (None, None)
    lo = hi = nums[0]
    for x in nums[1:]:
        if x < lo:
            lo = x
        if x > hi:
            hi = x
    return (lo, hi)


def span(nums: list) -> int | None:
    """Return ``max(nums) - min(nums)``; ``None`` for an empty list.

    - ``span([]) is None``
    - ``span([5]) == 0``
    - ``span([3, 1, 2]) == 2``
    - ``span([-4, 7]) == 11``
    """
    if not nums:
        return None
    lo, hi = min_max(nums)
    return hi - lo


def within(value, lo, hi) -> bool:
    """Inclusive bounds check: ``lo <= value <= hi``.

    - ``within(5, 1, 10) is True``
    - ``within(0, 1, 10) is False``
    - ``within(11, 1, 10) is False``
    - ``within(1, 1, 10) is True``
    - ``within(10, 1, 10) is True``
    """
    return lo <= value <= hi
