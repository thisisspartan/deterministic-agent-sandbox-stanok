"""Sliding-window statistics over lists of ints.

Three pure functions, no imports, no randomness, no I/O. A "window" is a
contiguous slice of exactly ``k`` elements. If ``k <= 0`` or
``k > len(nums)`` there are no windows and every function returns 0.

- ``max_window_sum(nums, k)`` — maximum sum over all windows of length k.
- ``min_window_sum(nums, k)`` — minimum sum over all windows of length k.
- ``window_count(nums, k, threshold)`` — number of windows of length k
  whose sum is >= threshold.

Inputs are never mutated. Each function runs in O(n) via a sliding sum
(the first window sum is computed once, then each next window sum is
derived by adding the entering element and subtracting the leaving one).
"""


def max_window_sum(nums, k):
    """Maximum sum over all windows of length k; no windows -> 0.

    - ``max_window_sum([1, 2, 3], 2) == 5``
    - ``max_window_sum([-1, -2, -3], 2) == -3``
    - ``max_window_sum([1, 2, 3], 4) == 0`` (k > len(nums))
    """
    n = len(nums)
    if k <= 0 or k > n:
        return 0
    s = sum(nums[:k])
    best = s
    for i in range(1, n - k + 1):
        s += nums[i + k - 1] - nums[i - 1]
        if s > best:
            best = s
    return best


def min_window_sum(nums, k):
    """Minimum sum over all windows of length k; no windows -> 0.

    - ``min_window_sum([1, 2, 3], 2) == 3``
    - ``min_window_sum([-1, 5, -2], 2) == 3``
    - ``min_window_sum([1, 2, 3], 4) == 0`` (k > len(nums))
    """
    n = len(nums)
    if k <= 0 or k > n:
        return 0
    s = sum(nums[:k])
    worst = s
    for i in range(1, n - k + 1):
        s += nums[i + k - 1] - nums[i - 1]
        if s < worst:
            worst = s
    return worst


def window_count(nums, k, threshold):
    """Number of windows of length k whose sum is >= threshold; no windows -> 0.

    - ``window_count([1, 2, 3, 4], 2, 5) == 2`` (window sums 3, 5, 7)
    - ``window_count([1, 2, 3], 2, 10) == 0``
    - ``window_count([], 2, 0) == 0``
    """
    n = len(nums)
    if k <= 0 or k > n:
        return 0
    s = sum(nums[:k])
    count = 1 if s >= threshold else 0
    for i in range(1, n - k + 1):
        s += nums[i + k - 1] - nums[i - 1]
        if s >= threshold:
            count += 1
    return count
