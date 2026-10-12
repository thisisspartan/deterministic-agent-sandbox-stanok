"""Acceptance tests for src/wordfreq.py (TASK-STANOK-CC-245).

Contract under test:
- tokenize(text) -> list[str]: lowercased word tokens; any non-alphanumeric,
  non-underscore character splits; digits and underscores stay inside a token;
  no empty token ever appears.
- count_words(text) -> dict[str, int]: token -> number of occurrences.
- top_words(text, n) -> list[tuple[str, int]]: (word, count) pairs sorted by
  count descending, then word ascending on ties; n clamped to
  [0, len(result)]; n <= 0 -> [].
"""

from src.wordfreq import count_words, tokenize, top_words


# --- tokenize ---------------------------------------------------------------

def test_tokenize_empty_text():
    assert tokenize("") == []


def test_tokenize_whitespace_only():
    # Runs of spaces, tabs, newlines and CRs carry no tokens.
    assert tokenize("   ") == []
    assert tokenize("\n\t \r\n  ") == []


def test_tokenize_single_token():
    assert tokenize("hello") == ["hello"]


def test_tokenize_lowercases_every_token():
    assert tokenize("Foo FOO foo") == ["foo", "foo", "foo"]
    assert tokenize("MiXeD CaSe") == ["mixed", "case"]


def test_tokenize_splits_on_punctuation_and_newlines():
    # "a,b;c\nd" -> four tokens; the separators are not kept.
    assert tokenize("a,b;c\nd") == ["a", "b", "c", "d"]


def test_tokenize_splits_on_any_non_word_character():
    text = "one!two?three.four(five)six[six]seven{eight}'nine\"ten"
    assert tokenize(text) == [
        "one", "two", "three", "four", "five",
        "six", "six", "seven", "eight", "nine", "ten",
    ]


def test_tokenize_keeps_digits_and_underscores():
    # "x_1" is a single token, not "x" and "1".
    assert tokenize("x_1") == ["x_1"]
    assert tokenize("abc123 _private_ 42") == ["abc123", "_private_", "42"]
    assert tokenize("snake_case_word") == ["snake_case_word"]


def test_tokenize_never_yields_empty_tokens():
    # Adjacent and leading/trailing separators must not produce "".
    tokens = tokenize(",,a,,,b,,  ,, ")
    assert tokens == ["a", "b"]
    assert "" not in tokens


def test_tokenize_separators_alone_are_dropped():
    assert tokenize("!!! ... ??? ---") == []


def test_tokenize_preserves_repetition_and_order():
    assert tokenize("b a b") == ["b", "a", "b"]


# --- count_words ------------------------------------------------------------

def test_count_words_empty_text():
    assert count_words("") == {}


def test_count_words_whitespace_only():
    assert count_words("   \n\t ") == {}


def test_count_words_case_folding():
    # "Foo FOO foo" is one token with count 3.
    assert count_words("Foo FOO foo") == {"foo": 3}


def test_count_words_punctuation_boundaries():
    assert count_words("a,b;c\nd") == {"a": 1, "b": 1, "c": 1, "d": 1}


def test_count_words_keeps_digits_and_underscores():
    assert count_words("x_1 x_1 y2") == {"x_1": 2, "y2": 1}


def test_count_words_exact_counts_on_pinned_text():
    text = (
        "the quick, the lazy; the quick\n"
        "dog_dog dog DOG 42 42\n"
        "End end END end"
    )
    assert count_words(text) == {
        "the": 3,
        "quick": 2,
        "lazy": 1,
        "dog_dog": 1,
        "dog": 2,
        "42": 2,
        "end": 4,
    }


def test_count_words_returns_str_to_int_mapping():
    result = count_words("a a b")
    assert isinstance(result, dict)
    assert all(isinstance(word, str) and isinstance(count, int)
               for word, count in result.items())


def test_count_words_matches_tokenize():
    # count_words is exactly the tally of tokenize's output.
    text = "A, a! b_b 1 1 1"
    tokens = tokenize(text)
    expected = {}
    for token in tokens:
        expected[token] = expected.get(token, 0) + 1
    assert count_words(text) == expected


# --- top_words --------------------------------------------------------------

def test_top_words_empty_text():
    assert top_words("", 5) == []
    assert top_words("", 0) == []


def test_top_words_n_non_positive():
    text = "a b c"
    assert top_words(text, 0) == []
    assert top_words(text, -1) == []
    assert top_words(text, -100) == []


def test_top_words_single_token():
    assert top_words("hello", 1) == [("hello", 1)]


def test_top_words_sorted_by_count_descending():
    result = top_words("x x x y y z", 3)
    assert result == [("x", 3), ("y", 2), ("z", 1)]
    counts = [count for _, count in result]
    assert counts == sorted(counts, reverse=True)


def test_top_words_ties_break_lexicographically():
    # Equal counts -> ascending word order.
    assert top_words("delta charlie bravo alpha", 4) == [
        ("alpha", 1),
        ("bravo", 1),
        ("charlie", 1),
        ("delta", 1),
    ]
    # Tie-breaking also applies inside a mixed distribution.
    assert top_words("b b a a c c c", 3) == [("c", 3), ("a", 2), ("b", 2)]
    # Digits sort before letters ("42" < "end").
    assert top_words("end end 42 42", 2) == [("42", 2), ("end", 2)]


def test_top_words_case_folding():
    assert top_words("Foo FOO foo", 1) == [("foo", 3)]


def test_top_words_punctuation_boundaries():
    assert top_words("a,b;c\nd", 4) == [("a", 1), ("b", 1), ("c", 1), ("d", 1)]


def test_top_words_keeps_digits_and_underscores():
    assert top_words("x_1 x_1 y2", 2) == [("x_1", 2), ("y2", 1)]


def test_top_words_limits_to_n():
    result = top_words("a a a b b c", 2)
    assert result == [("a", 3), ("b", 2)]
    assert len(result) == 2


def test_top_words_n_larger_than_vocabulary_is_clamped():
    # Fewer distinct tokens than n -> the whole vocabulary.
    assert top_words("a b a", 100) == [("a", 2), ("b", 1)]
    assert len(top_words("a b a", 100)) == len(count_words("a b a"))


def test_top_words_exact_result_on_pinned_text():
    # "the" and "lazy" both occur 3 times -> the tie breaks alphabetically.
    text = "the quick, the lazy; the quick\nlazy lazy 42"
    assert top_words(text, 3) == [("lazy", 3), ("the", 3), ("quick", 2)]
    assert top_words(text, 4) == [("lazy", 3), ("the", 3), ("quick", 2), ("42", 1)]


def test_top_words_returns_pairs_of_str_and_int():
    result = top_words("a a b", 2)
    assert all(isinstance(item, tuple) and len(item) == 2 for item in result)
    assert all(isinstance(word, str) and isinstance(count, int)
               for word, count in result)


def test_top_words_counts_match_count_words():
    text = "one one two two two three"
    counts = count_words(text)
    for word, count in top_words(text, 10):
        assert counts[word] == count
