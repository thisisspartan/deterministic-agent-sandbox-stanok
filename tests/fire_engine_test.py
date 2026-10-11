"""Acceptance tests for src/fire_engine.py (TASK-STANOK-CC-240 / FIRE-01).

Contract under test (pure Doom Fire logic, no I/O):
- PALETTE: exactly 37 RGB tuples (the classic Doom fire palette).
- FireField(width, height, rng=None): flat buffer[y*width+x], y=0 top,
  y=height-1 is the source row seeded to 36; rng is an injectable
  random.Random (default module random).
- step(wind=0): single bottom-up pass; for each non-zero source pixel
  rand = rng.randint(0,3), dst = x - rand + 1 + wind, in-bounds writes
  max(0, src - (rand & 1)); zero source writes 0; out-of-bounds dst is
  skipped (no wrap); wind clamped to [-3, 3].
- color_at(value) -> PALETTE[value].

Every test uses a seeded random.Random so results are exact and reproducible.
"""

import random

from src.fire_engine import PALETTE, FireField


def rows(field):
    """Read a FireField's flat buffer back into a list of rows (top first)."""
    w, h = field.width, field.height
    return [field.buffer[y * w:(y + 1) * w] for y in range(h)]


def leading_zeros(row):
    n = 0
    for v in row:
        if v == 0:
            n += 1
        else:
            break
    return n


# --- PALETTE ---------------------------------------------------------------

def test_palette_has_exactly_37_entries():
    assert len(PALETTE) == 37


def test_palette_first_and_last_entries():
    assert PALETTE[0] == (0x07, 0x07, 0x07)
    assert PALETTE[36] == (0xFF, 0xFF, 0xFF)


def test_palette_known_intermediate_entries():
    # A pinned mid-palette entry guards against a shifted/truncated table.
    assert PALETTE[1] == (0x1F, 0x07, 0x07)
    assert PALETTE[18] == (0xCF, 0x77, 0x0F)
    assert PALETTE[34] == (0xEF, 0xEF, 0xC7)


def test_palette_entries_are_rgb_triples_of_bytes():
    for entry in PALETTE:
        assert isinstance(entry, tuple) and len(entry) == 3
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in entry)


# --- color_at ------------------------------------------------------------

def test_color_at_returns_the_palette_entry():
    assert color_at_is_palette(0)
    assert color_at_is_palette(18)
    assert color_at_is_palette(36)


def color_at_is_palette(value):
    from src.fire_engine import color_at
    return color_at(value) == PALETTE[value]


def test_color_at_endpoints_are_exact_tuples():
    from src.fire_engine import color_at
    assert color_at(0) == (0x07, 0x07, 0x07)
    assert color_at(36) == (0xFF, 0xFF, 0xFF)
    assert color_at(18) == (0xCF, 0x77, 0x0F)


# --- FireField construction ----------------------------------------------

def test_source_row_is_seeded_to_36():
    field = FireField(4, 3, rng=random.Random(0))
    r = rows(field)
    assert r[2] == [36, 36, 36, 36]  # bottom row is the source
    assert r[0] == [0, 0, 0, 0]      # every other row starts dark
    assert r[1] == [0, 0, 0, 0]


def test_buffer_is_flat_indexed_by_y_width_plus_x():
    field = FireField(3, 2, rng=random.Random(0))
    # The documented flat layout: buffer[y*width + x].
    width = field.width
    for x in range(width):
        assert field.buffer[1 * width + x] == 36  # source row
        assert field.buffer[0 * width + x] == 0   # top row


# --- step: exact propagation ---------------------------------------------

def test_step_propagates_to_exact_expected_row():
    # width=5, height=2, seed=42 -> randint(0,3) sequence [0,0,2,1,1].
    # x=0 r0 -> dst1=36; x=1 r0 -> dst2=36; x=2 r2 -> dst1=36;
    # x=3 r1 -> dst3=35; x=4 r1 -> dst4=35. Column 0 stays 0.
    field = FireField(5, 2, rng=random.Random(42))
    field.step()
    assert rows(field) == [[0, 36, 36, 35, 35], [36, 36, 36, 36, 36]]


def test_step_never_modifies_the_source_row():
    field = FireField(5, 3, rng=random.Random(42))
    field.step()
    assert rows(field)[2] == [36, 36, 36, 36, 36]  # source row untouched


# --- step: decay never below zero ----------------------------------------

def test_decay_never_goes_below_zero():
    # seed=3 -> randint sequence [1,1,2,3]; source all 2.
    # Odd rand decays by 1 (2->1), even rand by 0; nothing is ever negative
    # and no value exceeds its source.
    field = FireField(4, 2, rng=random.Random(3))
    field.buffer[1 * 4:2 * 4] = [2, 2, 2, 2]  # source row = 2
    field.step()
    top = rows(field)[0]
    assert top == [1, 1, 0, 0]
    assert all(v >= 0 for v in field.buffer)
    assert all(v <= 2 for v in field.buffer)


def test_decay_of_one_saturates_at_zero_not_negative():
    # source all 1 with odd rand must clamp to 0, never -1.
    field = FireField(4, 2, rng=random.Random(3))
    field.buffer[1 * 4:2 * 4] = [1, 1, 1, 1]
    field.step()
    assert all(v >= 0 for v in field.buffer)
    assert rows(field)[0] == [0, 0, 0, 0]


# --- step: wind shifts the propagation symmetrically ---------------------

def test_wind_shifts_the_source_index_symmetrically():
    # Same seed (randint sequence [3,0,0,0,0]) with wind -1 / 0 / +1:
    # the fire front shifts left / stays / shifts right by exactly wind.
    def run(wind):
        f = FireField(5, 2, rng=random.Random(1234))
        f.step(wind=wind)
        return rows(f)[0]

    minus = run(-1)
    base = run(0)
    plus = run(1)

    assert base == [0, 0, 36, 36, 36]
    assert plus == [0, 0, 0, 36, 36]   # base shifted right by 1
    assert minus == [0, 36, 36, 36, 36]  # base shifted left by 1

    # The leading dark gap grows/shrinks symmetrically with wind.
    assert leading_zeros(minus) == 1
    assert leading_zeros(base) == 2
    assert leading_zeros(plus) == 3


def test_wind_is_clamped_to_minus_three_through_three():
    def run(wind):
        f = FireField(5, 2, rng=random.Random(1234))
        f.step(wind=wind)
        return rows(f)[0]

    assert run(10) == run(3) == [0, 35, 0, 0, 0]
    assert run(-10) == run(-3) == [36, 36, 36, 0, 0]


# --- step: zero pixels stay zero -----------------------------------------

def test_zero_source_row_stays_zero():
    field = FireField(3, 2, rng=random.Random(99))
    field.buffer[1 * 3:2 * 3] = [0, 0, 0]  # a dark source row
    field.step()
    assert rows(field) == [[0, 0, 0], [0, 0, 0]]


# --- step: out-of-bounds dst is skipped, no wrap -------------------------

def test_out_of_bounds_dst_is_skipped_without_wrap():
    # seed=5 -> randint sequence [2,2,0]; width=3, source all 36.
    # x=0 r2 -> dst=-1 (skipped, must NOT wrap to column 2);
    # x=1 r2 -> dst=0 (36); x=2 r0 -> dst=3 (skipped).
    field = FireField(3, 2, rng=random.Random(5))
    field.step()
    top = rows(field)[0]
    assert top == [36, 0, 0]
    # No wrapped value leaked into the far column.
    assert top[2] == 0
