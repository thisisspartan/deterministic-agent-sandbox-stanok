"""Small integer utilities.

Three pure functions, no I/O, no state, stdlib only:

- ``digit_sum(n)`` — sum of the decimal digits of ``n``; defined for
  ``n >= 0`` only; negative input raises ``ValueError``.
- ``is_perfect(n)`` — ``True`` iff ``n > 0`` and the sum of its proper
  divisors (divisors excluding ``n`` itself) equals ``n``; total over
  all ints (``n <= 0`` is ``False``, never raises).
- ``collatz_steps(n)`` — number of Collatz steps to reach 1; defined
  for ``n >= 1`` only; ``n < 1`` raises ``ValueError``.
"""

from __future__ import annotations


def digit_sum(n: int) -> int:
    """Sum of the decimal digits of ``n``.

    Defined for ``n >= 0`` only; negative input raises ``ValueError``
    (the message mentions the offending value).
    ``digit_sum(0) == 0``, ``digit_sum(123) == 6``, ``digit_sum(101) == 2``.
    """
    if n < 0:
        raise ValueError(f"digit_sum is defined for n >= 0, got {n}")
    return sum(int(d) for d in str(n))


def is_perfect(n: int) -> bool:
    """Return ``True`` iff ``n`` is a perfect number.

    ``n`` is perfect iff ``n > 0`` and the sum of its proper divisors
    (divisors excluding ``n`` itself) equals ``n``.
    Total over all ints: ``is_perfect(6) is True`` (1+2+3),
    ``is_perfect(28) is True``, ``is_perfect(1) is False``,
    ``is_perfect(0) is False``, ``is_perfect(-28) is False``.

    Trial division up to ``sqrt(n)`` — fast enough for ``n`` up to 10**6.
    """
    if n <= 0:
        return False
    total = 1  # 1 is a proper divisor of every n > 1
    i = 2
    while i * i <= n:
        if n % i == 0:
            total += i
            j = n // i
            if j != i:
                total += j
        i += 1
    return n > 1 and total == n


def collatz_steps(n: int) -> int:
    """Number of Collatz steps to reach 1.

    Each transformation counts one step: even ``n`` -> ``n // 2``,
    odd ``n`` -> ``3 * n + 1``. Defined for ``n >= 1`` only;
    ``n < 1`` raises ``ValueError`` (the message mentions the
    offending value).
    ``collatz_steps(1) == 0``, ``collatz_steps(6) == 8``,
    ``collatz_steps(7) == 16``, ``collatz_steps(8) == 3``.
    """
    if n < 1:
        raise ValueError(f"collatz_steps is defined for n >= 1, got {n}")
    steps = 0
    while n != 1:
        n = n // 2 if n % 2 == 0 else 3 * n + 1
        steps += 1
    return steps
