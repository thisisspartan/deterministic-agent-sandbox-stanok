"""Reference tests for src/smoke_perm.py (TASK-STANOK-CC-201).

Covers the ticket contract:
- count_permutations(nums): the ticket vectors, including the empty list.
- next_permutation(nums): the ticket vectors, including the last
  (fully descending) permutation returning None.
- kth_permutation(elems, k): the ticket vectors, including out-of-range
  and negative k returning None.
- Cross-check for elems = [1,2,3,4]: kth_permutation matches the
  reference list of all 24 lexicographic permutations for every k,
  and chaining next_permutation from [1,2,3,4] reproduces the whole
  reference sequence, returning None after the last element.
- None of the functions mutates its input list.
"""

import itertools

from smoke_perm import count_permutations, kth_permutation, next_permutation


def test_count_permutations_empty_list():
    assert count_permutations([]) == 1


def test_count_permutations_single_element():
    assert count_permutations([1]) == 1


def test_count_permutations_two_distinct():
    assert count_permutations([1, 2]) == 2


def test_count_permutations_with_duplicates():
    assert count_permutations([1, 1, 2]) == 3


def test_count_permutations_all_equal():
    assert count_permutations([1, 1, 1]) == 1


def test_count_permutations_three_distinct():
    assert count_permutations([1, 2, 3]) == 6


def test_next_permutation_basic():
    assert next_permutation([1, 2, 3]) == [1, 3, 2]


def test_next_permutation_last_returns_none():
    assert next_permutation([3, 2, 1]) is None


def test_next_permutation_with_duplicates():
    assert next_permutation([1, 1, 5]) == [1, 5, 1]


def test_next_permutation_four_elements():
    assert next_permutation([1, 2, 3, 4]) == [1, 2, 4, 3]


def test_kth_permutation_first():
    assert kth_permutation([1, 2, 3], 0) == [1, 2, 3]


def test_kth_permutation_last():
    assert kth_permutation([1, 2, 3], 5) == [3, 2, 1]


def test_kth_permutation_middle():
    assert kth_permutation([1, 2, 3], 3) == [2, 3, 1]


def test_kth_permutation_out_of_range_high():
    assert kth_permutation([1, 2], 2) is None


def test_kth_permutation_negative_k():
    assert kth_permutation([1, 2], -1) is None


def test_kth_permutation_matches_reference_for_all_k():
    elems = [1, 2, 3, 4]
    reference = [list(p) for p in sorted(itertools.permutations(elems))]
    assert len(reference) == 24
    for k in range(24):
        assert kth_permutation(elems, k) == reference[k]


def test_next_permutation_chain_reproduces_reference_sequence():
    elems = [1, 2, 3, 4]
    reference = [list(p) for p in sorted(itertools.permutations(elems))]
    current = list(elems)
    seen = [current]
    nxt = next_permutation(current)
    while nxt is not None:
        seen.append(nxt)
        nxt = next_permutation(nxt)
    assert seen == reference
    # The last permutation is fully descending; its successor is None.
    assert next_permutation(reference[-1]) is None


def test_count_permutations_does_not_mutate_input():
    xs = [1, 1, 2]
    count_permutations(xs)
    assert xs == [1, 1, 2]


def test_next_permutation_does_not_mutate_input():
    xs = [1, 2, 3]
    next_permutation(xs)
    assert xs == [1, 2, 3]


def test_kth_permutation_does_not_mutate_input():
    xs = [3, 1, 2]
    kth_permutation(xs, 0)
    assert xs == [3, 1, 2]
