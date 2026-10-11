"""Acceptance tests for src/fire_render.py (TASK-STANOK-CC-241 / FIRE-02).

Contract under test (terminal driver + half-block renderer, pure strings):
- ENTER / EXIT: exact terminal control sequences (alt screen + cursor, SGR reset).
- PAIR_CACHE: every one of the 37x37 palette index pairs (top, bottom) maps to
  the exact escape string
  "\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m▀", built once at import.
- render_frame(field): "\x1b[H" + terminal rows joined with "\n" + "\x1b[0m";
  each terminal row pairs two field rows (top y, bottom y+1), fg from the top
  row's color, bg from the bottom row's color, one cached cell per column.
- frame_bytes(frame): the utf-8 encoding of a frame string.

Tests import the engine only to read PALETTE; the renderer must agree with it.
"""

import random

from src.fire_engine import PALETTE, FireField
from src.fire_render import ENTER, EXIT, PAIR_CACHE, render_frame, frame_bytes


def naive_cell(top_index, bottom_index):
    """The reference formatting: exactly the escape string the cache must hold."""
    tr, tg, tb = PALETTE[top_index]
    br, bg, bb = PALETTE[bottom_index]
    return f"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m▀"


def naive_frame(values):
    """Reference frame for a field given as a list of rows of palette indices."""
    rows = ["".join(naive_cell(top, bottom) for top, bottom in zip(top_row, bottom_row))
            for top_row, bottom_row in zip(values[0::2], values[1::2])]
    return "\x1b[H" + "\n".join(rows) + "\x1b[0m"


def make_field(rows_of_values):
    """A FireField-shaped object with an exact hand-built buffer (no rng use)."""
    height = len(rows_of_values)
    width = len(rows_of_values[0])
    field = FireField(width, height, rng=random.Random(0))
    field.buffer = list(value for row in rows_of_values for value in row)
    return field


# --- terminal control constants -------------------------------------------

def test_enter_constant_is_alt_screen_and_hide_cursor():
    assert ENTER == "\x1b[?1049h\x1b[?25l"


def test_exit_constant_leaves_alt_screen_shows_cursor_resets_sgr():
    assert EXIT == "\x1b[?1049l\x1b[?25h\x1b[0m"


# --- PAIR_CACHE -----------------------------------------------------------

def test_pair_cache_has_all_37x37_entries():
    assert len(PAIR_CACHE) == 37 * 37 == 1369


def test_pair_cache_covers_every_index_pair():
    for top in range(37):
        for bottom in range(37):
            assert (top, bottom) in PAIR_CACHE


def test_pair_cache_entry_matches_the_exact_escape_format():
    # A pinned spot check with decimal RGB values written out literally:
    # PALETTE[1] = (0x1F,0x07,0x07) = (31,7,7), PALETTE[18] = (207,119,15).
    assert PAIR_CACHE[(1, 18)] == "\x1b[38;2;31;7;7m\x1b[48;2;207;119;15m▀"
    # Darkest over brightest, and the brightest corner.
    assert PAIR_CACHE[(0, 36)] == "\x1b[38;2;7;7;7m\x1b[48;2;255;255;255m▀"
    assert PAIR_CACHE[(36, 36)] == "\x1b[38;2;255;255;255m\x1b[48;2;255;255;255m▀"


def test_pair_cache_entries_are_two_sgr_sequences_then_one_half_block():
    for pair in ((0, 0), (5, 22), (36, 0)):
        entry = PAIR_CACHE[pair]
        assert entry.endswith("▀")
        assert entry.count("\x1b[38;2;") == 1
        assert entry.count("\x1b[48;2;") == 1
        assert entry.count("m") == 2
        assert entry.startswith("\x1b[38;2;")


def test_pair_cache_equals_naive_formatting_for_random_pairs():
    rng = random.Random(20261011)
    for _ in range(50):
        top = rng.randrange(37)
        bottom = rng.randrange(37)
        assert PAIR_CACHE[(top, bottom)] == naive_cell(top, bottom)


# --- render_frame: exact output -------------------------------------------

def test_render_frame_2x2_is_the_exact_expected_string():
    field = make_field([[0, 36], [1, 18]])
    expected = (
        "\x1b[H"
        "\x1b[38;2;7;7;7m\x1b[48;2;31;7;7m▀"
        "\x1b[38;2;255;255;255m\x1b[48;2;207;119;15m▀"
        "\x1b[0m"
    )
    assert render_frame(field) == expected


def test_render_frame_starts_with_home_and_ends_with_reset():
    frame = render_frame(make_field([[1, 2], [3, 4]]))
    assert frame.startswith("\x1b[H")
    assert frame.endswith("\x1b[0m")
    assert "\x1b[H" not in frame[1:]  # home appears exactly once
    assert "\x1b[0m" not in frame[:-len("\x1b[0m")]  # reset appears exactly once


def test_render_frame_uses_no_clear_and_no_cursor_moves():
    frame = render_frame(make_field([[1, 2], [3, 4]]))
    for forbidden in ("\x1b[2J", "\x1b[2K", "\x1b[H", "\x1b[?1049h", "\x1b[?25l"):
        if forbidden != "\x1b[H":
            assert forbidden not in frame
    assert frame.count("\x1b[H") == 1


def test_render_frame_pairs_field_rows_top_fg_bottom_bg():
    # 4 field rows -> 2 terminal rows; row pairs are (0,1) and (2,3).
    values = [[0, 1], [2, 3], [4, 5], [6, 7]]
    frame = render_frame(make_field(values))
    assert frame == naive_frame(values)
    body = frame[len("\x1b[H"):-len("\x1b[0m")]  # strip the home prefix / reset suffix
    lines = body.split("\n")
    assert len(lines) == 2
    assert lines[0] == naive_cell(0, 2) + naive_cell(1, 3)
    assert lines[1] == naive_cell(4, 6) + naive_cell(5, 7)


def test_render_frame_row_length_is_width_half_block_cells():
    width, height = 6, 4
    field = FireField(width, height, rng=random.Random(7))
    field.step()
    frame = render_frame(field)
    lines = frame[len("\x1b[H"):-len("\x1b[0m")].split("\n")
    assert len(lines) == height // 2
    for line in lines:
        assert line.count("▀") == width
        assert line.count("\x1b[38;2;") == width
        assert line.count("\x1b[48;2;") == width


def test_render_frame_matches_naive_reference_for_a_seeded_field():
    field = FireField(5, 4, rng=random.Random(42))
    field.step()
    field.step(wind=1)
    w, h = field.width, field.height
    values = [field.buffer[y * w:(y + 1) * w] for y in range(h)]
    assert render_frame(field) == naive_frame(values)


def test_render_frame_reads_the_field_without_mutating_it():
    field = FireField(3, 2, rng=random.Random(1))
    field.step()
    before = list(field.buffer)
    render_frame(field)
    assert field.buffer == before


# --- frame_bytes ----------------------------------------------------------

def test_frame_bytes_is_the_utf8_encoding_of_the_frame():
    field = make_field([[0, 36], [1, 18]])
    frame = render_frame(field)
    encoded = frame_bytes(frame)
    assert isinstance(encoded, bytes)
    assert encoded == frame.encode("utf-8")
    # The half block is 3 bytes in utf-8: 2 cells (one terminal row of width 2).
    assert encoded.count(b"\xe2\x96\x80") == 2
