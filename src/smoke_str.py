"""Pure string utilities: word reversal, palindrome check, vowel count.

Three pure functions, no I/O, no state, no third-party imports:

- ``reverse_words(s)`` — reverse the order of whitespace-separated words,
  preserving single-space separation; leading/trailing whitespace is
  stripped and runs of internal whitespace collapse to one space.
- ``is_palindrome(s)`` — True if ``s`` reads the same forwards and
  backwards, case-insensitive, ignoring non-alphanumeric characters
  (ASCII letters and digits only).
- ``count_vowels(s)`` — number of ASCII vowels (a e i o u, both cases).
"""

from __future__ import annotations

_VOWELS = frozenset("aeiouAEIOU")


def reverse_words(s: str) -> str:
    """Reverse the order of whitespace-separated words in ``s``.

    - words are maximal runs of non-whitespace (``str.split`` semantics —
      any run of whitespace is one separator);
    - the result uses single spaces between words, with no leading or
      trailing whitespace;
    - ``""`` and a whitespace-only string -> ``""``.
    """
    return " ".join(s.split()[::-1])


def is_palindrome(s: str) -> bool:
    """True if ``s`` is a palindrome, case-insensitive.

    - only ASCII letters and digits are considered; every other
      character (punctuation, spaces, non-ASCII) is ignored;
    - comparison is case-insensitive;
    - if no alphanumeric characters remain after filtering -> False.
    """
    filtered = [ch.lower() for ch in s if ch.isascii() and ch.isalnum()]
    if not filtered:
        return False
    return filtered == filtered[::-1]


def count_vowels(s: str) -> int:
    """Count ASCII vowels (a e i o u, both cases) in ``s``.

    Digits, punctuation, whitespace and non-ASCII characters are
    ignored.
    """
    return sum(1 for ch in s if ch in _VOWELS)
