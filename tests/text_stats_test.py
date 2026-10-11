"""Acceptance tests for src/text_stats.py (TASK-STANOK-CC-235).

Contract under test:
- word_count(text) -> int: number of whitespace-separated words ("" -> 0).
- top_words(text, n) -> list[tuple[str, int]]: the n most frequent lowercased
  words with counts, sorted by count descending then word ascending;
  n <= 0 -> []; fewer distinct words than n -> all of them.
"""

from src.text_stats import top_words, word_count


# --- word_count -------------------------------------------------------------

def test_word_count_empty_string():
    assert word_count("") == 0


def test_word_count_whitespace_only():
    # Spaces, tabs, newlines and their combinations carry no words.
    assert word_count("   ") == 0
    assert word_count("\n\t \r\n  ") == 0


def test_word_count_single_word():
    assert word_count("hello") == 1


def test_word_count_repeated_words_are_counted():
    # Repetition counts: a word appearing three times is three words.
    assert word_count("a b a b a") == 5


def test_word_count_case_is_irrelevant_to_counting():
    assert word_count("A a") == 2


def test_word_count_multiline_text():
    # Newlines are whitespace separators, not part of a word.
    assert word_count("one two\nthree\n\nfour\tfive") == 5


def test_word_count_leading_and_trailing_whitespace():
    assert word_count("  alpha   beta  \n") == 2


# --- top_words ------------------------------------------------------------

def test_top_words_empty_string():
    assert top_words("", 5) == []


def test_top_words_n_non_positive():
    # n <= 0 -> empty list, whatever the text.
    text = "a b c"
    assert top_words(text, 0) == []
    assert top_words(text, -1) == []
    assert top_words("", 0) == []


def test_top_words_single_word():
    assert top_words("hello", 1) == [("hello", 1)]


def test_top_words_counts_repeated_words():
    assert top_words("a b a c b a", 3) == [("a", 3), ("b", 2), ("c", 1)]


def test_top_words_case_folding():
    # "A a" is one word "a" with count 2.
    assert top_words("A a", 1) == [("a", 2)]
    assert top_words("Apple apple APPLE banana", 2) == [("apple", 3), ("banana", 1)]


def test_top_words_sorted_by_count_descending():
    result = top_words("x x x y y z", 3)
    assert result == [("x", 3), ("y", 2), ("z", 1)]
    counts = [count for _, count in result]
    assert counts == sorted(counts, reverse=True)


def test_top_words_ties_break_alphabetically():
    # Equal counts -> ascending word order.
    assert top_words("delta charlie bravo alpha", 4) == [
        ("alpha", 1),
        ("bravo", 1),
        ("charlie", 1),
        ("delta", 1),
    ]
    # Tie-breaking applies within a mixed distribution too.
    assert top_words("b b a a c c c", 3) == [("c", 3), ("a", 2), ("b", 2)]


def test_top_words_limits_to_n():
    result = top_words("a a a b b c", 2)
    assert result == [("a", 3), ("b", 2)]
    assert len(result) == 2


def test_top_words_n_larger_than_distinct_word_count():
    # Fewer distinct words than n -> return all of them.
    assert top_words("a b a", 100) == [("a", 2), ("b", 1)]


def test_top_words_multiline_text():
    # Newlines are whitespace: words split across lines are counted normally.
    assert top_words("one\ntwo one\n\nthree\ttwo one", 2) == [("one", 3), ("two", 2)]


def test_top_words_returns_pairs_of_str_and_int():
    result = top_words("a a b", 2)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in result)
    assert all(isinstance(word, str) and isinstance(count, int)
               for word, count in result)
