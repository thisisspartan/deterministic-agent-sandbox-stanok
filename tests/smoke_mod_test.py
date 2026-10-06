"""Reference tests for src/smoke_mod.py (TASK-STANOK-CC-200).

Covers the ticket contract:
- mod_pow(base, exp, m): base ** exp mod m via fast (binary)
  exponentiation; m == 1 -> 0; exp == 0 -> 1 % m; exp >= 0.
- mod_inverse(a, m): modular inverse of a mod m (result in 0..m-1)
  via extended Euclidean algorithm; None when gcd(a, m) != 1.
- is_prime(n): deterministic primality by trial division; n < 2 -> False.

Plus the acceptance cross-checks:
- 20 deterministic triples (seeded random.Random(3)): mod_pow equals
  the builtin pow(base, exp, m).
- every n in range(2000): is_prime(n) equals a reference trial division.
- 20 deterministic pairs (seeded random.Random(3)): when mod_inverse
  is not None, a * inv % m == 1; when it is None, math.gcd(a, m) != 1.
"""

import math
import random

from smoke_mod import is_prime, mod_inverse, mod_pow


# --- deterministic data (seeded, no live randomness) -------------------


def _seeded(draw, count):
    r = random.Random(3)
    return tuple(draw(r) for _ in range(count))


_POW_TRIPLES = _seeded(
    lambda r: (r.randint(0, 10**6), r.randint(0, 10**6), r.randint(1, 10**6)),
    20,
)

_INV_PAIRS = _seeded(lambda r: (r.randint(0, 10**6), r.randint(2, 10**6)), 20)


def _ref_is_prime(n):
    """Reference trial division over all divisors from 2 up to sqrt(n)."""
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


# --- mod_pow -------------------------------------------------------------


def test_mod_pow_ticket_vectors():
    assert mod_pow(2, 10, 1000) == 24
    assert mod_pow(3, 0, 7) == 1
    assert mod_pow(5, 3, 5) == 0
    assert mod_pow(2, 200, 1000) == 376
    assert mod_pow(7, 1, 3) == 1
    assert mod_pow(10, 5, 1) == 0


def test_mod_pow_m_one_is_zero():
    assert mod_pow(10, 5, 1) == 0
    assert mod_pow(0, 0, 1) == 0
    assert mod_pow(12345, 99, 1) == 0


def test_mod_pow_exp_zero_is_one_mod_m():
    assert mod_pow(0, 0, 7) == 1
    assert mod_pow(12345, 0, 13) == 1
    assert mod_pow(1, 0, 2) == 1


def test_mod_pow_matches_builtin_pow_seeded():
    for base, exp, m in _POW_TRIPLES:
        assert mod_pow(base, exp, m) == pow(base, exp, m), (base, exp, m)


def test_mod_pow_large_exponent_is_fast():
    # 2**100000 mod 1000000007 — fast exponentiation handles this instantly.
    assert mod_pow(2, 100000, 1000000007) == pow(2, 100000, 1000000007)


# --- mod_inverse ----------------------------------------------------------


def test_mod_inverse_ticket_vectors():
    assert mod_inverse(3, 7) == 5
    assert mod_inverse(10, 17) == 12
    assert mod_inverse(1, 7) == 1
    assert mod_inverse(2, 4) is None
    assert mod_inverse(0, 7) is None


def test_mod_inverse_result_in_range():
    for a, m in _INV_PAIRS:
        inv = mod_inverse(a, m)
        if inv is not None:
            assert 0 <= inv < m
            assert a * inv % m == 1
        else:
            assert math.gcd(a, m) != 1


def test_mod_inverse_none_iff_not_coprime():
    # Exhaustive small check: None exactly when gcd(a, m) != 1.
    for m in range(2, 30):
        for a in range(0, m):
            inv = mod_inverse(a, m)
            if math.gcd(a, m) == 1:
                assert inv is not None
                assert a * inv % m == 1
            else:
                assert inv is None


# --- is_prime -------------------------------------------------------------


def test_is_prime_ticket_vectors():
    assert is_prime(0) is False
    assert is_prime(1) is False
    assert is_prime(2) is True
    assert is_prime(3) is True
    assert is_prime(4) is False
    assert is_prime(97) is True
    assert is_prime(100) is False
    assert is_prime(7919) is True
    assert is_prime(1000003) is True


def test_is_prime_matches_reference_range_2000():
    for n in range(2000):
        assert is_prime(n) is _ref_is_prime(n), n


def test_is_prime_small_values():
    expected = {
        2: True, 3: True, 5: True, 7: True,
        4: False, 6: False, 8: False, 9: False, 10: False,
        25: False, 49: False, 121: False, 169: False,
    }
    for n, want in expected.items():
        assert is_prime(n) is want, n
