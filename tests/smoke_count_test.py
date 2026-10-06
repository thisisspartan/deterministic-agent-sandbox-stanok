"""Reference tests for src/smoke_count.py (TASK-STANOK-CC-203).

Covers the ticket contract:
- count_greater(nums, x): number of elements strictly greater than x;
  empty list -> 0.
- count_between(nums, lo, hi): number of elements v with lo <= v <= hi
  (inclusive); empty list -> 0.
- count_signs(nums): (negatives, zeros, positives); empty -> (0, 0, 0).
- none of the three functions mutates the input list.
- cross-check against reference comprehensions on a fixed deterministic
  list of 100 ints (seeded random.Random(17)).
"""

import random

from smoke_count import count_between, count_greater, count_signs


def test_count_greater_empty():
    assert count_greater([], 0) == 0


def test_count_greater_basic():
    assert count_greater([1, 2, 3], 2) == 1


def test_count_greater_excludes_equal():
    assert count_greater([1, 2, 3], 3) == 0


def test_count_greater_negative_values():
    assert count_greater([-1, -2], -2) == 1


def test_count_greater_single_equal():
    assert count_greater([5], 5) == 0


def test_count_between_empty():
    assert count_between([], 0, 1) == 0


def test_count_between_inclusive_range():
    assert count_between([1, 2, 3, 4], 2, 3) == 2


def test_count_between_range_outside():
    assert count_between([1, 2, 3, 4], 5, 6) == 0


def test_count_between_negative_range():
    assert count_between([-1, 0, 1], -1, 1) == 3


def test_count_between_single_point():
    assert count_between([2], 2, 2) == 1


def test_count_signs_empty():
    assert count_signs([]) == (0, 0, 0)


def test_count_signs_all_zeros():
    assert count_signs([0, 0]) == (0, 2, 0)


def test_count_signs_mixed():
    assert count_signs([-1, 0, 2]) == (1, 1, 1)


def test_count_signs_all_negative():
    assert count_signs([-5, -3]) == (2, 0, 0)


def test_count_signs_single_positive():
    assert count_signs([7]) == (0, 0, 1)


def test_input_not_mutated_by_count_greater():
    xs = [1, 2, 3]
    count_greater(xs, 2)
    assert xs == [1, 2, 3]


def test_input_not_mutated_by_count_between():
    xs = [1, 2, 3, 4]
    count_between(xs, 2, 3)
    assert xs == [1, 2, 3, 4]


def test_input_not_mutated_by_count_signs():
    xs = [-1, 0, 2]
    count_signs(xs)
    assert xs == [-1, 0, 2]


def test_count_greater_matches_reference_on_seeded_list():
    nums = [random.Random(17).randint(-50, 50) for _ in range(100)]
    assert count_greater(nums, 0) == sum(1 for v in nums if v > 0)


def test_count_between_matches_reference_on_seeded_list():
    nums = [random.Random(17).randint(-50, 50) for _ in range(100)]
    assert count_between(nums, -10, 10) == sum(1 for v in nums if -10 <= v <= 10)


def test_count_signs_matches_reference_on_seeded_list():
    nums = [random.Random(17).randint(-50, 50) for _ in range(100)]
    assert count_signs(nums) == (
        sum(1 for v in nums if v < 0),
        sum(1 for v in nums if v == 0),
        sum(1 for v in nums if v > 0),
    )
