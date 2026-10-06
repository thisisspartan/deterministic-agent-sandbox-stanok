"""Reference tests for src/smoke_sort.py (TASK-STANOK-CC-190).

Covers the ticket contract:
- is_sorted(nums, strict): non-decreasing vs strictly increasing,
  empty/single-element lists, equal neighbours, descending lists.
- count_inversions(nums): index pairs i < j with nums[i] > nums[j],
  empty/sorted/reversed/duplicate lists, and a brute-force O(n^2)
  reference checked on a fixed 200-element list (descending and a
  seeded random.Random(42) permutation).
- kth_smallest(nums, k): 1-based k-th smallest value, duplicates as
  separate positions, None for out-of-range k and empty lists.
- is_sorted on the 200-element descending list -> False, on its
  sorted copy -> True.
- none of the functions mutates its input list.
"""

import random

from smoke_sort import count_inversions, is_sorted, kth_smallest


def _brute_inversions(nums):
    """Brute-force O(n^2) reference: count pairs i < j with nums[i] > nums[j]."""
    return sum(
        1
        for i in range(len(nums))
        for j in range(i + 1, len(nums))
        if nums[i] > nums[j]
    )


# --- is_sorted -------------------------------------------------------------


def test_is_sorted_empty_list():
    assert is_sorted([]) is True


def test_is_sorted_single_element():
    assert is_sorted([1]) is True


def test_is_sorted_non_decreasing_with_equal_neighbours():
    assert is_sorted([1, 2, 2, 3]) is True


def test_is_sorted_equal_neighbours_rejected_in_strict_mode():
    assert is_sorted([1, 2, 2, 3], strict=True) is False


def test_is_sorted_descending_list():
    assert is_sorted([3, 2, 1]) is False


def test_is_sorted_two_equal_elements_non_strict():
    assert is_sorted([1, 1]) is True


def test_is_sorted_two_equal_elements_strict():
    assert is_sorted([1, 1], strict=True) is False


def test_is_sorted_strictly_increasing():
    assert is_sorted([1, 2, 3], strict=True) is True


def test_is_sorted_negative_values():
    assert is_sorted([-3, -1, -1, 0]) is True
    assert is_sorted([-3, -1, -1, 0], strict=True) is False


def test_is_sorted_200_element_descending_and_sorted_copy():
    desc = list(range(200, 0, -1))
    assert is_sorted(desc) is False
    assert is_sorted(sorted(desc)) is True


# --- count_inversions -------------------------------------------------------


def test_count_inversions_empty_list():
    assert count_inversions([]) == 0


def test_count_inversions_sorted_list():
    assert count_inversions([1, 2, 3]) == 0


def test_count_inversions_reversed_list():
    assert count_inversions([3, 2, 1]) == 3


def test_count_inversions_mixed_vector():
    # Pairs (2,1), (4,1), (4,3).
    assert count_inversions([2, 4, 1, 3]) == 3


def test_count_inversions_all_equal():
    assert count_inversions([1, 1, 1]) == 0


def test_count_inversions_two_elements():
    assert count_inversions([5, 1]) == 1


def test_count_inversions_200_element_descending_against_brute_force():
    nums = list(range(200, 0, -1))
    assert count_inversions(nums) == _brute_inversions(nums)


def test_count_inversions_200_element_seeded_permutation_against_brute_force():
    rng = random.Random(42)
    nums = list(range(200))
    rng.shuffle(nums)
    assert count_inversions(nums) == _brute_inversions(nums)


# --- kth_smallest ------------------------------------------------------------


def test_kth_smallest_basic_vector():
    assert kth_smallest([3, 1, 2], 1) == 1
    assert kth_smallest([3, 1, 2], 2) == 2
    assert kth_smallest([3, 1, 2], 3) == 3


def test_kth_smallest_k_zero_is_none():
    assert kth_smallest([3, 1, 2], 0) is None


def test_kth_smallest_k_beyond_length_is_none():
    assert kth_smallest([3, 1, 2], 4) is None


def test_kth_smallest_empty_list_is_none():
    assert kth_smallest([], 1) is None


def test_kth_smallest_duplicates_count_as_separate_positions():
    assert kth_smallest([7, 7, 7], 2) == 7


def test_kth_smallest_negative_values():
    assert kth_smallest([-5, -1, -9], 1) == -9
    assert kth_smallest([-5, -1, -9], 3) == -1


# --- purity ------------------------------------------------------------------


def test_input_not_mutated_by_is_sorted():
    xs = [3, 1, 2]
    is_sorted(xs)
    is_sorted(xs, strict=True)
    assert xs == [3, 1, 2]


def test_input_not_mutated_by_count_inversions():
    xs = [2, 4, 1, 3]
    count_inversions(xs)
    assert xs == [2, 4, 1, 3]


def test_input_not_mutated_by_kth_smallest():
    xs = [3, 1, 2]
    kth_smallest(xs, 2)
    assert xs == [3, 1, 2]
