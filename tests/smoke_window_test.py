"""Reference tests for src/smoke_window.py (TASK-STANOK-CC-199).

Covers the ticket contract:
- max_window_sum(nums, k): maximum sum over all windows of length k;
  no windows (k <= 0 or k > len(nums)) -> 0.
- min_window_sum(nums, k): minimum sum over all windows of length k;
  no windows -> 0.
- window_count(nums, k, threshold): number of windows of length k whose
  sum is >= threshold; no windows -> 0.
- A deterministic 200-int list (random.Random(11)) with k = 7 checked
  against the reference max/min/count over all window sums.
"""

import random

from smoke_window import max_window_sum, min_window_sum, window_count


# --- max_window_sum -------------------------------------------------------

def test_max_window_sum_empty_list():
    assert max_window_sum([], 2) == 0


def test_max_window_sum_single_element():
    assert max_window_sum([5], 1) == 5


def test_max_window_sum_basic():
    assert max_window_sum([1, 2, 3], 2) == 5


def test_max_window_sum_full_window():
    assert max_window_sum([1, 2, 3], 3) == 6


def test_max_window_sum_k_too_large():
    assert max_window_sum([1, 2, 3], 4) == 0


def test_max_window_sum_negative_values():
    assert max_window_sum([-1, -2, -3], 2) == -3


def test_max_window_sum_k_zero():
    assert max_window_sum([1, 2, 3], 0) == 0


def test_max_window_sum_k_negative():
    assert max_window_sum([1, 2, 3], -1) == 0


# --- min_window_sum -------------------------------------------------------

def test_min_window_sum_empty_list():
    assert min_window_sum([], 2) == 0


def test_min_window_sum_basic():
    assert min_window_sum([1, 2, 3], 2) == 3


def test_min_window_sum_negative_values():
    assert min_window_sum([-1, 5, -2], 2) == 3


def test_min_window_sum_full_window():
    assert min_window_sum([1, 2, 3], 3) == 6


def test_min_window_sum_k_too_large():
    assert min_window_sum([1, 2, 3], 4) == 0


def test_min_window_sum_k_zero():
    assert min_window_sum([1, 2, 3], 0) == 0


def test_min_window_sum_k_negative():
    assert min_window_sum([1, 2, 3], -1) == 0


# --- window_count ---------------------------------------------------------

def test_window_count_basic():
    # windows of length 2 in [1,2,3,4]: sums 3, 5, 7 -> two are >= 5
    assert window_count([1, 2, 3, 4], 2, 5) == 2


def test_window_count_lower_threshold():
    # sums 3, 5, 7 -> all three are >= 3
    assert window_count([1, 2, 3, 4], 2, 3) == 3


def test_window_count_threshold_above_all():
    assert window_count([1, 2, 3], 2, 10) == 0


def test_window_count_empty_list():
    assert window_count([], 2, 0) == 0


def test_window_count_k_too_large():
    assert window_count([1, 2, 3], 4, 0) == 0


def test_window_count_k_zero():
    assert window_count([1, 2, 3], 0, 0) == 0


def test_window_count_negative_threshold_counts_all():
    # sums 3, 5, 7 -> all three are >= -100
    assert window_count([1, 2, 3, 4], 2, -100) == 3


# --- deterministic 200-int reference check ---------------------------------

def test_reference_200_ints_k7():
    rng = random.Random(11)
    nums = [rng.randint(-50, 50) for _ in range(200)]
    k = 7
    n = len(nums)
    sums = [sum(nums[i:i + k]) for i in range(n - k + 1)]
    assert max_window_sum(nums, k) == max(sums)
    assert min_window_sum(nums, k) == min(sums)
    assert window_count(nums, k, 0) == sum(1 for s in sums if s >= 0)


# --- inputs are never mutated ----------------------------------------------

def test_input_not_mutated_by_max_window_sum():
    nums = [1, 2, 3, 4]
    max_window_sum(nums, 2)
    assert nums == [1, 2, 3, 4]


def test_input_not_mutated_by_min_window_sum():
    nums = [1, 2, 3, 4]
    min_window_sum(nums, 2)
    assert nums == [1, 2, 3, 4]


def test_input_not_mutated_by_window_count():
    nums = [1, 2, 3, 4]
    window_count(nums, 2, 5)
    assert nums == [1, 2, 3, 4]
