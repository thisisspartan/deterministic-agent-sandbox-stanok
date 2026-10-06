"""Reference tests for src/smoke_words.py (TASK-STANOK-CC-191).

Covers the ticket contract:
- count_words(text): whitespace-separated token count; empty string,
  single word, leading/trailing/multiple whitespace, mixed whitespace
  (newline, tab).
- most_frequent_word(text): case-insensitive frequency, lowercase
  result, ties -> lexicographically smallest, None for empty input.
- longest_word(text): longest word with original case preserved,
  ties -> first occurrence, None for empty input.
- A fixed 500-character deterministic text: the sum of per-word
  occurrence counts equals count_words(text), and most_frequent_word
  returns one of the words actually present.
- longest_word on a fixed list of 50 words of varying lengths returns
  the expected word (computed by hand).
"""

from smoke_words import count_words, longest_word, most_frequent_word


# ---------------------------------------------------------------- count_words

def test_count_words_empty():
    assert count_words("") == 0


def test_count_words_single_word():
    assert count_words("hello") == 1


def test_count_words_leading_trailing_and_repeated_whitespace():
    assert count_words("  a  b  ") == 2


def test_count_words_mixed_whitespace():
    assert count_words("a\nb\tc") == 3


# ---------------------------------------------------- most_frequent_word

def test_most_frequent_word_empty():
    assert most_frequent_word("") is None


def test_most_frequent_word_tie_goes_to_lexicographically_smallest():
    # a=2, b=2, c=1 -> tie between a and b -> "a"
    assert most_frequent_word("a b a c b") == "a"


def test_most_frequent_word_unique_winner():
    assert most_frequent_word("the cat the dog the") == "the"


def test_most_frequent_word_case_insensitive_returns_lowercase():
    # z=2 (Z + z), a=1 -> "z"
    assert most_frequent_word("Z z a") == "z"


# ----------------------------------------------------------- longest_word

def test_longest_word_empty():
    assert longest_word("") is None


def test_longest_word_tie_goes_to_first_occurrence():
    # hello=5, there=5 -> "hello" (appears first)
    assert longest_word("hi hello there") == "hello"


def test_longest_word_unique_longest():
    assert longest_word("a bb") == "bb"


def test_longest_word_single_word_with_surrounding_whitespace():
    assert longest_word("  x  ") == "x"


# ------------------------------------------- fixed 500-character text check

# Deterministic 500-character text: 24 repetitions of a 20-character
# sentence plus 5 extra "the " tokens (24*20 + 5*4 = 500 characters).
# Per-word counts: the=29, quick=24, brown=24, fox=24 (sum 101).
BIG_TEXT = "the quick brown fox " * 24 + "the the the the the "


def test_big_text_is_exactly_500_characters():
    assert len(BIG_TEXT) == 500


def test_big_text_per_word_counts_sum_to_count_words():
    counts = {}
    for w in BIG_TEXT.split():
        counts[w] = counts.get(w, 0) + 1
    assert sum(counts.values()) == count_words(BIG_TEXT)
    assert count_words(BIG_TEXT) == 101


def test_big_text_most_frequent_word_is_a_word_present_in_text():
    present = set(BIG_TEXT.split())
    assert most_frequent_word(BIG_TEXT) in present
    # Unique winner by hand: the=29 > quick=brown=fox=24.
    assert most_frequent_word(BIG_TEXT) == "the"


# ------------------------------------- 50 words of varying lengths check

# 50 words: lengths 1-6 each appear 8 times, length 7 appears twice
# (positions 3 and 40). Longest length is 7; the first length-7 word is
# "abcdefg" at position 3, so it must win the tie.
WORDS_50 = [
    "a", "bb", "abcdefg", "ccc", "dddd", "eeeee", "ffffff", "g",
    "hh", "iii", "jjjj", "kkkkk", "llllll", "m", "nn", "ooo",
    "pppp", "qqqqq", "rrrrrr", "s", "tt", "uuu", "vvvv", "wwwww",
    "xxxxxx", "y", "zz", "aaa", "bbbb", "ccccc", "dddddd", "e",
    "ff", "ggg", "hhhh", "iiiii", "jjjjjj", "k", "ll", "abcdefg",
    "mmm", "nnnn", "ooooo", "pppppp", "q", "rr", "sss", "tttt",
    "uuuuu", "vvvvvv",
]


def test_words_50_list_shape():
    assert len(WORDS_50) == 50
    lengths = sorted(len(w) for w in WORDS_50)
    assert lengths == [1] * 8 + [2] * 8 + [3] * 8 + [4] * 8 + [5] * 8 + [6] * 8 + [7] * 2


def test_longest_word_on_50_words_returns_first_longest():
    assert longest_word(" ".join(WORDS_50)) == "abcdefg"
