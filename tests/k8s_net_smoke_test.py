"""Acceptance tests for src/k8s_net_smoke.py (TASK-STANOK-CC-227)."""
from src.k8s_net_smoke import mul


def test_positive_numbers():
    assert mul(2, 3) == 6
    assert mul(100, 200) == 20000
    assert mul(7, 1) == 7


def test_negative_times_positive_sign():
    assert mul(-2, 3) == -6
    assert mul(3, -2) == -6
    assert mul(-2, -3) == 6


def test_zero_identity():
    assert mul(0, 0) == 0
    assert mul(0, 42) == 0
    assert mul(42, 0) == 0
    assert mul(0, -13) == 0
    assert mul(-13, 0) == 0


def test_identity_with_one():
    assert mul(1, 7) == 7
    assert mul(7, 1) == 7
    assert mul(1, -7) == -7
    assert mul(-7, 1) == -7
    assert mul(1, 0) == 0
    assert mul(1, 1) == 1


def test_commutativity():
    for a, b in [(1, 2), (-5, 9), (0, 7), (-3, -8), (123456789, -987654321)]:
        assert mul(a, b) == mul(b, a)
