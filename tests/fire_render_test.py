"""Reference tests for TASK-STANOK-CC-249 (FIRE2-02): src/fire_render.py —
terminal driver constants + half-block frame renderer."""

import random

from fire_engine import PALETTE
from fire_render import ENTER, EXIT, PAIR_CACHE, frame_bytes, render_frame

CELL = "▀"  # U+2580 UPPER HALF BLOCK
HOME = "\x1b[H"
RESET = "\x1b[0m"


def naive_pair(top, bottom):
    """Naively formatted reference for one (top, bottom) palette-index pair."""
    tr, tg, tb = PALETTE[top]
    br, bg, bb = PALETTE[bottom]
    return f"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m{CELL}"


class FakeField:
    """Minimal FireField-like object: render_frame reads only width/height/buffer."""

    def __init__(self, width, height, buffer):
        assert len(buffer) == width * height
        self.width = width
        self.height = height
        self.buffer = list(buffer)


def expected_frame(pairs_per_row):
    """Frame string from a list of rows, each a list of (top, bottom) index pairs."""
    rows = ["".join(naive_pair(t, b) for t, b in row) for row in pairs_per_row]
    return HOME + "\n".join(rows) + RESET


# --- terminal control constants -------------------------------------------

def test_enter_constant_is_alt_screen_and_hide_cursor():
    assert ENTER == "\x1b[?1049h\x1b[?25l"


def test_exit_constant_leaves_alt_screen_shows_cursor_resets_sgr():
    assert EXIT == "\x1b[?1049l\x1b[?25h\x1b[0m"


# --- PAIR_CACHE -------------------------------------------------------------

def test_pair_cache_has_1369_entries():
    assert len(PAIR_CACHE) == 37 * 37 == 1369


def test_pair_cache_covers_every_index_pair():
    for top in range(37):
        for bottom in range(37):
            assert (top, bottom) in PAIR_CACHE


def test_pair_cache_entry_matches_exact_escape_format():
    # Spot checks: index 0 (07,07,07) over index 36 (255,255,255), and a mid pair.
    assert PAIR_CACHE[(0, 36)] == (
        "\x1b[38;2;7;7;7m\x1b[48;2;255;255;255m" + CELL
    )
    assert PAIR_CACHE[(36, 0)] == (
        "\x1b[38;2;255;255;255m\x1b[48;2;7;7;7m" + CELL
    )
    assert PAIR_CACHE[(18, 5)] == (
        "\x1b[38;2;207;119;15m\x1b[48;2;103;31;7m" + CELL
    )


def test_pair_cache_entries_end_with_the_half_block_cell():
    for entry in PAIR_CACHE.values():
        assert isinstance(entry, str) and entry.endswith(CELL)
        assert entry.count("\x1b[38;2;") == 1 and entry.count("\x1b[48;2;") == 1
        assert "\n" not in entry


def test_pair_cache_flat_index_access_matches_tuple_access():
    for top in (0, 1, 18, 36):
        for bottom in (0, 7, 35, 36):
            assert PAIR_CACHE[top * 37 + bottom] == PAIR_CACHE[(top, bottom)]


def test_pair_cache_equals_naive_reference_for_random_pairs():
    # Property check: the cached string is byte-identical to a naively
    # formatted one, for seeded-random pairs (no flakiness: fixed seed).
    rng = random.Random(20261012)
    for _ in range(200):
        top = rng.randrange(37)
        bottom = rng.randrange(37)
        assert PAIR_CACHE[(top, bottom)] == naive_pair(top, bottom)


# --- render_frame: exact output --------------------------------------------

def test_render_frame_2x2_exact_string():
    field = FakeField(2, 2, [0, 1, 35, 36])  # top row [0,1], bottom row [35,36]
    assert render_frame(field) == expected_frame([[(0, 35), (1, 36)]])


def test_render_frame_4x4_exact_string():
    field = FakeField(4, 4, [
        0, 1, 2, 3,
        36, 35, 34, 33,
        10, 11, 12, 13,
        20, 21, 22, 23,
    ])
    assert render_frame(field) == expected_frame([
        [(0, 36), (1, 35), (2, 34), (3, 33)],
        [(10, 20), (11, 21), (12, 22), (13, 23)],
    ])


def test_render_frame_fg_is_top_row_color_and_bg_is_bottom_row_color():
    # Swapping the two field rows must swap fg and bg, not reuse a cached cell.
    a = FakeField(1, 2, [0, 36])
    b = FakeField(1, 2, [36, 0])
    assert render_frame(a) == HOME + naive_pair(0, 36) + RESET
    assert render_frame(b) == HOME + naive_pair(36, 0) + RESET
    assert render_frame(a) != render_frame(b)


def test_render_frame_accepts_a_real_fire_field():
    from fire_engine import FireField

    field = FireField(3, 4)
    field.buffer = [
        0, 0, 0,
        5, 6, 7,
        30, 31, 32,
        36, 36, 36,
    ]
    # Terminal row 0 pairs field rows 0 and 1; row 1 pairs rows 2 and 3.
    assert render_frame(field) == expected_frame([
        [(0, 5), (0, 6), (0, 7)],
        [(30, 36), (31, 36), (32, 36)],
    ])


# --- render_frame: frame structure -----------------------------------------

def test_render_frame_starts_with_cursor_home_and_has_no_clear():
    frame = render_frame(FakeField(2, 2, [0, 0, 36, 36]))
    assert frame.startswith(HOME)
    assert frame.count(HOME) == 1
    assert "\x1b[2J" not in frame  # no clear-screen: the whole cell is repainted
    assert "\x1b[?1049" not in frame  # ENTER/EXIT are the driver's job, not the frame's


def test_render_frame_ends_with_single_sgr_reset():
    frame = render_frame(FakeField(3, 4, list(range(12))))
    assert frame.endswith(RESET)
    assert frame.count(RESET) == 1


def test_render_frame_row_count_and_cell_count():
    for width, height in ((5, 6), (8, 8), (1, 2), (3, 4)):
        frame = render_frame(FakeField(width, height, [0] * (width * height)))
        body = frame[len(HOME):len(frame) - len(RESET)]
        rows = body.split("\n")
        assert len(rows) == height // 2
        # An all-zero field is exactly `width` copies of the cached (0, 0) cell.
        assert all(row == PAIR_CACHE[(0, 0)] * width for row in rows)


def test_render_frame_rows_are_joined_with_newlines_only():
    frame = render_frame(FakeField(2, 6, list(range(12))))
    body = frame[len(HOME):len(frame) - len(RESET)]
    assert body.count("\n") == 2
    assert "\r" not in frame


def test_render_frame_odd_height_renders_every_field_row():
    # A trailing unpaired field row is rendered as a full block (fg == bg),
    # never silently dropped.
    field = FakeField(2, 3, [0, 1, 2, 3, 4, 5])
    assert render_frame(field) == expected_frame([
        [(0, 2), (1, 3)],
        [(4, 4), (5, 5)],
    ])


def test_render_frame_single_row_field_pairs_with_itself():
    field = FakeField(2, 1, [7, 8])
    assert render_frame(field) == expected_frame([[(7, 7), (8, 8)]])


def test_render_frame_empty_field_is_home_plus_reset():
    assert render_frame(FakeField(0, 0, [])) == HOME + RESET


def test_render_frame_does_not_mutate_the_field():
    field = FakeField(2, 2, [3, 4, 5, 6])
    before = list(field.buffer)
    render_frame(field)
    render_frame(field)
    assert field.buffer == before
    assert (field.width, field.height) == (2, 2)


def test_render_frame_is_reproducible_for_the_same_buffer():
    buf = list(range(24))
    a = render_frame(FakeField(4, 6, buf))
    b = render_frame(FakeField(4, 6, buf))
    assert a == b


# --- frame_bytes -------------------------------------------------------------

def test_frame_bytes_is_the_utf8_encoding_of_the_frame():
    frame = render_frame(FakeField(2, 2, [0, 1, 35, 36]))
    raw = frame_bytes(frame)
    assert isinstance(raw, bytes)
    assert raw == frame.encode("utf-8")
    assert raw.endswith(RESET.encode("utf-8"))


def test_frame_bytes_encodes_the_half_block_as_three_bytes():
    raw = frame_bytes(render_frame(FakeField(1, 2, [0, 36])))
    assert raw == (HOME + naive_pair(0, 36) + RESET).encode("utf-8")
    assert raw.count(b"\xe2\x96\x80") == 1  # U+2580 in UTF-8
