"""Reference tests for src/smoke_stats.py (TASK-STANOK-CC-180).

Covers the ticket contract:
- mean(xs): arithmetic mean; int lists, float lists, single element,
  negative values.
- median(xs): median of the sorted input; odd count, even count (mean of
  the two middle values), unsorted input, duplicates, single element.
- variance(xs): population variance sum((x - mean)^2) / n; known value
  1.25 for [1, 2, 3, 4], constant list -> 0.0, single element -> 0.0,
  float values.
- none of the three functions mutates the input list.
"""

from smoke_stats import mean, median, variance


def test_mean_int_list():
    assert mean([1, 2, 3, 4]) == 2.5


def test_mean_float_list():
    assert mean([0.5, 1.5, 2.5]) == 1.5


def test_mean_single_element():
    assert mean([7]) == 7.0


def test_mean_negative_values():
    assert mean([-1, -2, -3]) == -2.0
    assert mean([-4, 4]) == 0.0


def test_median_odd_count():
    assert median([3, 1, 2]) == 2.0


def test_median_even_count():
    assert median([4, 1, 3, 2]) == 2.5


def test_median_unsorted_input():
    assert median([9, -5, 0, 7, 3]) == 3.0


def test_median_duplicates():
    assert median([2, 2, 2, 2]) == 2.0
    assert median([1, 1, 2, 3]) == 1.5


def test_median_single_element():
    assert median([42]) == 42.0


def test_variance_known_value():
    assert variance([1, 2, 3, 4]) == 1.25


def test_variance_constant_list_is_zero():
    assert variance([5, 5, 5, 5]) == 0.0


def test_variance_single_element_is_zero():
    assert variance([3]) == 0.0


def test_variance_float_values():
    assert variance([1.5, 2.5, 3.5]) == 0.6666666666666666


def test_input_not_mutated_by_mean():
    xs = [3, 1, 2]
    mean(xs)
    assert xs == [3, 1, 2]


def test_input_not_mutated_by_median():
    xs = [4, 1, 3, 2]
    median(xs)
    assert xs == [4, 1, 3, 2]


def test_input_not_mutated_by_variance():
    xs = [1, 2, 3, 4]
    variance(xs)
    assert xs == [1, 2, 3, 4]
