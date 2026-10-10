"""Acceptance tests for src/k8s_smoke.py (TASK-STANOK-CC-221)."""
from src.k8s_smoke import add


def test_positive_numbers():
    assert add(2, 3) == 5
    assert add(100, 200) == 300


def test_negative_numbers():
    assert add(-2, -3) == -5
    assert add(-7, 4) == -3
    assert add(7, -4) == 3


def test_zero_identity():
    assert add(0, 0) == 0
    assert add(0, 42) == 42
    assert add(42, 0) == 42
    assert add(0, -13) == -13
    assert add(-13, 0) == -13


def test_commutativity():
    for a, b in [(1, 2), (-5, 9), (0, 7), (-3, -8), (123456789, -987654321)]:
        assert add(a, b) == add(b, a)
