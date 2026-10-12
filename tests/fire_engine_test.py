"""Reference tests for TASK-STANOK-CC-248: src/fire_engine.py — pure Doom fire engine."""

import random

from fire_engine import PALETTE, FireField


class ScriptedRandom:
    """Deterministic rng stub: yields a scripted sequence of ints for randint()."""

    def __init__(self, values):
        self._values = list(values)
        self.calls = 0

    def randint(self, a, b):
        v = self._values[self.calls % len(self._values)]
        self.calls += 1
        assert a == 0 and b == 3, f"engine must draw rand in [0..3], got randint({a},{b})"
        return v

    def randrange(self, n):
        return self.randint(0, n - 1)


def make_field(width, height, rng=None):
    return FireField(width, height, rng=rng)


# --- palette -------------------------------------------------------------

def test_palette_length_and_endpoints():
    assert len(PALETTE) == 37
    assert PALETTE[0] == (0x07, 0x07, 0x07)
    assert PALETTE[1] == (0x1F, 0x07, 0x07)
    assert PALETTE[36] == (0xFF, 0xFF, 0xFF)
    assert PALETTE[35] == (0xFF, 0xFF, 0xFF)
    assert PALETTE[32] == (0xCF, 0xCF, 0x6F)


def test_palette_entries_are_rgb_tuples():
    for entry in PALETTE:
        assert isinstance(entry, tuple) and len(entry) == 3
        assert all(isinstance(c, int) and 0 <= c <= 255 for c in entry)


# --- construction --------------------------------------------------------

def test_source_row_seeded_to_36():
    f = make_field(5, 4)
    assert f.buffer == [0] * 15 + [36] * 5
    assert len(f.buffer) == 20


def test_buffer_is_flat_indexed_y_times_width_plus_x():
    f = make_field(3, 2)
    assert f.buffer[1 * 3 + 0] == 36
    assert f.buffer[1 * 3 + 2] == 36
    assert all(f.buffer[y * 3 + x] == 0 for y in range(1) for x in range(3))


# --- exact propagation (pinned seed) --------------------------------------

def test_exact_propagation_seeded():
    # random.Random(42).randint(0,3) sequence: 0,0,2,1,1
    # x=0 rand=0 -> dst=1 val=36; x=1 rand=0 -> dst=2 val=36;
    # x=2 rand=2 -> dst=1 val=36; x=3 rand=1 -> dst=3 val=35;
    # x=4 rand=1 -> dst=4 val=35.
    f = make_field(5, 2, rng=random.Random(42))
    f.step()
    assert f.buffer[:5] == [0, 36, 36, 35, 35]
    # source row is never modified by step
    assert f.buffer[5:] == [36] * 5


def test_repeated_steps_deterministic_with_seeded_rng():
    a = make_field(6, 4, rng=random.Random(7))
    b = make_field(6, 4, rng=random.Random(7))
    for _ in range(5):
        a.step()
        b.step()
    assert a.buffer == b.buffer


# --- decay / zero rules ---------------------------------------------------

def test_decay_never_below_zero():
    # rand=1 -> decrement 1; feed value 1 repeatedly, result must clamp at 0.
    f = make_field(4, 2, rng=ScriptedRandom([1]))
    f.buffer[4:] = [1, 1, 1, 1]
    f.step()
    assert all(v >= 0 for v in f.buffer)
    assert f.buffer[:4] == [0, 0, 0, 0]  # 1 - 1 = 0, never negative


def test_zero_pixels_stay_zero():
    f = make_field(4, 3, rng=ScriptedRandom([0, 1, 2, 3]))
    f.buffer = [0] * 12  # wipe everything, including the source row
    f.step()
    assert f.buffer == [0] * 12


def test_out_of_bounds_dst_skipped_no_wrap():
    # scripted rand=3 (odd -> decrement 1), width=4, wind=0:
    # x=0 dst=-2 skip; x=1 dst=-1 skip; x=2 dst=0 val=35; x=3 dst=1 val=35.
    # Skipped cells must not wrap to the far edge.
    f = make_field(4, 2, rng=ScriptedRandom([3]))
    f.step()
    assert f.buffer[:4] == [35, 35, 0, 0]


# --- wind -----------------------------------------------------------------

def test_wind_shifts_source_index_symmetrically():
    # rand=0 -> dst = x + 1 + wind. Compare wind=-1, 0, +1.
    def row_after(wind):
        f = make_field(5, 2, rng=ScriptedRandom([0]))
        f.step(wind=wind)
        return f.buffer[:5]

    assert row_after(0) == [0, 36, 36, 36, 36]  # x=4 -> dst=5 out of bounds
    assert row_after(-1) == [36, 36, 36, 36, 36]  # dst = x
    assert row_after(1) == [0, 0, 36, 36, 36]  # dst = x + 2
    # symmetry: wind=+1 result equals wind=-1 result shifted right by 2
    assert row_after(1) == [0, 0] + row_after(-1)[:3]


def test_wind_clamped_to_minus_three_three():
    def row_after(wind):
        f = make_field(6, 2, rng=ScriptedRandom([0]))
        f.step(wind=wind)
        return f.buffer[:6]

    # rand=0 -> dst = x+1+wind; clamped wind=3 -> dst=x+4: only x=0..1 land.
    clamped_hi = row_after(10)
    assert clamped_hi == row_after(3)
    assert clamped_hi == [0, 0, 0, 0, 36, 36]
    clamped_lo = row_after(-10)
    assert clamped_lo == row_after(-3)
    assert clamped_lo == [36, 36, 36, 36, 0, 0]  # dst = x - 2, only x>=2 land


# --- color_at ---------------------------------------------------------------

def test_color_at_bounds():
    f = make_field(2, 1)
    assert f.color_at(0) == PALETTE[0] == (0x07, 0x07, 0x07)
    assert f.color_at(36) == PALETTE[36] == (0xFF, 0xFF, 0xFF)
    assert f.color_at(18) == PALETTE[18]


# --- default rng ------------------------------------------------------------

def test_default_rng_produces_valid_values():
    f = make_field(8, 4)  # rng=None -> module random
    for _ in range(10):
        f.step()
        assert all(0 <= v <= 36 for v in f.buffer)
