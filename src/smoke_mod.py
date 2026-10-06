"""Modular arithmetic utilities.

Three pure functions, no imports, no I/O, no state, no randomness:

- ``mod_pow(base, exp, m)`` — ``base ** exp mod m`` via fast (binary)
  exponentiation; ``m == 1`` -> 0; ``exp == 0`` -> ``1 % m``;
  ``exp >= 0`` always in this contract.
- ``mod_inverse(a, m)`` — modular inverse of ``a`` mod ``m`` (result in
  ``0..m-1``) via the extended Euclidean algorithm; ``None`` when
  ``gcd(a, m) != 1``.
- ``is_prime(n)`` — deterministic primality by trial division;
  ``n < 2`` -> False.
"""


def mod_pow(base: int, exp: int, m: int) -> int:
    """Return ``base ** exp mod m`` via fast (binary) exponentiation.

    ``m == 1`` -> 0 (everything is 0 mod 1); ``exp == 0`` -> ``1 % m``.
    ``exp >= 0`` always in this contract. Runs in O(log exp)
    multiplications, so large exponents are cheap.
    ``mod_pow(2, 10, 1000) == 24``, ``mod_pow(3, 0, 7) == 1``,
    ``mod_pow(5, 3, 5) == 0``, ``mod_pow(2, 200, 1000) == 376``,
    ``mod_pow(7, 1, 3) == 1``, ``mod_pow(10, 5, 1) == 0``.
    """
    if m == 1:
        return 0
    result = 1 % m
    base %= m
    while exp > 0:
        if exp & 1:
            result = (result * base) % m
        base = (base * base) % m
        exp >>= 1
    return result


def mod_inverse(a: int, m: int) -> int | None:
    """Return the modular inverse of ``a`` mod ``m``, in ``0..m-1``.

    Computed with the extended Euclidean algorithm: finds ``x`` with
    ``a * x == 1 (mod m)``. Returns ``None`` when ``gcd(a, m) != 1``
    (no inverse exists).
    ``mod_inverse(3, 7) == 5``, ``mod_inverse(10, 17) == 12``,
    ``mod_inverse(1, 7) == 1``, ``mod_inverse(2, 4) is None``,
    ``mod_inverse(0, 7) is None``.
    """
    # Extended Euclid: track the coefficient of a in the remainder.
    old_r, r = a, m
    old_s, s = 1, 0
    while r != 0:
        q = old_r // r
        old_r, r = r, old_r - q * r
        old_s, s = s, old_s - q * s
    if old_r != 1:
        return None
    return old_s % m


def is_prime(n: int) -> bool:
    """Return ``True`` iff ``n`` is prime (deterministic trial division).

    ``n < 2`` -> False. Divides by 2, then by odd candidates up to
    ``sqrt(n)`` — fast enough for ``n`` up to ~10**6.
    ``is_prime(2) is True``, ``is_prime(4) is False``,
    ``is_prime(97) is True``, ``is_prime(7919) is True``,
    ``is_prime(1000003) is True``.
    """
    if n < 2:
        return False
    if n < 4:
        return True  # 2 and 3
    if n % 2 == 0:
        return False
    i = 3
    while i * i <= n:
        if n % i == 0:
            return False
        i += 2
    return True
