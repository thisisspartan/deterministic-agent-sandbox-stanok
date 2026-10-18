"""CC-287 — reference tests for src/fire_engine.py.

Covers the ticket contract: determinism, instance and snapshot
independence, heat bounds, bottom-row fuel, grid movement, grid shape,
and constructor validation. No TTY, no subprocesses.
"""
import pytest

import fire_engine


def zero_grid(width, height):
    return [[0] * width for _ in range(height)]


def run(engine, steps):
    for _ in range(steps):
        engine.step()
    return engine.grid


# ---------------------------------------------------------------- 1. determinism

def test_same_seed_same_grid():
    a = fire_engine.FireEngine(1, 12, 8)
    b = fire_engine.FireEngine(1, 12, 8)
    assert run(a, 10) == run(b, 10)


def test_arbitrary_seed_accepted():
    # seed is an arbitrary int — negative seeds must work too.
    a = fire_engine.FireEngine(-42, 6, 4)
    b = fire_engine.FireEngine(-42, 6, 4)
    assert run(a, 3) == run(b, 3)


def test_different_seed_different_state():
    a = fire_engine.FireEngine(1, 12, 8)
    b = fire_engine.FireEngine(2, 12, 8)
    ga, gb = run(a, 3), run(b, 3)
    assert ga != gb
    assert ga[-1] != gb[-1]  # at minimum the bottom (fuel) row differs


# ---------------------------------------------------------------- 2. instance independence

def test_instances_are_independent():
    a = fire_engine.FireEngine(1, 12, 8)
    b = fire_engine.FireEngine(1, 12, 8)
    for _ in range(5):
        a.step()
        b.step()
    ga, gb = a.grid, b.grid
    assert ga == gb
    for _ in range(3):
        a.step()
    assert b.grid == gb  # stepping A never touches B
    for ra, rb in zip(ga, gb):
        assert ra is not rb  # rows of two engines' snapshots are distinct objects


# ---------------------------------------------------------------- 3. snapshot independence

def test_snapshot_is_a_deep_copy():
    e = fire_engine.FireEngine(7, 10, 6)
    e.step()
    g1 = e.grid
    g1[0][0] = 999  # mutating a snapshot must not touch the engine
    g2 = e.grid  # second snapshot, no new step
    assert g2[0][0] != 999
    assert g1[0][0] == 999  # the mutated snapshot keeps its own value
    e.step()
    g3 = e.grid
    assert g3[0][0] != 999  # 999 is outside the legal heat range [0, 255]
    for r1, r2 in zip(g1, g2):
        assert r1 is not r2  # two snapshots of one engine share no rows


# ---------------------------------------------------------------- 4. heat bounds

def test_heat_bounds_after_20_steps():
    e = fire_engine.FireEngine(3, 16, 10)
    for _ in range(20):
        e.step()
        for row in e.grid:
            for v in row:
                assert 0 <= v <= 255


# ---------------------------------------------------------------- 5. fuel: bottom row

def test_bottom_row_is_fuel_every_step():
    e = fire_engine.FireEngine(5, 12, 8)
    for _ in range(5):
        e.step()
        for v in e.grid[-1]:
            assert 180 <= v <= 255


# ---------------------------------------------------------------- 6. the grid moves

def test_grid_empty_initially_and_moves_after_first_step():
    e = fire_engine.FireEngine(1, 12, 8)
    assert e.grid == zero_grid(12, 8)  # initial state: all zeros
    e.step()
    assert e.grid != zero_grid(12, 8)


def test_grid_shape():
    e = fire_engine.FireEngine(1, 2, 2)  # minimal legal size
    g = run(e, 2)
    assert len(g) == 2 and all(len(row) == 2 for row in g)
    for row in g:
        for v in row:
            assert isinstance(v, int)


# ---------------------------------------------------------------- 7. validation

@pytest.mark.parametrize("width,height", [
    (1, 8), (12, 1), (1, 1), (0, 8), (8, 0), (0, 0), (-3, 5), (5, -3),
])
def test_constructor_rejects_degenerate_sizes(width, height):
    with pytest.raises(ValueError):
        fire_engine.FireEngine(1, width, height)
