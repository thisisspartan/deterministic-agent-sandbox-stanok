"""Reference tests for src/smoke_seq.py (TASK-STANOK-CC-181).

Covers the ticket contract:
- fib(n): fib(0) == 0, fib(1) == 1, known values up to n=10, a larger
  value (fib(50)), negative n raises ValueError.
- is_monotonic(xs): strictly increasing, equal neighbours allowed,
  decreasing pair -> False, empty list, single element, unsorted.
- run_length_encode(xs): the ticket example, all-distinct input,
  all-equal input, empty input.
- none of the three functions mutates the input list.
"""

import pytest

from smoke_seq import fib, is_monotonic, run_length_encode


def test_fib_zero():
    assert fib(0) == 0


def test_fib_one():
    assert fib(1) == 1


def test_fib_known_values_up_to_ten():
    expected = [0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]
    for n, want in enumerate(expected):
        assert fib(n) == want


def test_fib_ten_is_fifty_five():
    assert fib(10) == 55


def test_fib_fifty():
    assert fib(50) == 12586269025


def test_fib_negative_raises_value_error():
    with pytest.raises(ValueError):
        fib(-1)
    with pytest.raises(ValueError):
        fib(-100)


def test_is_monotonic_strictly_increasing():
    assert is_monotonic([1, 2, 3, 4, 5]) is True


def test_is_monotonic_equal_neighbours_allowed():
    assert is_monotonic([1, 1, 2, 3]) is True
    assert is_monotonic([2, 2, 2]) is True


def test_is_monotonic_decreasing_pair_is_false():
    assert is_monotonic([3, 1, 2]) is False
    assert is_monotonic([5, 4]) is False


def test_is_monotonic_empty_list():
    assert is_monotonic([]) is True


def test_is_monotonic_single_element():
    assert is_monotonic([42]) is True


def test_is_monotonic_unsorted():
    assert is_monotonic([3, 1, 2]) is False
    assert is_monotonic([1, 3, 2, 4]) is False


def test_run_length_encode_ticket_example():
    assert run_length_encode([1, 1, 2, 3, 3, 3]) == [[1, 2], [2, 1], [3, 3]]


def test_run_length_encode_all_distinct():
    assert run_length_encode([1, 2, 3]) == [[1, 1], [2, 1], [3, 1]]


def test_run_length_encode_all_equal():
    assert run_length_encode([7, 7, 7, 7]) == [[7, 4]]


def test_run_length_encode_empty_input():
    assert run_length_encode([]) == []


def test_input_not_mutated_by_fib():
    # fib takes an int; the no-mutation contract applies to the list
    # functions, but fib must not require or touch any list state.
    assert fib(5) == 5


def test_input_not_mutated_by_is_monotonic():
    xs = [3, 1, 2]
    is_monotonic(xs)
    assert xs == [3, 1, 2]


def test_input_not_mutated_by_run_length_encode():
    xs = [1, 1, 2, 3, 3, 3]
    run_length_encode(xs)
    assert xs == [1, 1, 2, 3, 3, 3]
