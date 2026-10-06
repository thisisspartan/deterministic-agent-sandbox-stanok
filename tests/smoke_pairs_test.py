"""Reference tests for src/smoke_pairs.py (TASK-STANOK-CC-189).

Covers the ticket contract:
- count_pairs_with_sum(nums, target): index-pair counting (i < j),
  duplicates as distinct elements, negatives, empty/single-element
  lists, no-match target, and a 200-element list checked against a
  brute-force reference.
- two_sum_first(nums, target): lexicographically smallest (i, j) pair,
  None when no pair exists, smallest j when several match the smallest i.
- max_pair_product(nums): maximum product over all index pairs, None
  for fewer than 2 elements, two negatives beating two positives,
  all-negative lists, two-element lists.
- none of the functions mutates its input list.
"""

from smoke_pairs import count_pairs_with_sum, max_pair_product, two_sum_first


def _brute_count(nums, target):
    """Brute-force reference: count all index pairs i < j with sum == target."""
    return sum(
        1
        for i in range(len(nums))
        for j in range(i + 1, len(nums))
        if nums[i] + nums[j] == target
    )


def _brute_max_product(nums):
    """Brute-force reference: max product over all index pairs i < j."""
    return max(
        nums[i] * nums[j]
        for i in range(len(nums))
        for j in range(i + 1, len(nums))
    )


# --- count_pairs_with_sum -------------------------------------------------


def test_count_pairs_basic_vector():
    assert count_pairs_with_sum([1, 5, 3, 7, 2], 8) == 2


def test_count_pairs_all_ones():
    assert count_pairs_with_sum([1, 1, 1], 2) == 3


def test_count_pairs_zeros():
    assert count_pairs_with_sum([0, 0, 0], 0) == 3


def test_count_pairs_negatives():
    assert count_pairs_with_sum([-1, 1, -1, 1], 0) == 4


def test_count_pairs_empty_list():
    assert count_pairs_with_sum([], 0) == 0


def test_count_pairs_single_element():
    assert count_pairs_with_sum([5], 10) == 0


def test_count_pairs_no_match_target():
    assert count_pairs_with_sum([1, 2, 3], 100) == 0


def test_count_pairs_large_list_against_brute_force():
    # 200 deterministic elements mixing negatives, zeros and positives.
    nums = [(i * 7) % 13 - 5 for i in range(200)]
    for target in (-10, 0, 7, 12):
        assert count_pairs_with_sum(nums, target) == _brute_count(nums, target)


# --- two_sum_first ---------------------------------------------------------


def test_two_sum_first_basic_vector():
    assert two_sum_first([1, 5, 3, 7, 2], 8) == (0, 3)


def test_two_sum_first_smallest_i_wins():
    # 3+5 at (0, 2) beats 1+7 at (1, 3): smallest i wins.
    assert two_sum_first([3, 1, 5, 7], 8) == (0, 2)


def test_two_sum_first_adjacent_pair():
    assert two_sum_first([5, 3, 1, 7], 8) == (0, 1)


def test_two_sum_first_no_pair():
    assert two_sum_first([1, 2], 5) is None


def test_two_sum_first_empty_list():
    assert two_sum_first([], 0) is None


def test_two_sum_first_smallest_j_for_smallest_i():
    # i=0 (value 2) matches j=1, 2, 3; the smallest j must be returned.
    assert two_sum_first([2, 6, 6, 6], 8) == (0, 1)


# --- max_pair_product ------------------------------------------------------


def test_max_pair_product_basic_vector():
    assert max_pair_product([3, -1, 4, 0]) == 12


def test_max_pair_product_two_negatives_beat_two_positives():
    # (-5)*(-2) = 10 beats (-5)*3 = -15 and (-2)*3 = -6.
    assert max_pair_product([-5, -2, 3]) == 10
    # Two negatives genuinely beating two positives: (-5)*(-3) = 15 > 2*4 = 8.
    assert max_pair_product([-5, -3, 2, 4]) == 15


def test_max_pair_product_two_negatives():
    assert max_pair_product([-1, -2]) == 2


def test_max_pair_product_single_element():
    assert max_pair_product([7]) is None


def test_max_pair_product_empty_list():
    assert max_pair_product([]) is None


def test_max_pair_product_all_negative():
    # The two largest-magnitude negatives: (-4) * (-3) = 12.
    assert max_pair_product([-4, -3, -1]) == 12


def test_max_pair_product_two_elements_positive():
    assert max_pair_product([3, 4]) == 12


def test_max_pair_product_two_elements_negative_result():
    assert max_pair_product([-2, 5]) == -10


def test_max_pair_product_mixed_list_against_brute_force():
    nums = [-9, 4, -1, 0, 7, -6, 2, 11, -3, 5]
    assert max_pair_product(nums) == _brute_max_product(nums)


# --- purity -----------------------------------------------------------------


def test_input_not_mutated_by_count_pairs_with_sum():
    xs = [1, 5, 3, 7, 2]
    count_pairs_with_sum(xs, 8)
    assert xs == [1, 5, 3, 7, 2]


def test_input_not_mutated_by_two_sum_first():
    xs = [3, 1, 5, 7]
    two_sum_first(xs, 8)
    assert xs == [3, 1, 5, 7]


def test_input_not_mutated_by_max_pair_product():
    xs = [-5, -2, 3]
    max_pair_product(xs)
    assert xs == [-5, -2, 3]
