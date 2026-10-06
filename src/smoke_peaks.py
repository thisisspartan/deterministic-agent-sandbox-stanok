"""Peak/valley statistics over lists of ints.

Three pure functions, no imports, no randomness, no I/O, no state:

- ``count_peaks(nums)`` — the number of peaks; lists shorter than 3 -> 0.
- ``count_valleys(nums)`` — the number of valleys; lists shorter than 3 -> 0.
- ``peak_positions(nums)`` — the indices of the peaks, ascending;
  empty/short list -> ``[]``.

A peak at index ``i`` (``1 <= i < n-1``) requires ``nums[i] > nums[i-1]``
AND ``nums[i] > nums[i+1]`` (strict). A valley is the mirror image with
``<``.

Inputs are never mutated (the original list order and contents are
preserved). All three functions are total for any list of ints.
"""


def count_peaks(nums: list) -> int:
    """Number of peaks in ``nums``; lists shorter than 3 -> 0.

    A peak at index ``i`` (``1 <= i < n-1``) requires
    ``nums[i] > nums[i-1]`` AND ``nums[i] > nums[i+1]`` (strict).

    - ``count_peaks([]) == 0``
    - ``count_peaks([1]) == 0``
    - ``count_peaks([1, 2]) == 0``
    - ``count_peaks([1, 2, 1]) == 1``
    - ``count_peaks([1, 2, 3]) == 0``
    - ``count_peaks([1, 3, 2, 4, 1]) == 2``
    - ``count_peaks([5, 5, 5]) == 0``

    The input is not mutated.
    """
    return sum(
        1 for i in range(1, len(nums) - 1)
        if nums[i] > nums[i - 1] and nums[i] > nums[i + 1]
    )


def count_valleys(nums: list) -> int:
    """Number of valleys in ``nums``; lists shorter than 3 -> 0.

    A valley at index ``i`` (``1 <= i < n-1``) requires
    ``nums[i] < nums[i-1]`` AND ``nums[i] < nums[i+1]`` (strict).

    - ``count_valleys([]) == 0``
    - ``count_valleys([3, 1, 3]) == 1``
    - ``count_valleys([1, 2, 1]) == 0``
    - ``count_valleys([2, 1, 2, 1, 2]) == 2``
    - ``count_valleys([1, 1, 1]) == 0``

    The input is not mutated.
    """
    return sum(
        1 for i in range(1, len(nums) - 1)
        if nums[i] < nums[i - 1] and nums[i] < nums[i + 1]
    )


def peak_positions(nums: list) -> list:
    """Indices of the peaks in ``nums``, ascending; empty/short list -> ``[]``.

    - ``peak_positions([]) == []``
    - ``peak_positions([1, 2, 1]) == [1]``
    - ``peak_positions([1, 3, 2, 4, 1]) == [1, 3]``
    - ``peak_positions([1, 2, 3]) == []``

    The input is not mutated.
    """
    return [
        i for i in range(1, len(nums) - 1)
        if nums[i] > nums[i - 1] and nums[i] > nums[i + 1]
    ]
