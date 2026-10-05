"""Small pure interval-merge utilities.

An interval is a tuple ``(start, end)`` of integers with ``start <= end``,
half-open semantics: it covers the integer points
``start, start+1, ..., end-1``. A degenerate interval (``start == end``)
covers no points.

Three pure functions, no I/O, no state, stdlib only:

- ``merge_intervals(intervals)`` — merge overlapping OR touching
  intervals; result sorted by start; input not mutated.
- ``total_length(intervals)`` — total number of integer points covered
  after merging.
- ``point_coverage(intervals, point)`` — how many DISTINCT merged
  intervals contain ``point`` (``s <= point < e``).
"""

from __future__ import annotations


def merge_intervals(intervals: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Merge overlapping or touching intervals.

    Two intervals touch when one's ``end`` equals the other's ``start``
    (``(1, 3)`` and ``(3, 5)`` merge to ``(1, 5)``). Nested intervals are
    absorbed: ``(1, 10)`` and ``(2, 3)`` merge to ``(1, 10)``. The result
    is sorted by start. The input list is NOT mutated. Empty input
    returns ``[]``.

    ``merge_intervals([(1, 3), (2, 5), (7, 8)]) == [(1, 5), (7, 8)]``
    ``merge_intervals([(1, 3), (3, 5)]) == [(1, 5)]``
    ``merge_intervals([(1, 10), (2, 3)]) == [(1, 10)]``
    ``merge_intervals([]) == []``
    ``merge_intervals([(5, 6)]) == [(5, 6)]``
    ``merge_intervals([(2, 3), (1, 2)]) == [(1, 3)]``
    """
    if not intervals:
        return []
    items = sorted(intervals)
    merged: list[list[int]] = [list(items[0])]
    for start, end in items[1:]:
        last = merged[-1]
        if start <= last[1]:
            # overlapping or touching: extend (nested intervals are
            # absorbed because max() keeps the larger end)
            if end > last[1]:
                last[1] = end
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged]


def total_length(intervals: list[tuple[int, int]]) -> int:
    """Total number of integer points covered after merging.

    ``total_length([(1, 3), (2, 5), (7, 8)]) == 5`` (points 1,2,3,4 + 7)
    ``total_length([]) == 0``
    ``total_length([(1, 1)]) == 0`` (degenerate covers no points)
    ``total_length([(1, 5), (1, 5)]) == 4`` (no double counting)
    """
    return sum(end - start for start, end in merge_intervals(intervals))


def point_coverage(intervals: list[tuple[int, int]], point: int) -> int:
    """How many DISTINCT merged intervals contain ``point``.

    A point is contained in ``(s, e)`` when ``s <= point < e`` (half-open:
    the end is exclusive).

    ``point_coverage([(1, 3), (2, 5), (7, 8)], 2) == 1`` (merged to one)
    ``point_coverage([(1, 3), (7, 8)], 5) == 0``
    ``point_coverage([(1, 3), (7, 8)], 1) == 1``
    ``point_coverage([], 0) == 0``
    """
    return sum(
        1
        for start, end in merge_intervals(intervals)
        if start <= point < end
    )
