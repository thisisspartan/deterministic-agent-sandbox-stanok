"""Reference tests for src/fire/simulator.py (TASK-FIRE-02).

Contract:
- ``FireSimulation(width, height, decay_min=1, decay_max=4)`` holds a
  ``buffer`` of ``height`` rows x ``width`` columns of ints in ``[0..255]``,
  initialized to zeros. Row 0 is the top row, row ``height - 1`` the bottom
  (fuel) row.
- ``ignite_bottom(intensity_min=200, intensity_max=255)`` heats the bottom
  row with random high temperatures, allowing rare gaps (cold cells).
- ``step(wind=0)`` recomputes rows ``0..height-2`` from the row below: the
  new value of cell ``(x, y)`` comes from ``(x, y + 1)``, shifted
  horizontally by ``-wind + {-1, 0, 1}`` and decayed by
  ``randint(decay_min, decay_max)`` (clamped at 0). The bottom row is left
  untouched.
- No ``curses`` or ``sys.stdout`` dependency.
"""

import random

from fire.simulator import FireSimulation


def _mean(buffer):
    total = sum(sum(row) for row in buffer)
    cells = sum(len(row) for row in buffer)
    return total / cells


def test_initialization_is_zeros():
    sim = FireSimulation(width=16, height=12)
    assert len(sim.buffer) == 12
    for row in sim.buffer:
        assert len(row) == 16
        for value in row:
            assert value == 0


def test_ignite_bottom_heats_bottom_row():
    random.seed(42)
    sim = FireSimulation(width=20, height=10)
    sim.ignite_bottom()
    bottom = sim.buffer[-1]
    # At least one hot cell, and every cell is either a gap (0) or a
    # high temperature within the requested intensity range.
    assert sum(bottom) > 0
    for value in bottom:
        assert 0 <= value <= 255
        assert value == 0 or 200 <= value <= 255
    # Only the bottom row is heated by ignite_bottom.
    for y in range(sim.height - 1):
        assert sum(sim.buffer[y]) == 0


def test_step_cools_buffer_without_ignition():
    # A fully hot buffer cools down over 10 steps without any ignition.
    random.seed(7)
    sim = FireSimulation(width=20, height=20)
    for y in range(sim.height):
        for x in range(sim.width):
            sim.buffer[y][x] = 255
    before = _mean(sim.buffer)
    for _ in range(10):
        sim.step()
    after = _mean(sim.buffer)
    assert after < before
    for row in sim.buffer:
        for value in row:
            assert 0 <= value <= 255


def test_top_row_colder_than_bottom_row():
    random.seed(1)
    sim = FireSimulation(width=20, height=20)
    sim.ignite_bottom()
    for _ in range(10):
        sim.step()
    top = sum(sim.buffer[0]) / sim.width
    bottom = sum(sim.buffer[-1]) / sim.width
    assert top < bottom


def test_decay_reduces_heat_upward():
    random.seed(3)
    sim = FireSimulation(width=10, height=8, decay_min=1, decay_max=4)
    sim.ignite_bottom()
    sim.step()
    # Every cell one row up lost at least decay_min heat versus its source.
    assert max(sim.buffer[-2]) <= max(sim.buffer[-1]) - 1


def test_wind_shifts_heat():
    random.seed(5)
    sim = FireSimulation(width=20, height=6)
    for x in range(sim.width):
        sim.buffer[-1][x] = 255
    sim.step(wind=5)
    row = sim.buffer[-2]
    left = sum(row[:10])
    right = sum(row[10:])
    # Positive wind pushes the heat to the left.
    assert left > right


def test_no_wraparound_at_edges():
    random.seed(9)
    sim = FireSimulation(width=12, height=5)
    sim.buffer[-1][0] = 255  # single hot cell in the leftmost column
    sim.step()
    # Heat must not wrap around to the opposite (right) edge.
    assert sim.buffer[-2][-1] == 0


def test_small_grid_does_not_crash():
    random.seed(11)
    sim = FireSimulation(width=1, height=1)
    sim.ignite_bottom()
    sim.step()
    assert 0 <= sim.buffer[0][0] <= 255

    sim2 = FireSimulation(width=3, height=2)
    sim2.ignite_bottom()
    for _ in range(5):
        sim2.step(wind=-1)
    for row in sim2.buffer:
        for value in row:
            assert 0 <= value <= 255


def test_no_curses_or_stdout_dependency():
    import fire.simulator as module

    with open(module.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert "curses" not in source
    assert "sys.stdout" not in source
