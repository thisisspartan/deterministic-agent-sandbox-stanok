"""Reference tests for src/smoke_grid.py (TASK-STANOK-CC-194).

Covers the ticket contract:
- grid_sum(grid): sum of all cells; empty grid -> 0.
- row_maxes(grid): max of each row, in row order; empty grid -> [].
- col_sums(grid): sum of each column (rectangular grid); empty grid -> [].
- A fixed deterministic 5x7 grid checked against builtin references.
- A fixed 3x3 grid with negatives whose grid_sum is 0 (hand-computed).
"""

from smoke_grid import col_sums, grid_sum, row_maxes


# --- grid_sum -------------------------------------------------------------

def test_grid_sum_empty():
    assert grid_sum([]) == 0


def test_grid_sum_2x2():
    assert grid_sum([[1, 2], [3, 4]]) == 10


def test_grid_sum_negatives_cancel():
    assert grid_sum([[-1, 2], [3, -4]]) == 0


def test_grid_sum_1x1():
    assert grid_sum([[7]]) == 7


# --- row_maxes -------------------------------------------------------------

def test_row_maxes_empty():
    assert row_maxes([]) == []


def test_row_maxes_2x2():
    assert row_maxes([[1, 3], [2, 9]]) == [3, 9]


def test_row_maxes_single_negative():
    assert row_maxes([[-5]]) == [-5]


def test_row_maxes_single_row():
    assert row_maxes([[1, 2, 3]]) == [3]


# --- col_sums --------------------------------------------------------------

def test_col_sums_empty():
    assert col_sums([]) == []


def test_col_sums_2x3():
    assert col_sums([[1, 2, 3], [4, 5, 6]]) == [5, 7, 9]


def test_col_sums_2x2():
    assert col_sums([[1, 2], [3, 4]]) == [4, 6]


def test_col_sums_1x1():
    assert col_sums([[10]]) == [10]


# --- fixed 5x7 grid vs builtin references ----------------------------------

def _grid_5x7():
    return [[i * 7 + j for j in range(7)] for i in range(5)]


def test_grid_sum_5x7_matches_builtin():
    grid = _grid_5x7()
    assert grid_sum(grid) == sum(sum(row) for row in grid)


def test_row_maxes_5x7_matches_builtin():
    grid = _grid_5x7()
    assert row_maxes(grid) == [max(row) for row in grid]


def test_col_sums_5x7_matches_zip_reference():
    grid = _grid_5x7()
    assert col_sums(grid) == [sum(col) for col in zip(*grid)]


# --- fixed 3x3 grid with negatives, hand-computed sum 0 --------------------

def test_grid_sum_3x3_negatives_zero():
    # Row sums: 1+2+3 = 6; -4+5-6 = -5; 7-8+0 = -1. Total: 6-5-1 = 0.
    grid = [[1, 2, 3], [-4, 5, -6], [7, -8, 0]]
    assert grid_sum(grid) == 0


def test_row_maxes_3x3_negatives():
    grid = [[1, 2, 3], [-4, 5, -6], [7, -8, 0]]
    assert row_maxes(grid) == [3, 5, 7]


def test_col_sums_3x3_negatives():
    # Column sums: 1-4+7 = 4; 2+5-8 = -1; 3-6+0 = -3.
    grid = [[1, 2, 3], [-4, 5, -6], [7, -8, 0]]
    assert col_sums(grid) == [4, -1, -3]
