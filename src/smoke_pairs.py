"""Small pure pair-statistics utilities.

A "pair" is always a pair of DISTINCT INDICES ``(i, j)`` with ``i < j``;
equal VALUES at different indices count as separate elements.

Three pure functions, no I/O, no state, stdlib only:

- ``count_pairs_with_sum(nums, target)`` — number of index pairs
  ``(i, j)``, ``i < j``, with ``nums[i] + nums[j] == target``.
- ``two_sum_first(nums, target)`` — the lexicographically smallest pair
  ``(i, j)``, ``i < j``, with ``nums[i] + nums[j] == target`` (smallest
  ``i``, then smallest ``j``); ``None`` when no pair exists.
- ``max_pair_product(nums)`` — the maximum product ``nums[i] * nums[j]``
  over all index pairs ``i < j``; ``None`` when the list has fewer than
  2 elements.

Inputs are never mutated. Negative values are valid everywhere.
"""

from __future__ import annotations


def count_pairs_with_sum(nums: list[int], target: int) -> int:
    """Count index pairs ``(i, j)``, ``i < j``, with ``nums[i] + nums[j] == target``.

    Duplicates are distinct elements (index-based counting):
    ``count_pairs_with_sum([1, 1, 1], 2) == 3``.

    - ``count_pairs_with_sum([1, 5, 3, 7, 2], 8) == 2``  (1+7, 5+3)
    - ``count_pairs_with_sum([], 0) == 0``
    - ``count_pairs_with_sum([5], 10) == 0``

    The input is not mutated.
    """
    count = 0
    seen: dict[int, int] = {}
    for x in nums:
        # Every earlier index i with nums[i] == target - x forms a pair
        # (i, current j) with i < j.
        count += seen.get(target - x, 0)
        seen[x] = seen.get(x, 0) + 1
    return count


def two_sum_first(nums: list[int], target: int) -> tuple[int, int] | None:
    """Lexicographically smallest pair ``(i, j)``, ``i < j``, with
    ``nums[i] + nums[j] == target``; ``None`` when no pair exists.

    Smallest ``i`` first, then smallest ``j``:

    - ``two_sum_first([1, 5, 3, 7, 2], 8) == (0, 3)``
    - ``two_sum_first([3, 1, 5, 7], 8) == (0, 3)``  (3+5; 1+7 is later)
    - ``two_sum_first([1, 2], 5) is None``
    - ``two_sum_first([], 0) is None``

    The input is not mutated.
    """
    n = len(nums)
    for i in range(n):
        need = target - nums[i]
        for j in range(i + 1, n):
            if nums[j] == need:
                return (i, j)
    return None


def max_pair_product(nums: list[int]) -> int | None:
    """Maximum product ``nums[i] * nums[j]`` over all index pairs ``i < j``.

    ``None`` when the list has fewer than 2 elements. Two negative values
    can beat two positives:

    - ``max_pair_product([3, -1, 4, 0]) == 12``
    - ``max_pair_product([-5, -2, 3]) == 15``
    - ``max_pair_product([-1, -2]) == 2``
    - ``max_pair_product([7]) is None``
    - ``max_pair_product([]) is None``

    The input is not mutated.
    """
    n = len(nums)
    if n < 2:
        return None
    best: int | None = None
    for i in range(n):
        for j in range(i + 1, n):
            p = nums[i] * nums[j]
            if best is None or p > best:
                best = p
    return best
