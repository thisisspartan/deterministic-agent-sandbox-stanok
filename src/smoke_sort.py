"""Small pure sort-statistics utilities.

Three pure functions, no I/O, no state, stdlib only, no randomness:

- ``is_sorted(nums, strict=False)`` — ``True`` when the list is
  non-decreasing (``strict=False``) or strictly increasing
  (``strict=True``).
- ``count_inversions(nums)`` — number of index pairs ``(i, j)``,
  ``i < j``, with ``nums[i] > nums[j]``.
- ``kth_smallest(nums, k)`` — the 1-based ``k``-th smallest value
  (duplicates count as separate positions); ``None`` when
  ``k < 1`` or ``k > len(nums)``.

Inputs are never mutated.
"""

from __future__ import annotations


def is_sorted(nums: list[int], strict: bool = False) -> bool:
    """``True`` when ``nums`` is sorted.

    - ``strict=False``: non-decreasing — equal neighbours are allowed.
    - ``strict=True``: strictly increasing — every neighbour must grow.

    - ``is_sorted([]) is True``
    - ``is_sorted([1]) is True``
    - ``is_sorted([1, 2, 2, 3]) is True``
    - ``is_sorted([1, 2, 2, 3], strict=True) is False``
    - ``is_sorted([3, 2, 1]) is False``
    - ``is_sorted([1, 1]) is True``; ``is_sorted([1, 1], strict=True) is False``

    The input is not mutated.
    """
    for i in range(len(nums) - 1):
        if strict:
            if nums[i] >= nums[i + 1]:
                return False
        else:
            if nums[i] > nums[i + 1]:
                return False
    return True


def count_inversions(nums: list[int]) -> int:
    """Count index pairs ``(i, j)``, ``i < j``, with ``nums[i] > nums[j]``.

    Equal values are NOT inversions. Counted via a merge-sort pass
    (O(n log n)); a brute-force O(n^2) reference agrees on all inputs.

    - ``count_inversions([]) == 0``
    - ``count_inversions([1, 2, 3]) == 0``
    - ``count_inversions([3, 2, 1]) == 3``
    - ``count_inversions([2, 4, 1, 3]) == 3``  (pairs (2,1), (4,1), (4,3))
    - ``count_inversions([1, 1, 1]) == 0``
    - ``count_inversions([5, 1]) == 1``

    The input is not mutated.
    """
    return _merge_count(list(nums))


def _merge_count(nums: list[int]) -> int:
    """In-place merge sort returning the number of inversions."""
    n = len(nums)
    if n < 2:
        return 0
    mid = n // 2
    left = nums[:mid]
    right = nums[mid:]
    inv = _merge_count(left) + _merge_count(right)
    i = j = 0
    out: list[int] = []
    while i < len(left) and j < len(right):
        if left[i] <= right[j]:
            # left[i] is smaller than every remaining right element:
            # no inversion is formed by taking it.
            out.append(left[i])
            i += 1
        else:
            # right[j] is smaller than every remaining element of left
            # (left is sorted): each of them forms an inversion with it.
            inv += len(left) - i
            out.append(right[j])
            j += 1
    out.extend(left[i:])
    out.extend(right[j:])
    nums[:] = out
    return inv


def kth_smallest(nums: list[int], k: int) -> int | None:
    """The 1-based ``k``-th smallest value; duplicates count as separate
    positions. ``None`` when ``k < 1`` or ``k > len(nums)``.

    - ``kth_smallest([3, 1, 2], 1) == 1``
    - ``kth_smallest([3, 1, 2], 2) == 2``
    - ``kth_smallest([3, 1, 2], 3) == 3``
    - ``kth_smallest([3, 1, 2], 0) is None``
    - ``kth_smallest([3, 1, 2], 4) is None``
    - ``kth_smallest([], 1) is None``
    - ``kth_smallest([7, 7, 7], 2) == 7``

    The input is not mutated.
    """
    if k < 1 or k > len(nums):
        return None
    return sorted(nums)[k - 1]
