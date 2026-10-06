"""Reference tests for src/smoke_scan.py (TASK-STANOK-CC-202).

Covers the ticket contract:
- scan_max(nums): prefix maxima; empty, single element, the ticket
  vectors, all-negative input.
- scan_min(nums): prefix minima; empty, single element, the ticket
  vectors, all-equal input.
- scan_sum(nums): prefix sums; empty, single element, the ticket
  vectors, mixed-sign input.
- each function returns a NEW list of the same length and never
  mutates the input.
- a fixed deterministic list of 100 ints (seeded random.Random(13))
  matches the reference prefix computations for all three functions.
"""

import random

from smoke_scan import scan_max, scan_min, scan_sum


# ---------------------------------------------------------------- scan_max

def test_scan_max_empty():
    assert scan_max([]) == []


def test_scan_max_single():
    assert scan_max([3]) == [3]


def test_scan_max_ticket_vector():
    assert scan_max([1, 3, 2, 5]) == [1, 3, 3, 5]


def test_scan_max_all_negative():
    assert scan_max([-2, -5, -1]) == [-2, -2, -1]


# ---------------------------------------------------------------- scan_min

def test_scan_min_empty():
    assert scan_min([]) == []


def test_scan_min_single():
    assert scan_min([3]) == [3]


def test_scan_min_ticket_vector():
    assert scan_min([3, 1, 2, 0]) == [3, 1, 1, 0]


def test_scan_min_all_equal():
    assert scan_min([5, 5, 5]) == [5, 5, 5]


# ---------------------------------------------------------------- scan_sum

def test_scan_sum_empty():
    assert scan_sum([]) == []


def test_scan_sum_single():
    assert scan_sum([1]) == [1]


def test_scan_sum_ticket_vector():
    assert scan_sum([1, 2, 3]) == [1, 3, 6]


def test_scan_sum_mixed_signs():
    assert scan_sum([-1, 1, -1]) == [-1, 0, -1]


# ------------------------------------------------- new list, no mutation

def test_scan_max_returns_new_list_same_length():
    nums = [1, 3, 2, 5]
    out = scan_max(nums)
    assert out is not nums
    assert len(out) == len(nums)


def test_scan_min_returns_new_list_same_length():
    nums = [3, 1, 2, 0]
    out = scan_min(nums)
    assert out is not nums
    assert len(out) == len(nums)


def test_scan_sum_returns_new_list_same_length():
    nums = [1, 2, 3]
    out = scan_sum(nums)
    assert out is not nums
    assert len(out) == len(nums)


def test_scan_max_does_not_mutate_input():
    nums = [1, 3, 2, 5]
    scan_max(nums)
    assert nums == [1, 3, 2, 5]


def test_scan_min_does_not_mutate_input():
    nums = [3, 1, 2, 0]
    scan_min(nums)
    assert nums == [3, 1, 2, 0]


def test_scan_sum_does_not_mutate_input():
    nums = [-1, 1, -1]
    scan_sum(nums)
    assert nums == [-1, 1, -1]


# ------------------------------------------- 100-int deterministic reference

def _fixed_100_ints():
    # Fixed deterministic list: seeded random.Random(13), 100 ints.
    return [random.Random(13).randint(-1000, 1000) for _ in range(100)]


def test_scan_max_matches_reference_on_100_ints():
    nums = _fixed_100_ints()
    n = len(nums)
    assert scan_max(nums) == [max(nums[: i + 1]) for i in range(n)]


def test_scan_min_matches_reference_on_100_ints():
    nums = _fixed_100_ints()
    n = len(nums)
    assert scan_min(nums) == [min(nums[: i + 1]) for i in range(n)]


def test_scan_sum_matches_reference_on_100_ints():
    nums = _fixed_100_ints()
    n = len(nums)
    assert scan_sum(nums) == [sum(nums[: i + 1]) for i in range(n)]
