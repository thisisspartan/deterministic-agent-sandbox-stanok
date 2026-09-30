"""Reference tests for src/smoke_int.py (TASK-STANOK-CC-182).

Covers the ticket contract:
- digit_sum(n): sum of the decimal digits of n; defined for n >= 0 only;
  negative input raises ValueError (message mentions the value).
- is_perfect(n): True iff n > 0 and the sum of its proper divisors
  (divisors excluding n itself) equals n; total over all ints
  (n <= 0 is False, never raises).
- collatz_steps(n): number of Collatz steps to reach 1; defined for
  n >= 1 only; n < 1 raises ValueError (message mentions the value).
"""

import pytest

from smoke_int import collatz_steps, digit_sum, is_perfect


def test_digit_sum_zero():
    assert digit_sum(0) == 0


def test_digit_sum_single_digit():
    for d in range(10):
        assert digit_sum(d) == d


def test_digit_sum_multi_digit():
    assert digit_sum(123) == 6
    assert digit_sum(999) == 27
    assert digit_sum(1000000) == 1


def test_digit_sum_zeros_inside():
    assert digit_sum(101) == 2
    assert digit_sum(1002) == 3
    assert digit_sum(90909) == 27


def test_digit_sum_negative_raises_value_error():
    with pytest.raises(ValueError, match="-1"):
        digit_sum(-1)
    with pytest.raises(ValueError, match="-123"):
        digit_sum(-123)


def test_is_perfect_true_cases():
    assert is_perfect(6) is True
    assert is_perfect(28) is True
    assert is_perfect(496) is True


def test_is_perfect_false_cases():
    assert is_perfect(1) is False
    assert is_perfect(12) is False
    assert is_perfect(24) is False
    assert is_perfect(100) is False


def test_is_perfect_non_positive_is_false():
    assert is_perfect(0) is False
    assert is_perfect(-1) is False
    assert is_perfect(-28) is False


def test_is_perfect_large_value():
    # 10**6 is not perfect; the check must stay fast (trial division
    # up to sqrt(n)).
    assert is_perfect(10**6) is False


def test_collatz_steps_one_is_zero():
    assert collatz_steps(1) == 0


def test_collatz_steps_six_is_eight():
    # 6 -> 3 -> 10 -> 5 -> 16 -> 8 -> 4 -> 2 -> 1
    assert collatz_steps(6) == 8


def test_collatz_steps_seven_is_sixteen():
    assert collatz_steps(7) == 16


def test_collatz_steps_eight_is_three():
    # 8 -> 4 -> 2 -> 1
    assert collatz_steps(8) == 3


def test_collatz_steps_powers_of_two():
    for k in (1, 2, 3, 5, 10):
        assert collatz_steps(2**k) == k


def test_collatz_steps_below_one_raises_value_error():
    with pytest.raises(ValueError, match="0"):
        collatz_steps(0)
    with pytest.raises(ValueError, match="-5"):
        collatz_steps(-5)
