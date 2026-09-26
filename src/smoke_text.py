"""Pure text helpers: word counting and Caesar shift.

Two pure functions, no I/O, no state:

- ``word_count(s)`` — number of whitespace-separated words in ``s``;
  an empty string and a whitespace-only string -> 0.
- ``caesar_shift(text, k)`` — circular shift of Latin letters a-z/A-Z
  by ``k`` positions (``k`` may be negative or greater than 26);
  every non-letter character is left unchanged.
"""

from __future__ import annotations


def word_count(s: str) -> int:
    """Number of whitespace-separated words in ``s``.

    - separators are whitespace characters (``str.split`` semantics —
      any run of whitespace counts as one separator);
    - ``""`` and a whitespace-only string -> 0.
    """
    return len(s.split())


def caesar_shift(text: str, k: int) -> str:
    """Circularly shift the Latin letters of ``text`` by ``k`` positions.

    - only ``a-z`` and ``A-Z`` are shifted, preserving case;
    - ``k`` may be negative or greater than 26 — it is reduced modulo
      26 (Python's ``%`` keeps the result non-negative for negative
      ``k``);
    - every non-letter character is left unchanged.
    """
    out = []
    for ch in text:
        if "a" <= ch <= "z":
            out.append(chr(ord("a") + (ord(ch) - ord("a") + k) % 26))
        elif "A" <= ch <= "Z":
            out.append(chr(ord("A") + (ord(ch) - ord("A") + k) % 26))
        else:
            out.append(ch)
    return "".join(out)
