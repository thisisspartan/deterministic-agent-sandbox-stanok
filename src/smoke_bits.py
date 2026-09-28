"""Small integer-bit utilities.

Three pure functions, no I/O, no state, stdlib only:

- ``popcount(n)`` — number of 1-bits in ``n``; defined for ``n >= 0``
  only; negative input raises ``ValueError``.
- ``is_power_of_two(n)`` — ``True`` iff ``n == 2**k`` for some ``k >= 0``;
  total over all ints (``0`` and negatives are ``False``).
- ``parity(n)`` — ``True`` iff ``popcount(n)`` is odd; defined for
  ``n >= 0`` only; negative input raises ``ValueError``.
"""

from __future__ import annotations


def popcount(n: int) -> int:
    """Number of 1-bits in the binary representation of ``n``.

    Defined for ``n >= 0`` only; negative input raises ``ValueError``
    (the message mentions the offending value).
    ``popcount(0) == 0``, ``popcount(7) == 3``, ``popcount(0xFF) == 8``.
    """
    if n < 0:
        raise ValueError(f"popcount is defined for n >= 0, got {n}")
    return bin(n).count("1")


def is_power_of_two(n: int) -> bool:
    """Return ``True`` iff ``n`` is a power of two (``n == 2**k``, ``k >= 0``).

    Total over all ints: ``is_power_of_two(1) is True``,
    ``is_power_of_two(0) is False``, ``is_power_of_two(-16) is False``.
    """
    return n > 0 and (n & (n - 1)) == 0


def parity(n: int) -> bool:
    """Return ``True`` iff ``popcount(n)`` is odd.

    Defined for ``n >= 0`` only; negative input raises ``ValueError``
    (the message mentions the offending value).
    ``parity(0) is False``, ``parity(1) is True``, ``parity(7) is False``.
    """
    if n < 0:
        raise ValueError(f"parity is defined for n >= 0, got {n}")
    return popcount(n) % 2 == 1
