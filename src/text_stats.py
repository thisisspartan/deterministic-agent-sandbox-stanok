"""text_stats — word counting and top-frequency words (TASK-STANOK-CC-235).

Contract (stdlib only):
- word_count(text) returns the number of whitespace-separated words in the
  string; "" (or whitespace-only text) gives 0. Case does not affect counting.
- top_words(text, n) returns the n most frequent words as
  list[tuple[str, int]] of (word, count): words are lowercased, sorted by
  count descending, then by word ascending. n <= 0 gives []; when the text has
  fewer distinct words than n, all of them are returned.
"""

from collections import Counter


def word_count(text: str) -> int:
    """Return the number of whitespace-separated words in `text`
    (any run of whitespace separates words; "" gives 0)."""
    return len(text.split())


def top_words(text: str, n: int) -> list[tuple[str, int]]:
    """Return the `n` most frequent lowercased words in `text` as
    (word, count) pairs, sorted by count descending then by word ascending.

    `n <= 0` returns []; if the text holds fewer than `n` distinct words, all
    of them are returned.
    """
    if n <= 0:
        return []
    counts = Counter(text.lower().split())
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return ranked[:n]
