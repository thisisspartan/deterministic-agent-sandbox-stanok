"""Reference tests for src/fire_render.py — ticket TASK-STANOK-CC-275.

Stage 2 of the console-fire pipeline: heat field -> frame string
(half-block truecolor). Pure: determinism, purity, escape layout.
Self-contained — fixtures defined here, no conftest. Fields are hand-built
literal lists of floats; fire_sim is NOT imported here: the renderer must
accept any [0, 1] field.
"""

import copy
import random

import pytest

import fire_render

HALF = "▀"  # U+2580
RESET = "\x1b[0m"


def _zero_field(width, height):
    return [[0.0] * width for _ in range(height)]


def _hot_field(width, height):
    return [[1.0] * width for _ in range(height)]


# --- constants ---------------------------------------------------------------


def test_constants_exact():
    assert fire_render.HALF_BLOCK == "▀"
    assert fire_render.FALLBACK_COLUMNS == 80
    assert fire_render.FALLBACK_ROWS == 24
    assert fire_render.ANSI_RESET == "\x1b[0m"


# --- render_frame: cold field -------------------------------------------------


def test_all_cold_field_is_bare_half_blocks_no_escapes():
    field = _zero_field(6, 4)  # every heat 0.0 -> below the palette threshold
    frame = fire_render.render_frame(field, random.Random(1))
    lines = frame.split("\n")
    assert len(lines) == 4 // 2
    for line in lines:
        assert line == HALF * 6
    assert "\x1b" not in frame


# --- render_frame: shape rules ------------------------------------------------


def test_odd_height_raises_value_error():
    field = _zero_field(3, 3)
    with pytest.raises(ValueError):
        fire_render.render_frame(field, random.Random(1))


def test_line_structure_4x6_field():
    # height 4 x width 6 -> exactly 2 lines, each exactly 6 glyphs.
    field = _zero_field(6, 4)
    frame = fire_render.render_frame(field, random.Random(2))
    lines = frame.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert line.count(HALF) == 6


# --- render_frame: purity -----------------------------------------------------


def test_render_frame_does_not_mutate_field():
    field = [[0.0, 0.5, 1.0], [0.9, 0.0, 0.3], [0.7, 0.7, 0.0], [1.0, 0.2, 0.0]]
    original = copy.deepcopy(field)
    fire_render.render_frame(field, random.Random(3))
    assert field == original, "render_frame must not mutate its input field"


# --- render_frame: determinism ------------------------------------------------


def test_same_field_same_rng_state_is_byte_identical():
    field = [[0.0, 1.0, 0.4], [0.8, 0.0, 1.0], [0.6, 0.6, 0.0], [1.0, 0.1, 0.9]]
    a = fire_render.render_frame(field, random.Random(7))
    b = fire_render.render_frame(field, random.Random(7))
    assert a == b


def test_hot_field_emits_foreground_and_background_escapes():
    field = _hot_field(4, 2)  # a hot cell (1.0) on both halves
    frame = fire_render.render_frame(field, random.Random(7))
    assert "38;2;" in frame
    assert "48;2;" in frame


# --- render_frame: escape layout ----------------------------------------------


def test_escape_order_fg_then_bg_then_glyph_then_reset():
    field = _hot_field(2, 2)
    frame = fire_render.render_frame(field, random.Random(11))
    line = frame.split("\n")[0]
    i_fg = line.index("38;2;")
    i_bg = line.index("48;2;")
    i_glyph = line.index(HALF)
    i_reset = line.index(RESET)
    assert i_fg < i_bg < i_glyph < i_reset


def test_none_upper_half_emits_background_only():
    # upper heat 0.0 (None half), lower heat 1.0 (colored half)
    field = [[0.0], [1.0]]
    frame = fire_render.render_frame(field, random.Random(5))
    line = frame.split("\n")[0]
    assert "48;2;" in line
    assert "38;2;" not in line
    assert line.startswith("\x1b[48;2;")
    assert line.endswith(HALF + RESET)


def test_none_lower_half_emits_foreground_only():
    field = [[1.0], [0.0]]
    frame = fire_render.render_frame(field, random.Random(5))
    line = frame.split("\n")[0]
    assert "38;2;" in line
    assert "48;2;" not in line
    assert line.startswith("\x1b[38;2;")
    assert line.endswith(HALF + RESET)


# --- compose_frame -------------------------------------------------------------


def test_compose_centers_and_pads_canvas():
    # 2x4 frame (2 lines, 4 glyphs wide) into a 6x10 canvas.
    frame = "\n".join([HALF * 4, HALF * 4])
    canvas = fire_render.compose_frame(frame, columns=10, rows=6)
    lines = canvas.split("\n")
    assert len(lines) == 6
    indent = " " * ((10 - 4) // 2)
    assert lines[0] == indent + HALF * 4
    assert lines[1] == indent + HALF * 4
    assert lines[2:] == [""] * 4


def test_compose_exact_fit_adds_no_padding():
    frame = "\n".join([HALF * 4, HALF * 4])
    canvas = fire_render.compose_frame(frame, columns=4, rows=2)
    lines = canvas.split("\n")
    assert len(lines) == 2
    assert lines[0] == HALF * 4
    assert lines[1] == HALF * 4


def test_compose_rejects_frame_wider_than_canvas():
    frame = HALF * 12
    with pytest.raises(ValueError):
        fire_render.compose_frame(frame, columns=10, rows=6)


def test_compose_rejects_frame_taller_than_canvas():
    frame = "\n".join([HALF * 4] * 3)
    with pytest.raises(ValueError):
        fire_render.compose_frame(frame, columns=10, rows=2)
