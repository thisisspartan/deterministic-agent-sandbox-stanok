"""Reference tests for src/smoke_str.py (TASK-STANOK-CC-170).

Covers the ticket contract:
- reverse_words(s): reverse the order of whitespace-separated words,
  single-space separation, leading/trailing whitespace stripped,
  multiple internal spaces collapsed to one; empty/whitespace-only -> "".
- is_palindrome(s): case-insensitive, ignoring non-alphanumeric
  (ASCII letters and digits only); empty result after filtering -> False.
- count_vowels(s): count ASCII vowels a e i o u, both cases.
"""

from smoke_str import count_vowels, is_palindrome, reverse_words


# --- reverse_words -------------------------------------------------------

def test_reverse_words_single_word():
    assert reverse_words("hello") == "hello"


def test_reverse_words_multiple_words():
    assert reverse_words("the quick brown fox") == "fox brown quick the"


def test_reverse_words_leading_trailing_spaces():
    assert reverse_words("  hello world  ") == "world hello"


def test_reverse_words_multiple_internal_spaces():
    assert reverse_words("a   b    c") == "c b a"


def test_reverse_words_mixed_whitespace():
    assert reverse_words("  one\ttwo\nthree  ") == "three two one"


def test_reverse_words_empty():
    assert reverse_words("") == ""


def test_reverse_words_whitespace_only():
    assert reverse_words("   \t\n  ") == ""


# --- is_palindrome -------------------------------------------------------

def test_is_palindrome_exact():
    assert is_palindrome("racecar") is True


def test_is_palindrome_case_insensitive():
    assert is_palindrome("RaceCar") is True


def test_is_palindrome_with_punctuation_and_spaces():
    assert is_palindrome("A man, a plan, a canal: Panama") is True


def test_is_palindrome_with_digits():
    assert is_palindrome("12321") is True
    assert is_palindrome("a1b1a") is True


def test_is_palindrome_empty_after_filter():
    assert is_palindrome("") is False
    assert is_palindrome("!!! ???") is False


def test_is_palindrome_not_palindrome():
    assert is_palindrome("hello") is False
    assert is_palindrome("ab") is False


# --- count_vowels --------------------------------------------------------

def test_count_vowels_mixed_case():
    assert count_vowels("Hello World") == 3


def test_count_vowels_no_vowels():
    assert count_vowels("rhythm") == 0


def test_count_vowels_digits_punctuation_ignored():
    assert count_vowels("a1b!c") == 1
    assert count_vowels("12345 !@#") == 0


def test_count_vowels_empty():
    assert count_vowels("") == 0
