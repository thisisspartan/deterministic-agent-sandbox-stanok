"""Digit statistics on integers.

Three pure functions, no imports, no randomness, no I/O, no state:

- ``digit_product(n)`` — product of the decimal digits of ``abs(n)``.
- ``is_palin_number(n)`` — ``True`` iff the decimal representation of
  ``n`` is a palindrome; negative numbers are ``False`` (the minus
  sign breaks symmetry).
- ``sum_of_squares_of_digits(n)`` — sum of squares of the decimal
  digits of ``abs(n)``.
"""


def digit_product(n: int) -> int:
    """Product of the decimal digits of ``abs(n)``.

    ``digit_product(0) == 0``, ``digit_product(7) == 7``,
    ``digit_product(123) == 6``, ``digit_product(105) == 0``,
    ``digit_product(-24) == 8``. Any zero digit makes the product 0.
    """
    n = abs(n)
    if n == 0:
        return 0
    product = 1
    while n:
        product *= n % 10
        n //= 10
    return product


def is_palin_number(n: int) -> bool:
    """``True`` iff the decimal representation of ``n`` is a palindrome.

    ``is_palin_number(0) is True``, ``is_palin_number(7) is True``,
    ``is_palin_number(121) is True``, ``is_palin_number(12321) is True``,
    ``is_palin_number(123) is False``. Negative numbers are always
    ``False``: the minus sign breaks the symmetry
    (``is_palin_number(-121) is False``).
    """
    s = str(n)
    return s == s[::-1]


def sum_of_squares_of_digits(n: int) -> int:
    """Sum of squares of the decimal digits of ``abs(n)``.

    ``sum_of_squares_of_digits(0) == 0``,
    ``sum_of_squares_of_digits(10) == 1``,
    ``sum_of_squares_of_digits(123) == 14``,
    ``sum_of_squares_of_digits(-12) == 5``,
    ``sum_of_squares_of_digits(99) == 162``.
    """
    n = abs(n)
    total = 0
    while n:
        d = n % 10
        total += d * d
        n //= 10
    return total
