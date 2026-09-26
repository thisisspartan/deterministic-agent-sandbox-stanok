"""Reference tests for src/smoke_util.py (TASK-STANOK-CC-163).

Covers the ticket contract:
- clamp(v, lo, hi): in-range unchanged, below lo -> lo, above hi -> hi,
  degenerate lo == hi -> that value.
- lerp(a, b, t): t=0 -> a, t=1 -> b, t=0.5 -> midpoint; t < 0 and t > 1
  are clamped to 0 and 1 respectively.
"""

from smoke_util import clamp, lerp


def test_clamp_in_range_unchanged():
    assert clamp(5, 0, 10) == 5
    assert clamp(-3, -10, -1) == -3
    assert clamp(2.5, 1.0, 3.0) == 2.5


def test_clamp_below_lo_returns_lo():
    assert clamp(-1, 0, 10) == 0
    assert clamp(-100, -5, 5) == -5
    assert clamp(0.5, 1.0, 2.0) == 1.0


def test_clamp_above_hi_returns_hi():
    assert clamp(11, 0, 10) == 10
    assert clamp(100, -5, 5) == 5
    assert clamp(2.5, 1.0, 2.0) == 2.0


def test_clamp_degenerate_lo_equals_hi():
    assert clamp(0, 7, 7) == 7
    assert clamp(100, 7, 7) == 7
    assert clamp(-100, 7, 7) == 7
    assert clamp(7, 7, 7) == 7


def test_lerp_t_zero_returns_a():
    assert lerp(10, 20, 0) == 10
    assert lerp(-5, 5, 0) == -5


def test_lerp_t_one_returns_b():
    assert lerp(10, 20, 1) == 20
    assert lerp(-5, 5, 1) == 5


def test_lerp_t_half_returns_midpoint():
    assert lerp(0, 10, 0.5) == 5
    assert lerp(10, 20, 0.5) == 15
    assert lerp(-10, 10, 0.5) == 0


def test_lerp_t_below_zero_clamped_to_zero():
    assert lerp(10, 20, -1) == 10
    assert lerp(10, 20, -0.5) == 10


def test_lerp_t_above_one_clamped_to_one():
    assert lerp(10, 20, 2) == 20
    assert lerp(10, 20, 1.5) == 20
