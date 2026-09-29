"""Small sequence utilities.

Three pure functions, no I/O, no state, stdlib only:

- ``fib(n)`` — the n-th Fibonacci number, iterative; ``fib(0) == 0``,
  ``fib(1) == 1``; raises ``ValueError`` for negative ``n``.
- ``is_monotonic(xs)`` — True iff the list is non-decreasing
  (``xs[i] <= xs[i+1]`` for all i); empty and single-element lists
  are monotonic.
- ``run_length_encode(xs)`` — run-length encoding as a list of
  ``[value, count]`` pairs in first-occurrence order; empty input -> ``[]``.

Inputs are never mutated (the original list order and contents are
preserved). ``fib`` is total for all ``n >= 0``; ``is_monotonic`` and
``run_length_encode`` are total for any list of comparable elements.
"""

from __future__ import annotations


def fib(n: int) -> int:
    """The n-th Fibonacci number, computed iteratively.

    ``fib(0) == 0``, ``fib(1) == 1``, ``fib(10) == 55``.
    Raises ``ValueError`` for negative ``n``.
    """
    if n < 0:
        raise ValueError(f"fib: n must be >= 0, got {n}")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


def is_monotonic(xs: list) -> bool:
    """True iff the list is non-decreasing.

    ``xs[i] <= xs[i+1]`` for every adjacent pair. Empty and
    single-element lists are monotonic.

    - ``is_monotonic([1, 1, 2, 3]) is True``
    - ``is_monotonic([3, 1, 2]) is False``

    The input is not mutated.
    """
    for i in range(len(xs) - 1):
        if xs[i] > xs[i + 1]:
            return False
    return True


def run_length_encode(xs: list) -> list:
    """Run-length encode a list as ``[value, count]`` pairs.

    Pairs appear in first-occurrence order.

    - ``run_length_encode([1, 1, 2, 3, 3, 3]) == [[1, 2], [2, 1], [3, 3]]``
    - ``run_length_encode([]) == []``

    The input is not mutated.
    """
    out: list = []
    for x in xs:
        if out and out[-1][0] == x:
            out[-1][1] += 1
        else:
            out.append([x, 1])
    return out
