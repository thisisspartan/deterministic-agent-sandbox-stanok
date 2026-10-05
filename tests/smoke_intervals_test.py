"""Reference tests for src/smoke_intervals.py (TASK-STANOK-CC-188).

Covers the ticket contract:
- merge_intervals: merging of overlapping OR touching intervals, nested
  absorption, unsorted input, empty input, no mutation of the input
  list, negative coordinates, degenerate intervals.
- total_length: total number of integer points covered after merging
  (no double counting).
- point_coverage: how many DISTINCT merged intervals contain a point
  (half-open semantics: end is exclusive).
"""

import copy

from smoke_intervals import merge_intervals, point_coverage, total_length


# --- merge_intervals ---------------------------------------------------

def test_merge_overlapping_and_disjoint():
    assert merge_intervals([(1, 3), (2, 5), (7, 8)]) == [(1, 5), (7, 8)]


def test_merge_touching():
    assert merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]


def test_merge_nested_absorbed():
    assert merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]


def test_merge_empty():
    assert merge_intervals([]) == []


def test_merge_single():
    assert merge_intervals([(5, 6)]) == [(5, 6)]


def test_merge_unsorted_input():
    assert merge_intervals([(2, 3), (1, 2)]) == [(1, 3)]


def test_merge_chain_of_touching():
    assert merge_intervals([(0, 1), (1, 2), (2, 3)]) == [(0, 3)]


def test_merge_fully_disjoint_sorted_unchanged():
    assert merge_intervals([(1, 2), (5, 6), (9, 10)]) == [(1, 2), (5, 6), (9, 10)]


def test_merge_fully_disjoint_unsorted_returned_sorted():
    assert merge_intervals([(5, 6), (1, 2), (9, 10)]) == [(1, 2), (5, 6), (9, 10)]


def test_merge_input_not_mutated():
    original = [(2, 5), (1, 3), (7, 8)]
    snapshot = copy.deepcopy(original)
    merge_intervals(original)
    assert original == snapshot


def test_merge_negative_coordinates():
    assert merge_intervals([(-5, -2), (-3, 0)]) == [(-5, 0)]


def test_merge_degenerate_does_not_break_neighbours():
    assert merge_intervals([(1, 2), (2, 4)]) == [(1, 4)]


# --- total_length ------------------------------------------------------

def test_total_length_basic():
    # points 1,2,3,4 + 7
    assert total_length([(1, 3), (2, 5), (7, 8)]) == 5


def test_total_length_empty():
    assert total_length([]) == 0


def test_total_length_degenerate():
    assert total_length([(1, 1)]) == 0


def test_total_length_no_double_counting():
    assert total_length([(1, 5), (1, 5)]) == 4


# --- point_coverage ----------------------------------------------------

def test_point_coverage_merged_counts_once():
    assert point_coverage([(1, 3), (2, 5), (7, 8)], 2) == 1


def test_point_coverage_gap():
    assert point_coverage([(1, 3), (7, 8)], 5) == 0


def test_point_coverage_start_inclusive():
    assert point_coverage([(1, 3), (7, 8)], 1) == 1


def test_point_coverage_empty():
    assert point_coverage([], 0) == 0


def test_point_coverage_boundary_half_open():
    assert point_coverage([(1, 3)], 1) == 1
    assert point_coverage([(1, 3)], 3) == 0
