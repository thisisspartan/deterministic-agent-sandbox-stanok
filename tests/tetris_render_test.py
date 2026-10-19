"""CC-303 — tetris_render reference tests (pins R1..R5).

The contract (docs/tetris_render.md): pure functions rendering a duck-typed
board (list[list[int]], 0 empty / 1..7 piece id) into one ANSI half-block
truecolor frame string. The engine is NOT imported here or in the subject;
every expected color and every expected line is an in-test transcription of the
SPEC-pinned literals and of the pinned frame formula — the production module is
never used to derive an expectation.

Fixtures are defined inside this file (no conftest.py).
"""

import ast
import copy
import inspect
import re

import pytest

import tetris_render as rend  # pythonpath=src (see scripts/run.sh registry)

# --- SPEC-pinned literals (R3/R4 host transcription) -----------------------

RESET = "\x1b[0m"
GLYPH = "▀"  # U+2580
GLYPH_UTF8 = b"\xe2\x96\x80"
BORDER_RGB = (120, 120, 120)
EMPTY_RGB = (20, 20, 20)

# R4: id1 I, id2 O, id3 T, id4 S, id5 Z, id6 J, id7 L — hex literals whose
# decimal channels are the pinned RGBs.
SPEC_HEX = {
    1: "#00ffff", 2: "#ffff00", 3: "#a000ff", 4: "#00ff00",
    5: "#ff0000", 6: "#0078ff", 7: "#ff7800",
}


def _hex(literal: str) -> tuple:
    return tuple(int(literal[i:i + 2], 16) for i in (1, 3, 5))


PIECE_COLORS = {pid: _hex(literal) for pid, literal in SPEC_HEX.items()}

SEG_RE = re.compile(
    r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m" + GLYPH
)
LINE_RE = re.compile(
    r"(?:\x1b\[38;2;\d+;\d+;\d+m\x1b\[48;2;\d+;\d+;\d+m" + GLYPH + r")+\x1b\[0m"
)


# --- in-test transcription of the frame formula (R2..R4) -------------------

def _seg(fg, bg):
    return (f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m"
            f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m{GLYPH}")


def _color(value):
    return EMPTY_RGB if value == 0 else PIECE_COLORS[value]


def _expected_frame(board, active=None):
    """Independent builder of the expected frame from the SPEC pins."""
    height, width = len(board), len(board[0])
    eff = [list(row) for row in board]
    if active is not None:
        shape, x, y, piece_id = active
        for r, row in enumerate(shape):
            for c, value in enumerate(row):
                if not value:
                    continue
                yy, xx = y + r, x + c
                if 0 <= yy < height and 0 <= xx < width:
                    eff[yy][xx] = piece_id
    border = _seg(BORDER_RGB, BORDER_RGB) * width + RESET
    lines = [border]
    for t in range(height // 2):
        top, bottom = eff[2 * t], eff[2 * t + 1]
        lines.append("".join(_seg(_color(top[c]), _color(bottom[c]))
                             for c in range(width)) + RESET)
    lines.append(border)
    return "\n".join(lines)


def _empty_board(width, height):
    return [[0] * width for _ in range(height)]


def _lines(frame):
    return frame.split("\n")


def _segments(line):
    return [tuple(int(v) for v in match) for match in SEG_RE.findall(line)]


# --- R2: frame geometry -----------------------------------------------------

def test_frame_is_half_height_plus_two_lines():
    board = _empty_board(10, 20)
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    assert len(_lines(out)) == len(board) // 2 + 2 == 12


@pytest.mark.parametrize("width,height", [(4, 2), (6, 4), (8, 8), (1, 2), (10, 20)])
def test_geometry_holds_for_other_boards(width, height):
    board = _empty_board(width, height)
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    assert len(_lines(out)) == height // 2 + 2


def test_frame_has_no_trailing_newline():
    out = rend.render_board(_empty_board(5, 6))
    assert not out.endswith("\n")
    assert not out.startswith("\n")
    assert "\r" not in out


# --- R3: exact segment encoding, one reset per line -------------------------

def test_every_line_is_segments_then_exactly_one_reset():
    out = rend.render_board(_empty_board(10, 20))
    for line in _lines(out):
        assert LINE_RE.fullmatch(line), line
        assert line.count(RESET) == 1
        assert line.endswith(RESET)
        assert len(_segments(line)) == 10


def test_glyph_is_u2580_encoded_e2_96_80():
    out = rend.render_board(_empty_board(3, 2))
    data = out.encode("utf-8")
    # 3 lines (border + 1 half-block row + border) x 3 cells.
    assert data.count(GLYPH_UTF8) == 9
    assert len(_lines(out)) == 3


def test_border_rows_are_solid_border_color():
    out = rend.render_board(_empty_board(10, 20))
    lines = _lines(out)
    for line in (lines[0], lines[-1]):
        segments = _segments(line)
        assert len(segments) == 10
        for segment in segments:
            assert segment == BORDER_RGB + BORDER_RGB


def test_empty_cells_are_dark_on_both_halves():
    out = rend.render_board(_empty_board(10, 20))
    for line in _lines(out)[1:-1]:
        for segment in _segments(line):
            assert segment == EMPTY_RGB + EMPTY_RGB


def test_fg_is_upper_board_row_and_bg_is_lower():
    board = _empty_board(4, 2)
    board[0] = [1, 2, 0, 0]  # fg of screen row 0
    board[1] = [0, 0, 3, 4]  # bg of screen row 0
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    segments = _segments(_lines(out)[1])
    assert segments[0][:3] == PIECE_COLORS[1] and segments[0][3:] == EMPTY_RGB
    assert segments[1][:3] == PIECE_COLORS[2] and segments[1][3:] == EMPTY_RGB
    assert segments[2][:3] == EMPTY_RGB and segments[2][3:] == PIECE_COLORS[3]
    assert segments[3][:3] == EMPTY_RGB and segments[3][3:] == PIECE_COLORS[4]


def test_screen_row_t_uses_board_rows_2t_and_2t_plus_1():
    board = _empty_board(6, 6)
    board[4] = [0, 6, 0, 0, 0, 0]  # fg of screen row 2
    board[5] = [0, 0, 0, 0, 0, 7]  # bg of screen row 2
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    segments = _segments(_lines(out)[3])  # border + rows 0,1 + row 2
    assert segments[1][:3] == PIECE_COLORS[6] and segments[1][3:] == EMPTY_RGB
    assert segments[5][:3] == EMPTY_RGB and segments[5][3:] == PIECE_COLORS[7]


# --- R4: the palette is exact ----------------------------------------------

def test_module_palette_matches_the_pinned_table():
    assert dict(rend.PIECE_COLORS) == PIECE_COLORS
    assert len({tuple(v) for v in rend.PIECE_COLORS.values()}) == 7


@pytest.mark.parametrize("piece_id", sorted(PIECE_COLORS))
def test_each_piece_id_paints_its_pinned_rgb(piece_id):
    board = _empty_board(2, 2)
    board[0][0] = piece_id  # upper half
    board[1][0] = piece_id  # lower half
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    segment = _segments(_lines(out)[1])[0]
    assert segment == PIECE_COLORS[piece_id] + PIECE_COLORS[piece_id]


def test_palette_colors_are_seven_distinct_and_not_specials():
    colors = {tuple(v) for v in PIECE_COLORS.values()}
    assert len(colors) == 7
    for color in colors:
        assert color != EMPTY_RGB and color != BORDER_RGB


def test_all_ids_and_empty_render_side_by_side():
    board = _empty_board(10, 20)
    board[0] = [1, 2, 3, 4, 5, 6, 7, 0, 1, 7]
    board[19] = [7, 6, 5, 4, 3, 2, 1, 0, 0, 0]
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    first = _segments(_lines(out)[1])    # screen row 0 = board rows 0, 1
    assert first[9][:3] == PIECE_COLORS[7] and first[9][3:] == EMPTY_RGB
    assert first[7] == EMPTY_RGB + EMPTY_RGB
    last = _segments(_lines(out)[-2])    # last screen row = board rows 18, 19
    assert last[0][:3] == EMPTY_RGB and last[0][3:] == PIECE_COLORS[7]
    assert last[6][:3] == EMPTY_RGB and last[6][3:] == PIECE_COLORS[1]


# --- R1: active overlay ----------------------------------------------------

def test_active_none_renders_the_board_only():
    board = _empty_board(6, 4)
    board[2] = [1, 0, 0, 0, 0, 2]
    assert rend.render_board(board) == _expected_frame(board)
    assert rend.render_board(board, None) == _expected_frame(board)


def test_active_overlay_paints_over_board_cells_inside_its_bounds():
    board = _empty_board(10, 20)
    board[10][2] = 5  # a locked cell under the piece — must be covered
    board[10][5] = 7  # outside the shape — must stay
    active = (((1, 0), (1, 1)), 2, 10, 3)
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    segments = _segments(_lines(out)[6])  # screen row 5 = board rows 10, 11
    assert segments[2] == PIECE_COLORS[3] + PIECE_COLORS[3]
    assert segments[3][:3] == EMPTY_RGB and segments[3][3:] == PIECE_COLORS[3]
    assert segments[1] == EMPTY_RGB + EMPTY_RGB
    assert segments[5][:3] == PIECE_COLORS[7]


def test_overlay_color_follows_piece_id_not_shape_values():
    board = _empty_board(10, 20)
    # shape cells carry the value 7; the painted color must follow piece_id=3
    active = (((7, 0), (7, 7)), 2, 10, 3)
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    segments = _segments(_lines(out)[6])
    assert segments[2][:3] == PIECE_COLORS[3]
    assert segments[2][:3] != PIECE_COLORS[7]
    assert segments[3][3:] == PIECE_COLORS[3]


def test_active_partially_off_board_is_clipped_without_error():
    board = _empty_board(10, 20)
    active = (((1, 1), (1, 1)), 9, 19, 2)  # col 10 and row 20 hang off-board
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    assert len(_lines(out)) == 12
    segments = _segments(_lines(out)[10])  # screen row 9 = board rows 18, 19
    assert segments[9][:3] == EMPTY_RGB and segments[9][3:] == PIECE_COLORS[2]
    assert segments[8] == EMPTY_RGB + EMPTY_RGB


def test_active_with_negative_offsets_is_clipped():
    board = _empty_board(6, 4)
    active = (((1, 1), (1, 1)), -1, -1, 4)
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    assert len(_lines(out)) == 4
    # only shape cell (r=1, c=1) lands on the board: board[0][0]
    segments = _segments(_lines(out)[1])  # screen row 0 = board rows 0, 1
    assert segments[0][:3] == PIECE_COLORS[4] and segments[0][3:] == EMPTY_RGB
    assert segments[1] == EMPTY_RGB + EMPTY_RGB


def test_active_with_empty_shape_leaves_frame_unchanged():
    board = _empty_board(6, 4)
    board[1][1] = 6
    assert rend.render_board(board, active=((), 0, 0, 1)) == _expected_frame(board)
    assert rend.render_board(board, active=(((0, 0),), 0, 0, 1)) == _expected_frame(board)


# --- R2: validation negatives ----------------------------------------------

def _bad_boards():
    odd = _empty_board(10, 19)
    ragged = [[0, 0], [0, 0, 0]]
    ragged2 = [[0, 0, 0], [0, 0]]
    too_high = _empty_board(10, 4)
    too_high[1][3] = 8
    negative = _empty_board(10, 4)
    negative[0][0] = -1
    not_int = _empty_board(10, 4)
    not_int[0][0] = "1"
    zero_width = [[], []]
    return {
        "empty_board": lambda: [],
        "odd_height": lambda: odd,
        "ragged_rows": lambda: ragged,
        "ragged_first_row_shorter": lambda: ragged2,
        "cell_value_8": lambda: too_high,
        "cell_value_negative": lambda: negative,
        "cell_value_not_int": lambda: not_int,
        "zero_width": lambda: zero_width,
    }


@pytest.mark.parametrize("make_board", list(_bad_boards().values()),
                         ids=list(_bad_boards()))
def test_invalid_boards_raise_value_error(make_board):
    with pytest.raises(ValueError):
        rend.render_board(make_board())


@pytest.mark.parametrize("piece_id", [0, 8, -1, 99, None])
def test_piece_id_outside_1_7_raises_value_error(piece_id):
    with pytest.raises(ValueError):
        rend.render_board(_empty_board(10, 4), active=(((1,),), 0, 0, piece_id))


def test_valid_piece_ids_do_not_raise():
    for piece_id in range(1, 8):
        rend.render_board(_empty_board(10, 4), active=(((1,),), 0, 0, piece_id))


# --- R5: no cursor/erase controls, purity, determinism --------------------

def test_frame_contains_no_cursor_home_or_erase_sequences():
    board = _empty_board(10, 20)
    board[0][0] = 1
    out = rend.render_board(board, active=(((1, 1),), 0, 0, 1))
    for seq in ("\x1b[H", "\x1b[2J", "\x1b[?25", "\x1b[?25l", "\x1b[?25h", "?25"):
        assert seq not in out, seq


def test_module_does_not_import_the_engine():
    source = inspect.getsource(rend)
    tree = ast.parse(source)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
    for name in imported:
        assert "tetris_engine" not in name, f"renderer imports {name}"
    # ... nor pulls it in by name through importlib.
    assert "tetris_engine" not in source


def test_render_does_not_mutate_board_or_active():
    board = _empty_board(10, 20)
    board[3] = [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]
    shape = ((1, 0), (1, 1))
    active = (shape, 4, 9, 4)
    before_board = copy.deepcopy(board)
    before_active = copy.deepcopy(active)
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active)
    assert board == before_board
    assert active == before_active
    assert shape == ((1, 0), (1, 1))


def test_shared_row_objects_are_not_mutated_by_the_overlay():
    row = [0] * 10
    board = [row for _ in range(20)]  # the same list object, 20 times
    rend.render_board(board, active=(((1,),), 0, 0, 1))
    assert row == [0] * 10
    assert all(r is row for r in board)


def test_identical_input_gives_byte_identical_output():
    board = _empty_board(10, 20)
    board[0] = [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]
    active = (((1, 1), (1, 1)), 3, 4, 6)
    out1 = rend.render_board(board, active=active)
    out2 = rend.render_board(board, active=active)
    assert out1 == out2
    assert out1.encode("utf-8") == out2.encode("utf-8")
    assert isinstance(out1, str)
