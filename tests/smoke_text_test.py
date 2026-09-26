"""Reference tests for src/smoke_text.py (TASK-STANOK-CC-166).

Covers the ticket contract:
- word_count(s): whitespace-separated words; an empty string and a
  whitespace-only string -> 0.
- caesar_shift(text, k): circular shift of Latin letters a-z/A-Z by k
  positions (k may be negative or greater than 26); every non-letter
  character is left unchanged.
"""

from smoke_text import caesar_shift, word_count


def test_word_count_empty_and_whitespace_only():
    assert word_count("") == 0
    assert word_count("   ") == 0


def test_word_count_simple():
    assert word_count("a b c") == 3


def test_word_count_mixed_whitespace():
    assert word_count("  hello,   world  ") == 2


def test_caesar_shift_basic():
    assert caesar_shift("abc", 1) == "bcd"


def test_caesar_shift_wraparound():
    assert caesar_shift("xyz", 3) == "abc"


def test_caesar_shift_negative_and_mixed_case():
    assert caesar_shift("Abc", -1) == "Zab"


def test_caesar_shift_full_rotation_identity():
    assert caesar_shift("a1b", 26) == "a1b"


def test_caesar_shift_rot13():
    assert caesar_shift("Hello, World!", 13) == "Uryyb, Jbeyq!"
