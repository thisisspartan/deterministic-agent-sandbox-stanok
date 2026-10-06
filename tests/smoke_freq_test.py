"""Reference tests for src/smoke_freq.py (TASK-STANOK-CC-195).

Covers the ticket contract:
- freq_table(items): count of each item; empty list -> {}; string and
  int item vectors.
- top_k(freq, k): k most frequent (item, count) pairs, sorted by count
  DESCENDING, ties by item ASCENDING; k >= len(freq) -> all pairs;
  empty freq -> [].
- unique_count(items): number of distinct items; empty list -> 0.
- Invariants on a fixed deterministic 100-item list:
  sum(freq_table(items).values()) == len(items);
  sum(c for _, c in top_k(freq, len(freq))) == len(items);
  unique_count(items) == len(freq_table(items)).
- top_k on a fixed 5-key freq dict with all-distinct counts returns the
  keys in descending-count order (hand-computed).
"""

from smoke_freq import freq_table, top_k, unique_count


def test_freq_table_empty_list():
    assert freq_table([]) == {}


def test_freq_table_string_items():
    assert freq_table(["a", "b", "a"]) == {"a": 2, "b": 1}


def test_freq_table_int_items():
    assert freq_table([1, 1, 2, 2, 2]) == {1: 2, 2: 3}


def test_top_k_tie_broken_by_item_ascending():
    assert top_k({"a": 2, "b": 2, "c": 1}, 2) == [("a", 2), ("b", 2)]


def test_top_k_k_one():
    assert top_k({"a": 2, "b": 2, "c": 1}, 1) == [("a", 2)]


def test_top_k_k_exceeds_len_returns_all():
    assert top_k({"a": 2, "b": 2, "c": 1}, 5) == [("a", 2), ("b", 2), ("c", 1)]


def test_top_k_empty_freq():
    assert top_k({}, 3) == []


def test_unique_count_empty_list():
    assert unique_count([]) == 0


def test_unique_count_all_same():
    assert unique_count([1, 1, 1]) == 1


def test_unique_count_all_distinct():
    assert unique_count([1, 2, 3]) == 3


def test_unique_count_mixed_strings():
    assert unique_count(["x", "y", "x"]) == 2


def test_invariants_on_fixed_100_item_list():
    items = [i % 10 for i in range(100)]
    freq = freq_table(items)
    assert sum(freq.values()) == len(items)
    assert sum(c for _, c in top_k(freq, len(freq))) == len(items)
    assert unique_count(items) == len(freq)


def test_top_k_five_keys_all_distinct_counts():
    # Hand-computed: counts 9 > 7 > 5 > 2 > 1, so the order is
    # b, d, a, c, e.
    freq = {"a": 5, "b": 9, "c": 2, "d": 7, "e": 1}
    assert top_k(freq, 5) == [("b", 9), ("d", 7), ("a", 5), ("c", 2), ("e", 1)]
