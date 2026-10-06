"""Pure diagonal statistics over square matrices.

Three pure functions, no I/O, no state, no imports, no randomness. A
matrix is a list of lists of ints (rows), e.g. ``[[1, 2], [3, 4]]``;
the empty matrix is ``[]``:

- ``main_diag(m)`` — the main diagonal (top-left to bottom-right) as a
  list; empty matrix -> ``[]``.
- ``anti_diag(m)`` — the anti-diagonal (top-right to bottom-left) as a
  list; empty matrix -> ``[]``.
- ``diag_sum(m)`` — the sum of the main diagonal; empty matrix -> 0.

Inputs are never mutated; results contain plain ints.
"""

from __future__ import annotations


def main_diag(matrix: list[list]) -> list:
    """Main diagonal (top-left to bottom-right) of a square matrix.

    ``main_diag([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [1, 5, 9]``.
    Empty matrix -> ``[]``. The input is not mutated.
    """
    return [row[i] for i, row in enumerate(matrix)]


def anti_diag(matrix: list[list]) -> list:
    """Anti-diagonal (top-right to bottom-left) of a square matrix.

    ``anti_diag([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == [3, 5, 7]``.
    Empty matrix -> ``[]``. The input is not mutated.
    """
    return [row[len(row) - 1 - i] for i, row in enumerate(matrix)]


def diag_sum(matrix: list[list]) -> int:
    """Sum of the main diagonal of a square matrix.

    ``diag_sum([[1, 2, 3], [4, 5, 6], [7, 8, 9]]) == 15``.
    Empty matrix -> 0. The input is not mutated.
    """
    return sum(main_diag(matrix))
