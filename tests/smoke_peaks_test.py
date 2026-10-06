"""Reference tests for src/smoke_peaks.py (TASK-STANOK-CC-197).

A peak at index i (1 <= i < n-1) requires ``nums[i] > nums[i-1]`` AND
``nums[i] > nums[i+1]`` (strict). A valley is the mirror image with ``<``.

Covers the ticket contract:
- count_peaks: every ticket vector, lists shorter than 3 -> 0.
- count_valleys: every ticket vector, lists shorter than 3 -> 0.
- peak_positions: every ticket vector, empty/short list -> [].
- Cross-checks on a fixed deterministic list of 200 ints
  (random.Random(21) sample):
  * count_peaks == builtin reference sum;
  * count_valleys == mirror builtin reference sum;
  * peak_positions == matching list comprehension.
- Hand-computed zig-zag [1,3,1,3,1,3,1]: count_peaks == 3,
  count_valleys == 2.
- None of the three functions mutates the input list.
"""

import random

from smoke_peaks import count_peaks, count_valleys, peak_positions


# Fixed deterministic list of 200 ints (seed 21).
NUMS = [random.Random(21).randint(0, 9) for _ in range(200)]


def test_count_peaks_empty():
    assert count_peaks([]) == 0


def test_count_peaks_single():
    assert count_peaks([1]) == 0


def test_count_peaks_two():
    assert count_peaks([1, 2]) == 0


def test_count_peaks_one_peak():
    assert count_peaks([1, 2, 1]) == 1


def test_count_peaks_monotone():
    assert count_peaks([1, 2, 3]) == 0


def test_count_peaks_two_peaks():
    assert count_peaks([1, 3, 2, 4, 1]) == 2


def test_count_peaks_flat():
    assert count_peaks([5, 5, 5]) == 0


def test_count_valleys_empty():
    assert count_valleys([]) == 0


def test_count_valleys_single():
    assert count_valleys([3]) == 0


def test_count_valleys_two():
    assert count_valleys([3, 1]) == 0


def test_count_valleys_one_valley():
    assert count_valleys([3, 1, 3]) == 1


def test_count_valleys_peak_is_not_valley():
    assert count_valleys([1, 2, 1]) == 0


def test_count_valleys_two_valleys():
    assert count_valleys([2, 1, 2, 1, 2]) == 2


def test_count_valleys_flat():
    assert count_valleys([1, 1, 1]) == 0


def test_peak_positions_empty():
    assert peak_positions([]) == []


def test_peak_positions_single():
    assert peak_positions([1]) == []


def test_peak_positions_two():
    assert peak_positions([1, 2]) == []


def test_peak_positions_one():
    assert peak_positions([1, 2, 1]) == [1]


def test_peak_positions_two():
    assert peak_positions([1, 3, 2, 4, 1]) == [1, 3]


def test_peak_positions_monotone():
    assert peak_positions([1, 2, 3]) == []


def test_count_peaks_matches_builtin_reference_on_200_list():
    n = len(NUMS)
    expected = sum(
        1 for i in range(1, n - 1)
        if NUMS[i] > NUMS[i - 1] and NUMS[i] > NUMS[i + 1]
    )
    assert count_peaks(NUMS) == expected


def test_count_valleys_matches_builtin_reference_on_200_list():
    n = len(NUMS)
    expected = sum(
        1 for i in range(1, n - 1)
        if NUMS[i] < NUMS[i - 1] and NUMS[i] < NUMS[i + 1]
    )
    assert count_valleys(NUMS) == expected


def test_peak_positions_matches_comprehension_on_200_list():
    n = len(NUMS)
    expected = [
        i for i in range(1, n - 1)
        if NUMS[i] > NUMS[i - 1] and NUMS[i] > NUMS[i + 1]
    ]
    assert peak_positions(NUMS) == expected


def test_zigzag_peaks():
    assert count_peaks([1, 3, 1, 3, 1, 3, 1]) == 3


def test_zigzag_valleys():
    assert count_valleys([1, 3, 1, 3, 1, 3, 1]) == 2


def test_input_not_mutated_by_count_peaks():
    xs = [1, 3, 2, 4, 1]
    count_peaks(xs)
    assert xs == [1, 3, 2, 4, 1]


def test_input_not_mutated_by_count_valleys():
    xs = [2, 1, 2, 1, 2]
    count_valleys(xs)
    assert xs == [2, 1, 2, 1, 2]


def test_input_not_mutated_by_peak_positions():
    xs = [1, 3, 2, 4, 1]
    peak_positions(xs)
    assert xs == [1, 3, 2, 4, 1]
