"""CC-262: doomfire core model — pure math, no I/O.

Fixtures live inside this file (no conftest.py). The RNG call order
(top->bottom, left->right, off before decay, bottom row last) is part of
the contract and is exercised by the determinism tests.
"""

import random
from pathlib import Path

from src.doomfire_core import (
    create_field,
    seed_bottom,
    step,
    simulate,
)

MODULE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "doomfire_core.py"


def _rows(field):
    return len(field)


def _cols(row):
    return len(row)


# 1. Determinism


def test_simulate_is_deterministic_for_same_seed():
    a = simulate(8, 4, 10, 42)
    b = simulate(8, 4, 10, 42)
    assert a == b


def test_simulate_differs_for_different_seed():
    a = simulate(8, 4, 10, 42)
    b = simulate(8, 4, 10, 43)
    assert a != b


def test_step_sequence_matches_rng_call_order():
    # Reproduce the contract order by hand with an independent rng:
    # rows top->bottom, x left->right, off before decay, seed_bottom last.
    width, height = 5, 3
    rng_a = random.Random(7)
    rng_b = random.Random(7)
    field = create_field(width, height)
    seed_bottom(field, rng_a)
    expected = [row[:] for row in field]
    for y in range(height - 1):
        for x in range(width):
            off = rng_b.choice([-1, 0, 1])
            decay = rng_b.randint(1, 3)
            src_x = min(max(x + off, 0), width - 1)
            expected[y][x] = max(0, field[y + 1][src_x] - decay)
    for x in range(width):
        expected[height - 1][x] = rng_b.randint(128, 255)
    # rng_c starts from the same state as rng_b did before the manual
    # loop, so it consumes the identical sequence in the contract order.
    rng_c = random.Random(7)
    got = step(field, rng_c)
    assert got == expected


# 2. Range


def test_all_cells_stay_in_range():
    field = simulate(12, 6, 20, 1234)
    for row in field:
        for cell in row:
            assert 0 <= cell <= 255, f"cell out of range: {cell}"


# 3. Source row


def test_bottom_row_is_seeded_after_step():
    rng = random.Random(99)
    field = create_field(6, 4)
    for _ in range(5):
        field = step(field, rng)
        for cell in field[-1]:
            assert 128 <= cell <= 255, f"source cell out of range: {cell}"


def test_seed_bottom_sets_source_values():
    rng = random.Random(5)
    field = create_field(4, 2)
    seed_bottom(field, rng)
    assert _rows(field) == 2
    for cell in field[-1]:
        assert 128 <= cell <= 255
    assert all(c == 0 for c in field[0])


# 4. Decay invariant


def test_decay_invariant_against_pre_step_field():
    rng = random.Random(2024)
    field = simulate(10, 5, 3, 2024)
    for _ in range(5):
        old = [row[:] for row in field]
        field = step(field, rng)
        for y in range(_rows(old) - 1):
            assert max(field[y]) <= max(old[y + 1]), (
                f"row {y}: max {max(field[y])} exceeds source max "
                f"{max(old[y + 1])}"
            )


# 5. create_field validation and degenerate sizes


def test_create_field_rejects_nonpositive_dimensions():
    for w, h in [(0, 3), (3, 0), (-1, 3), (3, -1), (0, 0)]:
        try:
            create_field(w, h)
        except ValueError:
            pass
        else:
            raise AssertionError(f"create_field({w}, {h}) did not raise ValueError")


def test_create_field_shape():
    field = create_field(3, 4)
    assert _rows(field) == 4 and all(_cols(row) == 3 for row in field)
    assert all(cell == 0 for row in field for cell in row)


def test_single_cell_field_works():
    rng = random.Random(1)
    field = create_field(1, 1)
    field = step(field, rng)
    assert _rows(field) == 1 and _cols(field) == 1
    assert 128 <= field[0][0] <= 255


def test_single_column_field_works():
    # W=1: off clamps to 0.
    rng = random.Random(3)
    field = simulate(1, 4, 5, 3)
    assert _rows(field) == 4 and all(_cols(row) == 1 for row in field)
    for row in field:
        assert 0 <= row[0] <= 255


def test_single_row_field_only_reseeds():
    # H=1: step only reseeds the bottom (== only) row.
    rng = random.Random(4)
    field = create_field(5, 1)
    field = step(field, rng)
    assert _rows(field) == 1
    for cell in field[0]:
        assert 128 <= cell <= 255


def test_simulate_zero_steps_returns_seeded_field():
    rng = random.Random(11)
    expected = create_field(4, 3)
    seed_bottom(expected, rng)
    assert simulate(4, 3, 0, 11) == expected


# 6. step does not mutate its input


def test_step_does_not_mutate_input():
    rng = random.Random(17)
    field = simulate(6, 4, 2, 17)
    snapshot = [row[:] for row in field]
    new = step(field, rng)
    assert field == snapshot, "step mutated its input field"
    assert new is not field
    assert all(new[y] is not field[y] for y in range(_rows(field)))


# 7. Purity: module source has no I/O imports or print


def test_module_is_pure():
    src = MODULE_SOURCE.read_text(encoding="utf-8")
    for needle in ("import sys", "import os", "import time", "print("):
        assert needle not in src, f"impure construct in module source: {needle!r}"
