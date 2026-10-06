"""Frequency-statistics utilities.

Three pure functions, no imports, no I/O, no state, no randomness:

- ``freq_table(items)`` — count of each item; empty list -> ``{}``.
- ``top_k(freq, k)`` — the ``k`` most frequent ``(item, count)`` pairs,
  sorted by count DESCENDING, ties by item ASCENDING (items are
  comparable); ``k >= len(freq)`` -> all pairs; empty freq -> ``[]``.
- ``unique_count(items)`` — number of distinct items; empty list -> 0.

Inputs are never mutated.
"""


def freq_table(items):
    """Count of each item in ``items``.

    ``freq_table(["a", "b", "a"]) == {"a": 2, "b": 1}``;
    ``freq_table([]) == {}``. The input list is not mutated.
    """
    table = {}
    for x in items:
        table[x] = table.get(x, 0) + 1
    return table


def top_k(freq, k):
    """The ``k`` most frequent ``(item, count)`` pairs from ``freq``.

    Sorted by count DESCENDING, ties by item ASCENDING (items are
    comparable). ``k >= len(freq)`` returns all pairs; an empty ``freq``
    returns ``[]``.

    ``top_k({"a": 2, "b": 2, "c": 1}, 2) == [("a", 2), ("b", 2)]``.
    The input dict is not mutated.
    """
    pairs = sorted(freq.items(), key=lambda p: (-p[1], p[0]))
    return pairs[: max(k, 0)]


def unique_count(items):
    """Number of distinct items in ``items``.

    ``unique_count([1, 1, 1]) == 1``; ``unique_count([]) == 0``.
    The input list is not mutated.
    """
    return len(freq_table(items))
