"""Tests for src/smoke_neg.py — TASK-STANOK-CC-211.

Contract: add(a: int, b: int) -> int returns exactly a + b.
Covers the ticket vectors (2+3, 0+0) plus negative operands, identity,
commutativity, and larger magnitudes.
"""

from src import smoke_neg


def test_add_basic_vectors():
    assert smoke_neg.add(2, 3) == 5
    assert smoke_neg.add(0, 0) == 0


def test_add_negative_operands():
    assert smoke_neg.add(-1, -2) == -3
    assert smoke_neg.add(5, -3) == 2
    assert smoke_neg.add(-7, 4) == -3
    assert smoke_neg.add(-10, 10) == 0


def test_add_identity():
    assert smoke_neg.add(42, 0) == 42
    assert smoke_neg.add(0, -42) == -42


def test_add_is_commutative():
    assert smoke_neg.add(11, 31) == smoke_neg.add(31, 11) == 42


def test_add_large_magnitudes():
    assert smoke_neg.add(10**9, 10**9) == 2 * 10**9
    assert smoke_neg.add(-(10**9), -(10**9)) == -2 * 10**9
