"""Permutation utilities.

Three pure functions over lists of ints, no imports, no randomness:

- ``count_permutations(nums)`` — the number of DISTINCT permutations of
  the list, i.e. ``n! / prod(c! for each value-count c)``; empty list -> 1.
- ``next_permutation(nums)`` — the next lexicographic permutation of
  ``nums`` as a NEW list; ``None`` when ``nums`` is the last (fully
  descending) permutation.
- ``kth_permutation(elems, k)`` — the 0-based k-th lexicographic
  permutation of the SORTED form of ``elems`` (distinct ints); ``None``
  when ``k < 0`` or ``k >= n!``.

Inputs are never mutated.
"""


def _factorial(n: int) -> int:
    """n! for n >= 0, iteratively."""
    out = 1
    for i in range(2, n + 1):
        out *= i
    return out


def count_permutations(nums: list) -> int:
    """Number of distinct permutations of ``nums``.

    ``n! / prod(c! for each value-count c)``; the empty list has exactly
    one (empty) permutation.

    - ``count_permutations([]) == 1``
    - ``count_permutations([1, 1, 2]) == 3``
    - ``count_permutations([1, 2, 3]) == 6``

    The input is not mutated.
    """
    counts: dict = {}
    for x in nums:
        counts[x] = counts.get(x, 0) + 1
    total = _factorial(len(nums))
    for c in counts.values():
        total //= _factorial(c)
    return total


def next_permutation(nums: list) -> list | None:
    """The next lexicographic permutation of ``nums`` (a NEW list).

    Returns ``None`` when ``nums`` is the last (fully descending)
    permutation.

    - ``next_permutation([1, 2, 3]) == [1, 3, 2]``
    - ``next_permutation([3, 2, 1]) is None``
    - ``next_permutation([1, 1, 5]) == [1, 5, 1]``

    The input is not mutated.
    """
    a = list(nums)
    n = len(a)
    # Find the longest non-increasing suffix; i is its first index.
    i = n - 2
    while i >= 0 and a[i] >= a[i + 1]:
        i -= 1
    if i < 0:
        return None  # fully descending: the last permutation
    # Find the rightmost element greater than a[i] and swap.
    j = n - 1
    while a[j] <= a[i]:
        j -= 1
    a[i], a[j] = a[j], a[i]
    # Reverse the (non-increasing) suffix to make it strictly increasing.
    lo, hi = i + 1, n - 1
    while lo < hi:
        a[lo], a[hi] = a[hi], a[lo]
        lo += 1
        hi -= 1
    return a


def kth_permutation(elems: list, k: int) -> list | None:
    """The 0-based k-th lexicographic permutation of the sorted ``elems``.

    ``elems`` holds distinct ints. Returns ``None`` when ``k < 0`` or
    ``k >= n!``.

    - ``kth_permutation([1, 2, 3], 0) == [1, 2, 3]``
    - ``kth_permutation([1, 2, 3], 5) == [3, 2, 1]``
    - ``kth_permutation([1, 2], 2) is None``
    - ``kth_permutation([1, 2], -1) is None``

    The input is not mutated.
    """
    if k < 0:
        return None
    pool = sorted(elems)
    n = len(pool)
    if k >= _factorial(n):
        return None
    out: list = []
    for pos in range(n):
        block = _factorial(n - pos - 1)
        idx = k // block
        k %= block
        out.append(pool.pop(idx))
    return out
