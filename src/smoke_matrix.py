"""Pure matrix utilities.

Three pure functions, no I/O, no state, stdlib only. A matrix is a
non-empty list of non-empty lists of numbers (rows), e.g.
``[[1, 2], [3, 4]]``:

- ``transpose(m)`` — the transpose of a rectangular matrix (rows become
  columns).
- ``matrix_multiply(a, b)`` — the standard matrix product; ``a`` is
  m×n, ``b`` is n×p, the result is m×p. Raises ``ValueError`` when the
  inner dimensions do not match.
- ``is_square(m)`` — True iff the matrix is non-empty, every row has the
  same length, and that length equals the number of rows. Ragged input
  gives ``False`` (no exception).

Inputs are never mutated; results contain plain numbers.
"""

from __future__ import annotations


def transpose(m: list[list]) -> list[list]:
    """Transpose of a rectangular matrix: rows become columns.

    ``transpose([[1, 2, 3], [4, 5, 6]]) == [[1, 4], [2, 5], [3, 6]]``.
    Total for any non-empty list of non-empty rows; the input is not
    mutated.
    """
    return [[row[j] for row in m] for j in range(len(m[0]))]


def matrix_multiply(a: list[list], b: list[list]) -> list[list]:
    """Standard matrix product of ``a`` (m×n) and ``b`` (n×p).

    ``matrix_multiply([[1, 2], [3, 4]], [[5, 6], [7, 8]]) ==
    [[19, 22], [43, 50]]``. Raises ``ValueError`` when the inner
    dimensions do not match (``len(a[0]) != len(b)``). Inputs are not
    mutated; the result contains plain numbers.
    """
    if len(a[0]) != len(b):
        raise ValueError(
            f"inner dimensions do not match: {len(a)}x{len(a[0])} * "
            f"{len(b)}x{len(b[0])}"
        )
    return [
        [sum(a[i][k] * b[k][j] for k in range(len(b))) for j in range(len(b[0]))]
        for i in range(len(a))
    ]


def is_square(m: list[list]) -> bool:
    """True iff ``m`` is a non-empty square matrix.

    Every row must have the same length and that length must equal the
    number of rows. Ragged input gives ``False`` (no exception).
    """
    n = len(m)
    return n > 0 and all(len(row) == n for row in m)
