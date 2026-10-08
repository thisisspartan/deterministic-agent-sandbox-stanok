"""Tests for src/smoke_text.py — TASK-STANOK-CC-209.

Covers every vector in the ticket contract plus the deterministic
reference checks and the "inputs are never mutated" guarantee.
"""

from src import smoke_text


# ---------------------------------------------------------------------------
# is_palindrome
# ---------------------------------------------------------------------------

def test_is_palindrome_vectors():
    assert smoke_text.is_palindrome("") is True
    assert smoke_text.is_palindrome("a") is True
    assert smoke_text.is_palindrome("ab") is False
    assert smoke_text.is_palindrome("A man, a plan, a canal: Panama") is True
    assert smoke_text.is_palindrome("racecar") is True
    assert smoke_text.is_palindrome("race a car") is False
    assert smoke_text.is_palindrome("12321") is True
    assert smoke_text.is_palindrome("12345") is False


def test_is_palindrome_reversed_plus_self():
    # "".join(reversed(s)) + s is always a palindrome.
    s = "Ab3c"
    assert smoke_text.is_palindrome("".join(reversed(s)) + s) is True


# ---------------------------------------------------------------------------
# caesar
# ---------------------------------------------------------------------------

def test_caesar_vectors():
    assert smoke_text.caesar("abc", 3) == "def"
    assert smoke_text.caesar("xyz", 3) == "abc"
    assert smoke_text.caesar("XYZ", 3) == "ABC"
    assert smoke_text.caesar("Hello, World!", 3) == "Khoor, Zruog!"
    assert smoke_text.caesar("abc", -1) == "zab"
    assert smoke_text.caesar("abc", 29) == "def"
    assert smoke_text.caesar("", 5) == ""
    assert smoke_text.caesar("a1B2", 1) == "b1C2"


def test_caesar_round_trip():
    # Shifting forward then back by the same amount restores the input.
    s = "Mix3d Case! zZ"
    assert smoke_text.caesar(smoke_text.caesar(s, 7), -7) == s


# ---------------------------------------------------------------------------
# Inputs are never mutated
# ---------------------------------------------------------------------------

def test_inputs_are_not_mutated():
    # Strings are immutable; verify the returned value is a fresh string and
    # the argument reference is unchanged.
    text = "A man, a plan, a canal: Panama"
    assert smoke_text.is_palindrome(text) is True
    assert text == "A man, a plan, a canal: Panama"

    src_text = "Hello, World!"
    result = smoke_text.caesar(src_text, 3)
    assert result == "Khoor, Zruog!"
    assert src_text == "Hello, World!"
