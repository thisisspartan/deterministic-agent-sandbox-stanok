"""Reference tests for src/smoke_digits.py (TASK-STANOK-CC-192).

Covers the ticket contract:
- digit_product(n): product of the decimal digits of abs(n).
- is_palin_number(n): True iff the decimal representation of n is a
  palindrome; negative numbers are False (the minus sign breaks symmetry).
- sum_of_squares_of_digits(n): sum of squares of the decimal digits of
  abs(n).
Plus cross-checks against string-based references over the fixed
deterministic list list(range(-50, 50)).
"""

from smoke_digits import digit_product, is_palin_number, sum_of_squares_of_digits

RANGE_100 = list(range(-50, 50))


def test_digit_product_vectors():
    assert digit_product(0) == 0
    assert digit_product(7) == 7
    assert digit_product(123) == 6
    assert digit_product(105) == 0
    assert digit_product(-24) == 8


def test_digit_product_single_digits():
    for d in range(10):
        assert digit_product(d) == d
        assert digit_product(-d) == d


def test_digit_product_zeros_inside():
    assert digit_product(100) == 0
    assert digit_product(909) == 0
    assert digit_product(-101) == 0


def test_is_palin_number_vectors():
    assert is_palin_number(0) is True
    assert is_palin_number(7) is True
    assert is_palin_number(121) is True
    assert is_palin_number(12321) is True
    assert is_palin_number(123) is False
    assert is_palin_number(-121) is False


def test_is_palin_number_more_cases():
    assert is_palin_number(11) is True
    assert is_palin_number(1001) is True
    assert is_palin_number(10) is False
    assert is_palin_number(-7) is False
    assert is_palin_number(-1) is False


def test_sum_of_squares_of_digits_vectors():
    assert sum_of_squares_of_digits(0) == 0
    assert sum_of_squares_of_digits(10) == 1
    assert sum_of_squares_of_digits(123) == 14
    assert sum_of_squares_of_digits(-12) == 5
    assert sum_of_squares_of_digits(99) == 162


def test_digit_product_matches_abs_over_range():
    for n in RANGE_100:
        assert digit_product(n) == digit_product(abs(n))


def test_sum_of_squares_matches_string_reference_over_range():
    for n in RANGE_100:
        assert sum_of_squares_of_digits(n) == sum(int(c) ** 2 for c in str(abs(n)))


def test_is_palin_matches_string_reference_over_range():
    for n in RANGE_100:
        assert is_palin_number(n) == (str(n) == str(n)[::-1])
