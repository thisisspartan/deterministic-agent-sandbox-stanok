"""Pure numeric helpers: greatest common divisor and primality test.

Two pure functions, no I/O, no state:

- ``gcd(a, b)`` — greatest common divisor of two integers, computed with
  the iterative Euclidean algorithm; ``gcd(0, 0) == 0``; negative
  arguments are reduced to their absolute value first.
- ``is_prime(n)`` — primality test; ``n < 2`` -> ``False``; trial division
  by every integer up to ``sqrt(n)`` inclusive.
"""

from __future__ import annotations


def gcd(a: int, b: int) -> int:
    """Greatest common divisor of integers ``a`` and ``b``.

    - negative arguments are reduced to their absolute value;
    - ``gcd(0, 0) == 0``;
    - otherwise the iterative Euclidean algorithm:
      ``while b: a, b = b, a % b``.
    """
    a = abs(a)
    b = abs(b)
    while b:
        a, b = b, a % b
    return a


def is_prime(n: int) -> bool:
    """Return ``True`` iff ``n`` is a prime number.

    - ``n < 2`` -> ``False``;
    - trial division by every integer ``d`` with ``2 <= d <= sqrt(n)``
      (inclusive); a divisor found -> ``False``.
    """
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True
