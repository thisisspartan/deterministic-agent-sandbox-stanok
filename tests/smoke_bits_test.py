"""Reference tests for src/smoke_bits.py (TASK-STANOK-CC-175).

Covers the ticket contract:
- popcount(n): number of 1-bits in n; defined for n >= 0 only;
  negative input raises ValueError (message mentions the value).
- is_power_of_two(n): True iff n == 2**k for some k >= 0; total over
  all ints (negatives and zero are False, never raise).
- parity(n): True iff popcount(n) is odd; defined for n >= 0 only;
  negative input raises ValueError (message mentions the value).
"""

import pytest

from smoke_bits import is_power_of_two, parity, popcount


def test_popcount_zero_and_one():
    assert popcount(0) == 0
    assert popcount(1) == 1


def test_popcount_small_values():
    assert popcount(7) == 3
    assert popcount(255) == 8


def test_popcount_large_value():
    assert popcount(2**64 - 1) == 64


def test_popcount_powers_of_two_are_one():
    for k in (0, 1, 3, 10, 32, 64):
        assert popcount(2**k) == 1


def test_popcount_negative_raises_value_error():
    with pytest.raises(ValueError, match="-1"):
        popcount(-1)
    with pytest.raises(ValueError, match="-16"):
        popcount(-16)


def test_is_power_of_two_true_cases():
    assert is_power_of_two(1) is True
    assert is_power_of_two(2) is True
    assert is_power_of_two(4) is True
    assert is_power_of_two(1024) is True
    assert is_power_of_two(2**32) is True


def test_is_power_of_two_false_cases():
    assert is_power_of_two(0) is False
    assert is_power_of_two(3) is False
    assert is_power_of_two(5) is False


def test_is_power_of_two_negative_is_false():
    assert is_power_of_two(-1) is False
    assert is_power_of_two(-16) is False


def test_parity_small_values():
    assert parity(0) is False
    assert parity(1) is True
    assert parity(2) is True
    assert parity(3) is False
    assert parity(7) is True
    assert parity(8) is True


def test_parity_255():
    assert parity(255) is False


def test_parity_negative_raises_value_error():
    with pytest.raises(ValueError, match="-1"):
        parity(-1)
    with pytest.raises(ValueError, match="-16"):
        parity(-16)
