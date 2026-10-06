"""Word statistics over whitespace-separated text.

Three pure functions, no imports, no I/O, no state, no randomness.
A "word" is any maximal run of non-whitespace characters; any run of
whitespace (spaces, tabs, newlines, ...) separates words, and leading
or trailing whitespace is ignored.

- ``count_words(text)`` — number of words in ``text`` (0 for empty input).
- ``most_frequent_word(text)`` — most frequent word, compared
  case-insensitively; the returned value is lowercase. Ties go to the
  lexicographically smallest word. ``None`` when there are no words.
- ``longest_word(text)`` — longest word with its original case
  preserved. Ties go to the word that appears FIRST in the text.
  ``None`` when there are no words.
"""


def count_words(text: str) -> int:
    """Number of whitespace-separated words in ``text``.

    Any run of whitespace separates words; leading/trailing whitespace
    is ignored. ``count_words("") == 0``, ``count_words("  a  b  ") == 2``.
    """
    return len(text.split())


def most_frequent_word(text: str) -> str | None:
    """Most frequent word, case-insensitive; returned in lowercase.

    Ties are broken by lexicographic order (smallest word wins).
    Returns ``None`` when ``text`` contains no words.

    - ``most_frequent_word("a b a c b") == "a"``  (a=2, b=2 -> tie -> "a")
    - ``most_frequent_word("Z z a") == "z"``      (z=2, a=1)
    """
    words = text.split()
    if not words:
        return None
    counts: dict[str, int] = {}
    for w in words:
        lw = w.lower()
        counts[lw] = counts.get(lw, 0) + 1
    # Highest count first, then lexicographically smallest word.
    return min(counts, key=lambda w: (-counts[w], w))


def longest_word(text: str) -> str | None:
    """Longest word, original case preserved; first occurrence wins ties.

    Returns ``None`` when ``text`` contains no words.

    - ``longest_word("hi hello there") == "hello"``  (hello/there both 5)
    - ``longest_word("  x  ") == "x"``
    """
    words = text.split()
    if not words:
        return None
    best = words[0]
    for w in words[1:]:
        if len(w) > len(best):
            best = w
    return best
