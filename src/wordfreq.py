"""wordfreq — tokenizing and word-frequency counting (TASK-STANOK-CC-245).

Contract (stdlib only, no I/O):
- tokenize(text) returns the lowercased word tokens of `text`: any
  non-alphanumeric, non-underscore character splits a token, digits and
  underscores stay inside one, and no empty token is ever produced.
- count_words(text) returns dict[str, int] mapping each token to its number
  of occurrences; "" gives {}.
- top_words(text, n) returns the (word, count) pairs sorted by count
  descending, then by word ascending on ties; `n` is clamped to
  [0, len(result)], so `n <= 0` gives [] and `n` beyond the vocabulary gives
  the whole vocabulary.
"""

import re
from collections import Counter

# A token is a maximal run of alphanumeric-or-underscore characters; every
# other character is a separator and is dropped.
_TOKEN_RE = re.compile(r"\w+")


def tokenize(text: str) -> list[str]:
    """Return the lowercased word tokens of `text`.

    Any non-alphanumeric, non-underscore character splits tokens; digits and
    underscores are kept inside a token; empty tokens never appear.
    """
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def count_words(text: str) -> dict[str, int]:
    """Return {token: occurrences} for the tokens of `text` ("" gives {})."""
    return dict(Counter(tokenize(text)))


def top_words(text: str, n: int) -> list[tuple[str, int]]:
    """Return up to `n` (word, count) pairs, most frequent first.

    Sorted by count descending, then by word ascending for equal counts.
    `n` is clamped to [0, len(result)]: `n <= 0` returns [], and an `n`
    larger than the vocabulary returns the whole vocabulary.
    """
    if n <= 0:
        return []
    counts = count_words(text)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    # Slicing clamps n to len(ranked) on its own.
    return ranked[:n]
