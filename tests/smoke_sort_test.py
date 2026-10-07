"""Tests for src/smoke_sort.py — TASK-STANOK-CC-208.

Covers every vector in the ticket contract plus the deterministic
reference checks and the "inputs are never mutated" guarantee.
"""

import copy

from src import smoke_sort


# ---------------------------------------------------------------------------
# insertion_sort
# ---------------------------------------------------------------------------

def test_insertion_sort_vectors():
    assert smoke_sort.insertion_sort([]) == []
    assert smoke_sort.insertion_sort([3, 1, 2]) == [1, 2, 3]
    assert smoke_sort.insertion_sort([5, 5, 1]) == [1, 5, 5]
    assert smoke_sort.insertion_sort([2, -3, 0, -3, 2]) == [-3, -3, 0, 2, 2]
    assert smoke_sort.insertion_sort([1]) == [1]


def test_insertion_sort_matches_sorted():
    items = list(range(100, 0, -1))
    assert smoke_sort.insertion_sort(items) == sorted(items)


# ---------------------------------------------------------------------------
# merge_intervals
# ---------------------------------------------------------------------------

def test_merge_intervals_vectors():
    assert smoke_sort.merge_intervals([]) == []
    assert smoke_sort.merge_intervals([(1, 3), (2, 4)]) == [(1, 4)]
    assert smoke_sort.merge_intervals([(1, 2), (3, 4)]) == [(1, 2), (3, 4)]
    assert smoke_sort.merge_intervals([(1, 4), (4, 5)]) == [(1, 5)]
    assert smoke_sort.merge_intervals([(5, 6), (1, 2), (1, 5)]) == [(1, 6)]
    assert smoke_sort.merge_intervals([(2, 2), (1, 1)]) == [(1, 1), (2, 2)]


def test_merge_intervals_chain():
    intervals = [(i, i + 2) for i in range(0, 18)]
    assert smoke_sort.merge_intervals(intervals) == [(0, 19)]


# ---------------------------------------------------------------------------
# mode
# ---------------------------------------------------------------------------

def test_mode_vectors():
    assert smoke_sort.mode([]) is None
    assert smoke_sort.mode([1, 2, 2, 3]) == 2
    assert smoke_sort.mode([1, 1, 2, 2]) == 1
    assert smoke_sort.mode([7]) == 7
    assert smoke_sort.mode(["b", "a", "b", "a"]) == "a"
    assert smoke_sort.mode([3, 3, 2, 2, 1]) == 2


def test_mode_uniform_distribution():
    # [i % 7 for i in range(70)] — each value appears exactly 10 times;
    # tie broken by smallest value -> 0.
    assert smoke_sort.mode([i % 7 for i in range(70)]) == 0


# ---------------------------------------------------------------------------
# Inputs are never mutated
# ---------------------------------------------------------------------------

def test_inputs_are_not_mutated():
    items = [3, 1, 2]
    snapshot = copy.deepcopy(items)
    smoke_sort.insertion_sort(items)
    assert items == snapshot

    intervals = [(5, 6), (1, 2), (1, 5)]
    snapshot = copy.deepcopy(intervals)
    smoke_sort.merge_intervals(intervals)
    assert intervals == snapshot

    values = [1, 2, 2, 3]
    snapshot = copy.deepcopy(values)
    smoke_sort.mode(values)
    assert values == snapshot
