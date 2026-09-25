"""Reference tests for src/fire/renderer.py (TASK-FIRE-04).

Contract:
- FireRenderer(palette) — palette is a list of (r, g, b) int tuples,
  each channel in [0..255];
- render(buffer) takes a rectangular heat matrix of height 2*H (even)
  and width W, with values in [0, len(palette) - 1];
- each row pair (y, y+1) becomes one terminal line of W '▀' (U+2580)
  characters: fg = palette[buffer[y][x]] via \033[38;2;r;g;bm,
  bg = palette[buffer[y+1][x]] via \033[48;2;r;g;bm;
- a color code is omitted when it equals the code of the previous
  pixel (the terminal color state persists across the whole frame);
- the frame ends with a color reset \033[0m;
- invalid input (odd height, ragged rows, out-of-range values, bad
  palette) raises ValueError.
"""

import re

import pytest

from fire.palette import generate_fire_palette
from fire.renderer import FireRenderer

HALF_BLOCK = "\u2580"  # ▀
ESC = "\033"


def _palette():
    """Identity red ramp: palette[i] = (i, 0, 0) — easy to verify."""
    return [(i, 0, 0) for i in range(256)]


def _strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


def test_render_two_lines_of_half_blocks():
    # Gate: a 4x2 terminal grid (heat matrix W=4, 2H=4) renders as
    # 2 terminal lines, each of 4 '▀' characters.
    renderer = FireRenderer(_palette())
    buffer = [
        [1, 2, 3, 4],
        [5, 6, 7, 8],
        [2, 3, 4, 5],
        [6, 7, 8, 9],
    ]
    out = renderer.render(buffer)
    lines = out.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert _strip_ansi(line).count(HALF_BLOCK) == 4


def test_render_4x2_heat_matrix():
    # A literal 4x2 heat matrix (4 rows, 2 columns) -> 2 lines of 2 '▀'.
    renderer = FireRenderer(_palette())
    out = renderer.render([[1, 2], [3, 4], [5, 6], [7, 8]])
    lines = out.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert _strip_ansi(line).count(HALF_BLOCK) == 2


def test_truecolor_escape_codes_present():
    renderer = FireRenderer(_palette())
    out = renderer.render([[1, 2, 3, 4], [5, 6, 7, 8]])
    assert "38;2;" in out
    assert "48;2;" in out


def test_frame_ends_with_reset():
    renderer = FireRenderer(_palette())
    out = renderer.render([[0, 0], [0, 0]])
    assert out.endswith(ESC + "[0m")


def test_first_pixel_emits_both_codes():
    renderer = FireRenderer(_palette())
    out = renderer.render([[10, 0], [20, 0]])
    first_pixel = (
        ESC + "[38;2;10;0;0m" + ESC + "[48;2;20;0;0m" + HALF_BLOCK
    )
    assert out.startswith(first_pixel)


def test_exact_output_small_buffer():
    renderer = FireRenderer(_palette())
    buffer = [[1, 2], [3, 4]]
    expected = (
        ESC + "[38;2;1;0;0m" + ESC + "[48;2;3;0;0m" + HALF_BLOCK
        + ESC + "[38;2;2;0;0m" + ESC + "[48;2;4;0;0m" + HALF_BLOCK
        + ESC + "[0m"
    )
    assert renderer.render(buffer) == expected


def test_repeated_colors_are_not_resent():
    renderer = FireRenderer(_palette())
    out = renderer.render([[5, 5, 5, 5], [7, 7, 7, 7]])
    assert out.count("38;2;") == 1
    assert out.count("48;2;") == 1
    assert out.count(HALF_BLOCK) == 4


def test_color_change_resends_only_changed_code():
    renderer = FireRenderer(_palette())
    # fg alternates 1,2,1,2 -> 4 fg codes; bg constant -> 1 bg code.
    out = renderer.render([[1, 2, 1, 2], [0, 0, 0, 0]])
    assert out.count("38;2;") == 4
    assert out.count("48;2;") == 1


def test_color_state_persists_across_lines():
    renderer = FireRenderer(_palette())
    # Both lines identical: each color is sent once for the whole frame.
    out = renderer.render([[9, 9], [8, 8], [9, 9], [8, 8]])
    assert out.count("38;2;") == 1
    assert out.count("48;2;") == 1
    assert out.count(HALF_BLOCK) == 4


def test_render_with_fire_palette():
    renderer = FireRenderer(generate_fire_palette())
    buffer = [
        [255, 128, 64, 0],
        [0, 32, 96, 180],
        [128, 255, 0, 64],
        [32, 96, 180, 0],
    ]
    out = renderer.render(buffer)
    lines = out.split("\n")
    assert len(lines) == 2
    for line in lines:
        assert _strip_ansi(line).count(HALF_BLOCK) == 4
    assert "38;2;" in out
    assert "48;2;" in out
    assert out.endswith(ESC + "[0m")


def test_empty_buffer_is_just_reset():
    renderer = FireRenderer(_palette())
    assert renderer.render([]) == ESC + "[0m"


def test_odd_height_rejected():
    renderer = FireRenderer(_palette())
    with pytest.raises(ValueError):
        renderer.render([[1, 2], [3, 4], [5, 6]])


def test_ragged_buffer_rejected():
    renderer = FireRenderer(_palette())
    with pytest.raises(ValueError):
        renderer.render([[1, 2], [3]])


def test_out_of_range_value_rejected():
    renderer = FireRenderer(_palette())
    with pytest.raises(ValueError):
        renderer.render([[256, 0], [0, 0]])
    with pytest.raises(ValueError):
        renderer.render([[-1, 0], [0, 0]])


def test_invalid_palette_rejected():
    with pytest.raises(ValueError):
        FireRenderer([(0, 0)])  # not a 3-tuple
    with pytest.raises(ValueError):
        FireRenderer([(300, 0, 0)])  # channel out of [0..255]
    with pytest.raises(ValueError):
        FireRenderer([])  # empty palette
