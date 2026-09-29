"""Small descriptive-statistics utilities.

Three pure functions, no I/O, no state, stdlib only. Each takes a
non-empty list of numbers (ints or floats) and returns a float:

- ``mean(xs)`` — arithmetic mean: ``sum(xs) / len(xs)``.
- ``median(xs)`` — median of the sorted input; for an even count, the
  mean of the two middle values.
- ``variance(xs)`` — population variance: ``sum((x - mean)^2) / n``;
  never negative.

Inputs are never mutated (the original list order is preserved). All
functions are total for any non-empty list of ints or floats.
"""

from __future__ import annotations


def mean(xs: list) -> float:
    """Arithmetic mean of a non-empty list of numbers.

    ``mean([1, 2, 3, 4]) == 2.5``. The input is not mutated.
    """
    return sum(xs) / len(xs)


def median(xs: list) -> float:
    """Median of a non-empty list of numbers.

    The input is sorted into a new list (the original is untouched).
    For an odd count the middle element is returned; for an even count
    the mean of the two middle values:

    - ``median([3, 1, 2]) == 2.0``
    - ``median([4, 1, 3, 2]) == 2.5``
    """
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return float(s[mid])
    return (s[mid - 1] + s[mid]) / 2


def variance(xs: list) -> float:
    """Population variance of a non-empty list of numbers.

    ``sum((x - mean)^2) / n``; never negative.

    - ``variance([1, 2, 3, 4]) == 1.25``
    - a constant list (or a single element) gives ``0.0``.
    """
    m = mean(xs)
    return sum((x - m) ** 2 for x in xs) / len(xs)
