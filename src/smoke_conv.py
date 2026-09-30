"""Small pure conversion utilities.

Four pure functions, no I/O, no state, stdlib only:

- ``to_base(n, base)`` — non-negative int to a lowercase base-2..36
  string (digits ``0-9a-z``); ``ValueError`` for ``n < 0`` or ``base``
  outside 2..36.
- ``from_base(s, base)`` — parse a non-empty string of lowercase or
  uppercase digits in base 2..36 into an int; ``ValueError`` for an
  empty string, a digit not valid in the base, or ``base`` outside
  2..36. ``to_base`` and ``from_base`` are inverses.
- ``roman(n)`` — canonical uppercase Roman numeral for
  ``1 <= n <= 3999``; ``ValueError`` otherwise.
- ``roman_value(s)`` — parse a canonical uppercase Roman numeral into
  an int; ``ValueError`` for an empty string, any character outside
  ``MDCLXVI``, or a non-canonical numeral.
"""

from __future__ import annotations

import re

# Digits for bases up to 36: '0'..'9' then 'a'..'z'.
_DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"

# (value, symbol) pairs in descending order for canonical encoding.
_ROMAN_TABLE = (
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
)

_ROMAN_VALUES = {"M": 1000, "D": 500, "C": 100, "L": 50, "X": 10, "V": 5, "I": 1}

# Canonical uppercase Roman numeral: thousands, then hundreds, then tens,
# then ones — each group either a subtractive pair (I->V/X, X->L/C, C->M),
# a 5-multiple (V/L/D, never repeated), or 1-3 repeats of the 1-multiple
# (I/X/C/M). At least one group must be present (non-empty string).
_CANONICAL_ROMAN = re.compile(
    r"^M{0,3}"
    r"(CM|CD|D|C{1,3})?"
    r"(XC|XL|L|X{1,3})?"
    r"(IX|IV|V|I{1,3})?$"
)


def _check_base(base: int) -> None:
    if not 2 <= base <= 36:
        raise ValueError(f"base must be in 2..36, got {base}")


def to_base(n: int, base: int) -> str:
    """Convert a non-negative integer ``n`` to a string in ``base``.

    Digits are lowercase (``0-9a-z``). ``to_base(255, 16) == 'ff'``,
    ``to_base(0, 2) == '0'``, ``to_base(10, 2) == '1010'``.
    Raises ``ValueError`` for ``n < 0`` or ``base`` outside 2..36.
    """
    if n < 0:
        raise ValueError(f"to_base is defined for n >= 0, got {n}")
    _check_base(base)
    if n == 0:
        return "0"
    out = []
    while n:
        n, r = divmod(n, base)
        out.append(_DIGITS[r])
    return "".join(reversed(out))


def from_base(s: str, base: int) -> int:
    """Parse a non-empty string ``s`` of digits in ``base`` into an int.

    Lowercase and uppercase digits are both accepted.
    ``from_base('ff', 16) == 255``, ``from_base('1010', 2) == 10``.
    Raises ``ValueError`` for an empty string, a digit not valid in
    the base, or ``base`` outside 2..36.
    """
    _check_base(base)
    if not s:
        raise ValueError("from_base requires a non-empty string")
    n = 0
    for ch in s:
        d = _DIGITS.index(ch.lower())  # ValueError if ch is not a digit
        if d >= base:
            raise ValueError(f"digit {ch!r} is not valid in base {base}")
        n = n * base + d
    return n


def roman(n: int) -> str:
    """Convert ``n`` (``1 <= n <= 3999``) to a canonical uppercase Roman numeral.

    ``roman(1) == 'I'``, ``roman(4) == 'IV'``, ``roman(1994) == 'MCMXCIV'``,
    ``roman(3999) == 'MMMCMXCIX'``.
    Raises ``ValueError`` for ``n < 1`` or ``n > 3999``.
    """
    if not 1 <= n <= 3999:
        raise ValueError(f"roman is defined for 1 <= n <= 3999, got {n}")
    out = []
    for value, symbol in _ROMAN_TABLE:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)


def roman_value(s: str) -> int:
    """Parse a canonical uppercase Roman numeral ``s`` into an int.

    ``roman_value('MCMXCIV') == 1994``.
    Raises ``ValueError`` for an empty string, any character outside
    ``MDCLXVI``, or a non-canonical numeral (a smaller value may not be
    subtracted from a value more than 10x larger, and no digit may repeat
    more than 3 times — V, L, D never repeat at all).
    """
    if not s:
        raise ValueError("roman_value requires a non-empty string")
    if any(ch not in _ROMAN_VALUES for ch in s):
        bad = sorted({ch for ch in s if ch not in _ROMAN_VALUES})
        raise ValueError(f"roman_value: invalid character(s) {bad} in {s!r}")
    if not _CANONICAL_ROMAN.fullmatch(s):
        raise ValueError(f"roman_value: {s!r} is not a canonical Roman numeral")
    total = 0
    for i, ch in enumerate(s):
        v = _ROMAN_VALUES[ch]
        if i + 1 < len(s) and v < _ROMAN_VALUES[s[i + 1]]:
            total -= v  # subtractive pair (guaranteed valid by the regex)
        else:
            total += v
    return total
