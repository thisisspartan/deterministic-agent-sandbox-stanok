"""TASK-STANOK-CC-273: purity of the simulation / palette / renderer API.

Characterization tests: they pin the CURRENT, verified behaviour promised by
the docs — `advance` "returns a NEW field (the input is never mutated)",
`new_field` returns independent rows, `heat_to_rgb` without an rng is an exact
mapping, `render_frame` is pure. Expected to PASS against the current
implementation; a failure here is a finding about src/fire.py, not about the
assertions.

API level only (`import fire`; src is on sys.path via the runner's
`-o pythonpath=src`) — no CLI, no subprocess.
"""

import random

import fire


def _copy(field):
    """A deep copy of a heat field: a new outer list, a new list per row."""
    return [[cell for cell in row] for row in field]


def _shared(*groups):
    """Every object appearing in more than ONE group, by identity.

    Two groups are compared across each other only: an item is never
    "shared" with itself inside its own group.
    """
    owner = {}  # id(item) -> index of the group that first held it
    shared = []
    for index, group in enumerate(groups):
        for item in group:
            first = owner.get(id(item))
            if first is None:
                owner[id(item)] = index
            elif first != index:
                shared.append(item)
    return shared


def _distinct(group):
    """True when no two elements of the same list are the same object."""
    return len({id(item) for item in group}) == len(group)


# --- 1. new_field: independent rows ----------------------------------------


def test_new_field_rows_are_independent():
    """Mutating one cell must not leak into the same column of another row
    (the aliasing bug `[[0.0] * width] * height` would produce)."""
    field = fire.new_field(4, 3)
    assert len(field) == 3
    assert all(len(row) == 4 for row in field)

    field[0][0] = 0.75
    assert field[1][0] == 0.0
    assert field[2][0] == 0.0
    assert field[0][1] == 0.0


def test_new_field_rows_are_distinct_objects():
    field = fire.new_field(4, 3)
    assert _distinct(field)


# --- 2. advance: a new field, the input never mutated ----------------------


def test_advance_does_not_mutate_its_input():
    rng = random.Random(11)
    field = fire.new_field(5, 4)
    field = fire.advance(field, rng)
    before = _copy(field)

    fire.advance(field, rng)

    assert field == before, "advance mutated the input field"


def test_advance_returns_a_field_that_shares_no_row_with_the_input():
    rng = random.Random(11)
    field = fire.advance(fire.new_field(5, 4), rng)
    out = fire.advance(field, rng)

    assert out is not field
    assert len(out) == len(field)
    assert all(len(row) == len(src) for row, src in zip(out, field))
    assert _shared(out, field) == []
    assert out != field  # a tick actually changes the field


def test_advance_on_an_empty_field_is_still_a_new_field():
    for empty in ([], [[], []]):
        out = fire.advance(empty, random.Random(11))
        assert out == empty
        assert out is not empty
        assert _distinct(out)
        assert _shared(out, empty) == []


# --- 3. heat_to_rgb without rng: exact and stateless -----------------------

HEATS = [0.01, 0.25, 0.5, 0.75, 0.99]


def test_heat_to_rgb_is_exact_for_repeated_calls():
    for base_zone in (False, True):
        for heat in HEATS:
            first = fire.heat_to_rgb(heat, base_zone=base_zone)
            second = fire.heat_to_rgb(heat, base_zone=base_zone)
            assert first is not None
            assert first == second, f"heat {heat} mapped twice: {first} != {second}"
            assert all(0 <= channel <= 255 for channel in first)


def test_heat_to_rgb_does_not_depend_on_the_order_of_calls():
    ascending = {
        heat: fire.heat_to_rgb(heat, base_zone=base_zone)
        for base_zone in (False, True)
        for heat in HEATS
    }
    descending = {
        heat: fire.heat_to_rgb(heat, base_zone=base_zone)
        for base_zone in (False, True)
        for heat in reversed(HEATS)
    }
    assert ascending == descending


def test_heat_to_rgb_empty_cells_are_none():
    assert fire.heat_to_rgb(0.0) is None
    assert fire.heat_to_rgb(-0.5) is None
    assert fire.heat_to_rgb(0.0, base_zone=True) is None


# --- 4. render_frame: pure ------------------------------------------------


def test_render_frame_does_not_mutate_the_field():
    rng = random.Random(11)
    field = fire.advance(fire.new_field(6, 4), rng)

    for _ in range(2):  # with and without the colour-jitter stream
        before = _copy(field)
        frame = fire.render_frame(field, rng=random.Random(3))
        assert isinstance(frame, str) and frame
        assert field == before, "render_frame mutated the field"

        before = _copy(field)
        frame = fire.render_frame(field)
        assert isinstance(frame, str) and frame
        assert field == before, "render_frame mutated the field"


def test_render_frame_is_deterministic_for_a_fixed_rng():
    field = fire.advance(fire.new_field(6, 4), random.Random(11))
    assert fire.render_frame(field, rng=random.Random(5)) == fire.render_frame(
        field, rng=random.Random(5)
    )


# --- 5. simulate: fresh independent structures -----------------------------


def test_simulate_returns_deep_equal_but_unshared_structures():
    first = fire.simulate(5, 4, 3, 2)
    second = fire.simulate(5, 4, 3, 2)

    assert len(first) == len(second) == 2
    assert first == second
    assert _distinct(first) and _distinct(second)
    assert _shared(first, second) == []


def test_mutating_one_simulate_result_does_not_change_the_other():
    first = fire.simulate(5, 4, 3, 2)
    second = fire.simulate(5, 4, 3, 2)
    before = _copy(second)

    first[0][0][0] = 1.0
    first[1].append(0.5)

    assert second == before, "two simulate() calls share structure"
