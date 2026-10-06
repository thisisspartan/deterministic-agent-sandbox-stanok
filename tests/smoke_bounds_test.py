"""Reference tests for src/smoke_bounds.py (TASK-STANOK-CC-193).

Covers the ticket contract:
- min_max(nums): (min, max) of the list; (None, None) for an empty list.
- span(nums): max - min; None for an empty list.
- within(value, lo, hi): inclusive bounds lo <= value <= hi.
- Cross-checks against the builtin references on a fixed deterministic
  list of 200 integers and a fixed grid of (value, lo, hi) triples.
"""

import random

from smoke_bounds import min_max, span, within


# --- min_max: ticket vectors -------------------------------------------------

def test_min_max_empty():
    assert min_max([]) == (None, None)


def test_min_max_single_element():
    assert min_max([5]) == (5, 5)


def test_min_max_unsorted():
    assert min_max([3, 1, 2]) == (1, 3)


def test_min_max_negative_values():
    assert min_max([-4, 7, -4]) == (-4, 7)


# --- span: ticket vectors ----------------------------------------------------

def test_span_empty():
    assert span([]) is None


def test_span_single_element():
    assert span([5]) == 0


def test_span_unsorted():
    assert span([3, 1, 2]) == 2


def test_span_negative_values():
    assert span([-4, 7]) == 11


# --- within: ticket vectors --------------------------------------------------

def test_within_inside():
    assert within(5, 1, 10) is True


def test_within_below_lo():
    assert within(0, 1, 10) is False


def test_within_above_hi():
    assert within(11, 1, 10) is False


def test_within_at_lo():
    assert within(1, 1, 10) is True


def test_within_at_hi():
    assert within(10, 1, 10) is True


# --- deterministic cross-checks against builtin references -------------------

def _fixed_list():
    """A fixed deterministic list of 200 integers: a seeded permutation of
    range(200) plus a few negatives."""
    rng = random.Random(7)
    nums = list(range(200))
    rng.shuffle(nums)
    return nums + [-3, -17, -100, 0, 199]


def test_min_max_matches_builtins_on_fixed_list():
    nums = _fixed_list()
    assert min_max(nums) == (min(nums), max(nums))


def test_span_matches_builtins_on_fixed_list():
    nums = _fixed_list()
    assert span(nums) == max(nums) - min(nums)


def test_within_matches_builtin_expression_on_grid():
    # Fixed grid of (value, lo, hi) triples: values -5..5 against a set of
    # inclusive bounds, including lo == hi and negative bounds.
    bounds = [(1, 10), (-5, 5), (0, 0), (-10, -1), (2, 2), (-3, 7)]
    for value in range(-5, 6):
        for lo, hi in bounds:
            assert within(value, lo, hi) == (lo <= value <= hi)
