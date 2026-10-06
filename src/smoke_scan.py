"""Prefix scan utilities.

Three pure functions over lists of ints, no imports, no randomness,
no I/O, no state. Each returns a NEW list of the same length as the
input; inputs are never mutated.

- ``scan_max(nums)`` — prefix maxima: ``result[i] = max(nums[0..i])``;
  empty input -> ``[]``.
- ``scan_min(nums)`` — prefix minima: ``result[i] = min(nums[0..i])``;
  empty input -> ``[]``.
- ``scan_sum(nums)`` — prefix sums (cumulative):
  ``result[i] = sum(nums[0..i])``; empty input -> ``[]``.
"""


def scan_max(nums: list) -> list:
    """Prefix maxima: ``result[i] = max(nums[0..i])``.

    - ``scan_max([]) == []``
    - ``scan_max([3]) == [3]``
    - ``scan_max([1, 3, 2, 5]) == [1, 3, 3, 5]``
    - ``scan_max([-2, -5, -1]) == [-2, -2, -1]``

    Returns a new list; the input is not mutated.
    """
    out: list = []
    best = None
    for x in nums:
        if best is None or x > best:
            best = x
        out.append(best)
    return out


def scan_min(nums: list) -> list:
    """Prefix minima: ``result[i] = min(nums[0..i])``.

    - ``scan_min([]) == []``
    - ``scan_min([3]) == [3]``
    - ``scan_min([3, 1, 2, 0]) == [3, 1, 1, 0]``
    - ``scan_min([5, 5, 5]) == [5, 5, 5]``

    Returns a new list; the input is not mutated.
    """
    out: list = []
    best = None
    for x in nums:
        if best is None or x < best:
            best = x
        out.append(best)
    return out


def scan_sum(nums: list) -> list:
    """Prefix sums (cumulative): ``result[i] = sum(nums[0..i])``.

    - ``scan_sum([]) == []``
    - ``scan_sum([1]) == [1]``
    - ``scan_sum([1, 2, 3]) == [1, 3, 6]``
    - ``scan_sum([-1, 1, -1]) == [-1, 0, -1]``

    Returns a new list; the input is not mutated.
    """
    out: list = []
    total = 0
    for x in nums:
        total += x
        out.append(total)
    return out
