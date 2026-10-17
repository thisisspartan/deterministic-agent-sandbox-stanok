"""Reference tests for src/fire_sim.py — ticket TASK-STANOK-CC-274.

Stage 1 of the console-fire pipeline: pure, seeded simulation + palette.
These tests are the contract: purity, bounds, decay, determinism.
Self-contained — fixtures defined here, no conftest.
"""

import copy
import random

import pytest

import fire_sim


def _row_mean(row):
    return sum(row) / len(row)


# --- constants ---------------------------------------------------------------


def test_constants_exact():
    assert fire_sim.DEFAULT_SEED == 1
    assert fire_sim.IGNITION_LOW == 0.85
    assert fire_sim.COOL_LOW == 0.02
    assert fire_sim.COOL_HIGH == 0.18
    assert fire_sim.EMPTY_THRESHOLD == 0.05


# --- new_field ---------------------------------------------------------------


def test_new_field_shape_and_bounds():
    width, height = 7, 4
    field = fire_sim.new_field(width, height)
    assert len(field) == height
    assert all(len(row) == width for row in field)
    assert all(0.0 <= v <= 1.0 for row in field for v in row)


def test_new_field_rejects_degenerate_dimensions():
    with pytest.raises(ValueError):
        fire_sim.new_field(0, 3)
    with pytest.raises(ValueError):
        fire_sim.new_field(3, 0)
    with pytest.raises(ValueError):
        fire_sim.new_field(0, 0)


# --- advance -----------------------------------------------------------------


def test_advance_is_pure_and_preserves_shape():
    field = fire_sim.simulate(1, 9, 5, 3)[-1]
    original = copy.deepcopy(field)
    result = fire_sim.advance(field, random.Random(99))
    assert field == original, "advance must not mutate its input"
    assert result is not field
    assert len(result) == len(field)
    assert all(len(new) == len(old) for new, old in zip(result, field))


def test_advance_single_row_field_is_all_ignition():
    field = fire_sim.new_field(4, 1)
    result = fire_sim.advance(field, random.Random(5))
    assert all(v >= fire_sim.IGNITION_LOW for v in result[0])


def test_bounds_after_50_advances():
    fields = fire_sim.simulate(1, 12, 8, 50)
    assert len(fields) == 50
    for field in fields:
        assert all(0.0 <= v <= 1.0 for row in field for v in row)
        assert all(v >= fire_sim.IGNITION_LOW for v in field[-1])


def test_heat_decays_with_height():
    fields = fire_sim.simulate(7, 12, 8, 30)
    field = fields[-1]
    assert _row_mean(field[0]) < _row_mean(field[-1])


# --- simulate ----------------------------------------------------------------


def test_simulate_determinism_same_seed():
    a = fire_sim.simulate(42, 10, 6, 5)
    b = fire_sim.simulate(42, 10, 6, 5)
    assert a == b


def test_simulate_differs_across_seeds():
    a = fire_sim.simulate(42, 10, 6, 5)
    c = fire_sim.simulate(43, 10, 6, 5)
    assert a != c


def test_simulate_count_and_shape():
    fields = fire_sim.simulate(3, 4, 3, 2)
    assert len(fields) == 2
    for field in fields:
        assert len(field) == 3 and all(len(row) == 4 for row in field)


def test_simulate_rejects_bad_n():
    with pytest.raises(ValueError):
        fire_sim.simulate(1, 4, 4, 0)


# --- heat_to_rgb ---------------------------------------------------------------


def test_heat_to_rgb_empty_below_threshold():
    assert fire_sim.heat_to_rgb(0.0, random.Random(1)) is None
    assert fire_sim.heat_to_rgb(fire_sim.EMPTY_THRESHOLD - 1e-9, random.Random(1)) is None


def test_heat_to_rgb_at_threshold_is_colored():
    assert fire_sim.heat_to_rgb(fire_sim.EMPTY_THRESHOLD, random.Random(1)) is not None


def test_heat_to_rgb_full_heat_is_valid_rgb():
    rgb = fire_sim.heat_to_rgb(1.0, random.Random(1))
    assert isinstance(rgb, tuple) and len(rgb) == 3
    assert all(isinstance(ch, int) and 0 <= ch <= 255 for ch in rgb)


def test_heat_to_rgb_gradient_dark_red_to_near_white():
    low = fire_sim.heat_to_rgb(0.06, random.Random(11))
    high = fire_sim.heat_to_rgb(1.0, random.Random(11))
    assert low[0] < 150 and low[1] < 100 and low[2] < 60  # dark-red end
    assert high[0] >= 180 and high[1] >= 180 and high[2] >= 180  # near-white end


def test_heat_to_rgb_brightness_increases_with_heat():
    hot = fire_sim.heat_to_rgb(0.9, random.Random(7))
    cold = fire_sim.heat_to_rgb(0.2, random.Random(7))
    assert sum(hot) > sum(cold)


def test_heat_to_rgb_rejects_out_of_range():
    with pytest.raises(ValueError):
        fire_sim.heat_to_rgb(1.5, random.Random(1))
    with pytest.raises(ValueError):
        fire_sim.heat_to_rgb(-0.1, random.Random(1))


def test_palette_determinism_same_heat_same_rng_state():
    a = fire_sim.heat_to_rgb(0.63, random.Random(7))
    b = fire_sim.heat_to_rgb(0.63, random.Random(7))
    assert a == b
