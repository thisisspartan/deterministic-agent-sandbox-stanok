"""wordcount — a pure in-memory word counter (CC-315).

Contract:
  C1  count_words(text: str) -> dict[str, int] is the module's only public
      function. A token is a maximal non-empty run of [A-Za-z0-9_]; every
      token is lowercased. Everything else — whitespace, punctuation,
      non-ASCII — is a separator and is never counted.
  C2  The result maps token -> count, in insertion order of first appearance.
      A text with no words yields {}.
  C3  Pure: stdlib `re` only, no I/O, no state kept between calls, the
      argument is never mutated.
"""

from __future__ import annotations

import re

# The character class is ASCII by construction: a code-point range in a
# class does not fold case or widen to Unicode letters, so non-ASCII text
# falls through as a separator (C1) without needing re.ASCII.
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def count_words(text: str) -> dict[str, int]:
    """Count lowercased words in *text* (see the module docstring, C1..C3).

    Iterating matches in text order gives the dict its required insertion
    order (C2): a key is created at the first appearance of its token.
    """
    counts: dict[str, int] = {}
    for match in _TOKEN_RE.finditer(text):
        token = match.group().lower()
        counts[token] = counts.get(token, 0) + 1
    return counts
