"""Reference tests for src/audit_probe2.py (TASK-STANOK-CC-177).

Covers the ticket contract for ``clamp(value, lo, hi)``:
- below-range: ``value < lo`` -> ``lo``;
- above-range: ``value > hi`` -> ``hi``;
- in-range: ``lo <= value <= hi`` -> ``value`` unchanged;
- exact boundaries: ``value == lo`` -> ``lo``, ``value == hi`` -> ``hi``;
- ``lo > hi`` -> ``ValueError``;
- ``int`` and ``float`` arguments.
"""

import pytest

from audit_probe2 import clamp


def test_below_range_returns_lo():
    assert clamp(1, 5, 10) == 5
    assert clamp(-3, 0, 10) == 0


def test_above_range_returns_hi():
    assert clamp(15, 5, 10) == 10
    assert clamp(100, 0, 10) == 10


def test_in_range_returns_value_unchanged():
    assert clamp(7, 5, 10) == 7
    assert clamp(5, 5, 10) == 5
    assert clamp(10, 5, 10) == 10


def test_boundary_value_equals_lo():
    assert clamp(5, 5, 10) == 5


def test_boundary_value_equals_hi():
    assert clamp(10, 5, 10) == 10


def test_float_arguments():
    assert clamp(1.5, 2.0, 3.0) == 2.0
    assert clamp(4.5, 2.0, 3.0) == 3.0
    assert clamp(2.5, 2.0, 3.0) == 2.5


def test_mixed_int_and_float_arguments():
    assert clamp(1, 0.5, 2.5) == 1
    assert clamp(0.25, 0.5, 2.5) == 0.5
    assert clamp(3, 0.5, 2.5) == 2.5
    assert clamp(1.5, 0, 3) == 1.5


def test_negative_bounds():
    assert clamp(-7, -5, -1) == -5
    assert clamp(0, -5, -1) == -1
    assert clamp(-3, -5, -1) == -3


def test_lo_greater_than_hi_raises_value_error():
    with pytest.raises(ValueError):
        clamp(5, 10, 5)


def test_lo_equal_hi_is_valid():
    assert clamp(5, 5, 5) == 5
    assert clamp(1, 5, 5) == 5
    assert clamp(9, 5, 5) == 5
