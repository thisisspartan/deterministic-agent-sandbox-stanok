"""Reference tests for src/smoke_matrix.py (TASK-STANOK-CC-179).

Covers the ticket contract:
- transpose(m): rows become columns; 2x3, 1x1, identity, float entries.
- matrix_multiply(a, b): standard product; 2x2, 2x3 . 3x2, left and
  right identity, 1xn . nx1, inner-dimension mismatch -> ValueError.
- is_square(m): square -> True, rectangular -> False, ragged -> False,
  1x1 -> True.
- Inputs are not mutated; results contain plain numbers.
"""

import pytest

from smoke_matrix import is_square, matrix_multiply, transpose


# --- transpose -----------------------------------------------------------

def test_transpose_2x3():
    assert transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]


def test_transpose_1x1():
    assert transpose([[7]]) == [[7]]


def test_transpose_identity():
    m = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    assert transpose(m) == m


def test_transpose_float_entries():
    assert transpose([[0.5, 1.5], [2.5, 3.5]]) == [[0.5, 2.5], [1.5, 3.5]]


def test_transpose_double_is_identity():
    m = [[1, 2], [3, 4], [5, 6]]
    assert transpose(transpose(m)) == m


def test_transpose_does_not_mutate_input():
    m = [[1, 2], [3, 4]]
    snapshot = [row[:] for row in m]
    transpose(m)
    assert m == snapshot


# --- matrix_multiply -----------------------------------------------------

def test_multiply_2x2():
    assert matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]]) == [[19, 22], [43, 50]]


def test_multiply_2x3_times_3x2():
    a = [[1, 2, 3], [4, 5, 6]]
    b = [[7, 8], [9, 10], [11, 12]]
    assert matrix_multiply(a, b) == [[58, 64], [139, 154]]


def test_multiply_left_identity():
    a = [[1, 2, 3], [4, 5, 6]]
    i = [[1, 0], [0, 1]]
    assert matrix_multiply(i, a) == a


def test_multiply_right_identity():
    a = [[1, 2], [3, 4]]
    i = [[1, 0], [0, 1]]
    assert matrix_multiply(a, i) == a


def test_multiply_1xn_times_nx1():
    a = [[1, 2, 3, 4]]
    b = [[5], [6], [7], [8]]
    assert matrix_multiply(a, b) == [[70]]


def test_multiply_inner_dimension_mismatch_raises():
    # 2x2 * 3x3: inner dims 2 != 3
    with pytest.raises(ValueError):
        matrix_multiply([[1, 2], [3, 4]], [[1, 2, 3], [4, 5, 6], [7, 8, 9]])
    # 2x3 * 2x2: inner dims 3 != 2
    with pytest.raises(ValueError):
        matrix_multiply([[1, 2, 3], [4, 5, 6]], [[1, 2], [3, 4]])


def test_multiply_float_entries():
    a = [[0.5, 1.5], [2.5, 3.5]]
    b = [[1.0, 0.0], [0.0, 1.0]]
    assert matrix_multiply(a, b) == a


def test_multiply_does_not_mutate_inputs():
    a = [[1, 2], [3, 4]]
    b = [[5, 6], [7, 8]]
    sa = [row[:] for row in a]
    sb = [row[:] for row in b]
    matrix_multiply(a, b)
    assert a == sa
    assert b == sb


# --- is_square -----------------------------------------------------------

def test_is_square_square():
    assert is_square([[1, 2], [3, 4]]) is True
    assert is_square([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) is True


def test_is_square_rectangular():
    assert is_square([[1, 2, 3], [4, 5, 6]]) is False
    assert is_square([[1, 2], [3, 4], [5, 6]]) is False


def test_is_square_ragged_is_false():
    assert is_square([[1, 2], [3]]) is False
    assert is_square([[1], [2, 3]]) is False


def test_is_square_1x1():
    assert is_square([[42]]) is True
