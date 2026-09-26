"""Reference tests for src/smoke_struct.py (TASK-STANOK-CC-167).

Covers the ticket contract:
- flatten(nested): recursive flattening of arbitrarily nested lists into a
  single flat list; empty lists and lists of empty lists -> []; the input
  list is not mutated.
- chunk(lst, n): split a list into consecutive chunks of length n (the last
  chunk may be shorter); n < 1 -> ValueError; empty list -> [].
"""

import pytest

from smoke_struct import chunk, flatten


def test_flatten_empty_list():
    assert flatten([]) == []


def test_flatten_flat_list():
    assert flatten([1, 2, 3]) == [1, 2, 3]


def test_flatten_nested_lists():
    assert flatten([1, [2, 3], [[4], [5, 6]]]) == [1, 2, 3, 4, 5, 6]


def test_flatten_lists_of_empty_lists():
    assert flatten([[[]]]) == []


def test_flatten_deeply_nested():
    assert flatten([[1, [2, [3]]]]) == [1, 2, 3]


def test_flatten_does_not_mutate_input():
    original = [1, [2, 3], [[4], [5, 6]]]
    snapshot = [1, [2, 3], [[4], [5, 6]]]
    result = flatten(original)
    assert original == snapshot
    assert result == [1, 2, 3, 4, 5, 6]


def test_chunk_last_chunk_shorter():
    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]


def test_chunk_exact_multiple():
    assert chunk([1, 2, 3], 3) == [[1, 2, 3]]


def test_chunk_empty_list():
    assert chunk([], 2) == []


def test_chunk_n_larger_than_list():
    assert chunk([1, 2, 3, 4], 5) == [[1, 2, 3, 4]]


def test_chunk_zero_raises_value_error():
    with pytest.raises(ValueError):
        chunk([1], 0)


def test_chunk_negative_raises_value_error():
    with pytest.raises(ValueError):
        chunk([1], -1)
