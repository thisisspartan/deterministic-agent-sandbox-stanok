"""Pure rectangular-grid statistics.

Three pure functions over rectangular grids (lists of lists of ints),
no imports, no I/O, no state, no randomness:

- ``grid_sum(grid)`` — the sum of all cells; empty grid -> 0.
- ``row_maxes(grid)`` — the max of each row, in row order; empty grid -> [].
- ``col_sums(grid)`` — the sum of each column of a rectangular grid;
  empty grid -> [].

Inputs are never mutated; results are plain ints / lists of ints.
"""


def grid_sum(grid):
    """Sum of all cells of ``grid``.

    ``grid_sum([[1, 2], [3, 4]]) == 10``; ``grid_sum([]) == 0``.
    The input is not mutated.
    """
    return sum(sum(row) for row in grid)


def row_maxes(grid):
    """Max of each row, in row order.

    ``row_maxes([[1, 3], [2, 9]]) == [3, 9]``; ``row_maxes([]) == []``.
    The input is not mutated.
    """
    return [max(row) for row in grid]


def col_sums(grid):
    """Sum of each column of a rectangular grid, in column order.

    ``col_sums([[1, 2, 3], [4, 5, 6]]) == [5, 7, 9]``;
    ``col_sums([]) == []``. The input is not mutated.
    """
    if not grid:
        return []
    return [sum(col) for col in zip(*grid)]
