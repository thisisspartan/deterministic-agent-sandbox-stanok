"""Reference tests for src/smoke_math.py (TASK-STANOK-CC-165).

Covers the ticket contract:
- gcd(a, b): iterative Euclidean algorithm; gcd(0, 0) == 0; negative
  arguments are reduced to their absolute value.
- is_prime(n): n < 2 -> False; trial division by every integer up to
  sqrt(n) inclusive.
"""

from smoke_math import gcd, is_prime


def test_gcd_basic_pairs():
    assert gcd(12, 18) == 6
    assert gcd(7, 13) == 1


def test_gcd_with_zero():
    assert gcd(0, 5) == 5
    assert gcd(5, 0) == 5
    assert gcd(0, 0) == 0


def test_gcd_negative_arguments_reduced_to_abs():
    assert gcd(-12, 18) == 6
    assert gcd(12, -18) == 6
    assert gcd(-12, -18) == 6


def test_is_prime_below_two_is_false():
    assert is_prime(0) is False
    assert is_prime(1) is False


def test_is_prime_small_primes():
    assert is_prime(2) is True
    assert is_prime(3) is True


def test_is_prime_composites():
    assert is_prime(4) is False
    assert is_prime(100) is False


def test_is_prime_larger_values():
    assert is_prime(97) is True
    assert is_prime(7919) is True
