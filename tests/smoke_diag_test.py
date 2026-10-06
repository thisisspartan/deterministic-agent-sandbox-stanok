"""Reference tests for src/smoke_diag.py (TASK-STANOK-CC-198).

Covers the ticket contract:
- main_diag(m): main diagonal (top-left to bottom-right); empty -> [].
- anti_diag(m): anti-diagonal (top-right to bottom-left); empty -> [].
- diag_sum(m): sum of the main diagonal; empty -> 0.
Plus a fixed deterministic 6x6 matrix and a fixed 4x4 matrix with
negatives whose main-diagonal sum is 0 (hand-computed).
"""

from smoke_diag import anti_diag, diag_sum, main_diag


# --- main_diag -----------------------------------------------------------

def test_main_diag_empty():
    assert main_diag([]) == []


def test_main_diag_1x1():
    assert main_diag([[5]]) == [5]


def test_main_diag_2x2():
    assert main_diag([[1, 2], [3, 4]]) == [1, 4]


def test_main_diag_3x3():
    assert main_diag([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 5, 9]


# --- anti_diag -----------------------------------------------------------

def test_anti_diag_empty():
    assert anti_diag([]) == []


def test_anti_diag_1x1():
    assert anti_diag([[5]]) == [5]


def test_anti_diag_2x2():
    assert anti_diag([[1, 2], [3, 4]]) == [2, 3]


def test_anti_diag_3x3():
    assert anti_diag([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [3, 5, 7]


# --- diag_sum ------------------------------------------------------------

def test_diag_sum_empty():
    assert diag_sum([]) == 0


def test_diag_sum_1x1():
    assert diag_sum([[5]]) == 5


def test_diag_sum_2x2():
    assert diag_sum([[1, 2], [3, 4]]) == 5


def test_diag_sum_3x3():
    assert diag_sum([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == 15


# --- fixed 6x6 matrix ----------------------------------------------------

def test_main_diag_6x6():
    m = [[i * 6 + j for j in range(6)] for i in range(6)]
    assert main_diag(m) == [m[i][i] for i in range(6)]


def test_anti_diag_6x6():
    m = [[i * 6 + j for j in range(6)] for i in range(6)]
    assert anti_diag(m) == [m[i][5 - i] for i in range(6)]


def test_diag_sum_6x6():
    m = [[i * 6 + j for j in range(6)] for i in range(6)]
    assert diag_sum(m) == sum(main_diag(m))


# --- fixed 4x4 with negatives, main-diagonal sum 0 -----------------------

def test_diag_sum_4x4_negatives_zero():
    # Main diagonal: 1, -1, 2, -2 -> 1 + (-1) + 2 + (-2) = 0 (hand-computed).
    m = [
        [1, 2, 3, 4],
        [5, -1, 6, 7],
        [8, 9, 2, 10],
        [11, 12, 13, -2],
    ]
    assert main_diag(m) == [1, -1, 2, -2]
    assert diag_sum(m) == 0


# --- purity --------------------------------------------------------------

def test_functions_do_not_mutate_input():
    m = [[1, 2, 3], [4, 5, 6], [7, 8, 9]]
    snapshot = [row[:] for row in m]
    main_diag(m)
    anti_diag(m)
    diag_sum(m)
    assert m == snapshot
