"""Consecutive-run statistics over lists of ints.

Three pure functions, no imports, no randomness, no I/O, no state:

- ``count_runs(nums)`` — the number of runs; empty list -> 0.
- ``longest_run(nums)`` — the length of the longest run; empty list -> 0.
- ``run_starts(nums)`` — the first value of each run, in order;
  empty list -> ``[]``.

A "run" is a maximal contiguous subsequence where each element is
exactly +1 from the previous one (e.g. in ``[1, 2, 4, 5, 7]`` the runs
are ``[1, 2]``, ``[4, 5]`` and ``[7]``).

Inputs are never mutated (the original list order and contents are
preserved). All three functions are total for any list of ints.
"""

from __future__ import annotations


def count_runs(nums: list) -> int:
    """Number of runs in ``nums``; empty list -> 0.

    A run starts at index 0 and at every index ``i > 0`` where
    ``nums[i] != nums[i - 1] + 1``.

    - ``count_runs([]) == 0``
    - ``count_runs([1, 2, 3]) == 1``
    - ``count_runs([1, 2, 4, 5]) == 2``
    - ``count_runs([5, 3, 1]) == 3``

    The input is not mutated.
    """
    if not nums:
        return 0
    count = 1
    for i in range(1, len(nums)):
        if nums[i] != nums[i - 1] + 1:
            count += 1
    return count


def longest_run(nums: list) -> int:
    """Length of the longest run in ``nums``; empty list -> 0.

    - ``longest_run([]) == 0``
    - ``longest_run([1, 2, 3]) == 3``
    - ``longest_run([1, 2, 4, 5]) == 2``
    - ``longest_run([5, 3, 1]) == 1``

    The input is not mutated.
    """
    best = 0
    current = 0
    for i, x in enumerate(nums):
        if i > 0 and x == nums[i - 1] + 1:
            current += 1
        else:
            current = 1
        if current > best:
            best = current
    return best


def run_starts(nums: list) -> list:
    """First value of each run in ``nums``, in order; empty list -> ``[]``.

    - ``run_starts([]) == []``
    - ``run_starts([1, 2, 3]) == [1]``
    - ``run_starts([1, 2, 4, 5, 7]) == [1, 4, 7]``
    - ``run_starts([5, 3, 1]) == [5, 3, 1]``

    The input is not mutated.
    """
    starts: list = []
    for i, x in enumerate(nums):
        if i == 0 or x != nums[i - 1] + 1:
            starts.append(x)
    return starts
