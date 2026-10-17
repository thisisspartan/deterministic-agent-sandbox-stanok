"""CC-283 — reference tests for src/tetris_render.py.

Covers the ticket contract: pinned constants, the half-block truecolor cell
escape-macro, even-height validation, per-cell color mapping (board ids ->
PIECE_COLORS, 0 -> EMPTY_COLOR), the active-piece overlay drawn in its piece
color with the board left untouched, and the no-engine-import rule.
"""
import copy
import importlib
import re
import sys

import pytest

import tetris_render as tr

# Escape-macro of one half-block cell: fg -> bg -> glyph -> reset.
CELL_RE = re.compile(
    r"\x1b\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m"
    r"\x1b\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m"
    r"▀\x1b\[0m"
)


# ---------------------------------------------------------------- helpers

def empty_board(width, height):
    return [[0] * width for _ in range(height)]


def frame_cells(frame):
    """Split a frame into lines, each line into its cell strings.

    Asserts every line is a pure sequence of valid cells (nothing left over
    after removing all cell matches) — the frame-wide escape-macro check.
    """
    cells = []
    for line in frame.split("\n"):
        found = list(CELL_RE.finditer(line))
        stripped = CELL_RE.sub("", line)
        assert stripped == "", f"line is not a pure sequence of cells: {line!r}"
        cells.append([m.group(0) for m in found])
    return cells


def cell_rgb(cell):
    """(fg_rgb, bg_rgb) of one escape-macro cell; values pinned to 0..255."""
    m = CELL_RE.fullmatch(cell)
    assert m is not None, f"cell is not the escape-macro: {cell!r}"
    fg = tuple(int(m.group(i)) for i in (1, 2, 3))
    bg = tuple(int(m.group(i)) for i in (4, 5, 6))
    for v in fg + bg:
        assert 0 <= v <= 255
    return fg, bg


# ---------------------------------------------------------------- 1. frame shape

def test_constants_pinned():
    assert tr.HALF_BLOCK == "▀"  # U+2580
    assert tr.ANSI_RESET == "\x1b[0m"


def test_empty_board_frame_shape_and_reset():
    board = empty_board(4, 4)
    frame = tr.render_board(board)
    lines = frame.split("\n")
    # content lines = height // 2, plus the top and bottom border lines
    assert len(lines) == 4 // 2 + 2
    assert tr.ANSI_RESET in frame
    # every line is a pure sequence of valid cells: width + 2 border cells
    cells = frame_cells(frame)
    assert [len(row) for row in cells] == [6, 6, 6, 6]


# ---------------------------------------------------------------- 2. even height

def test_odd_height_raises_value_error():
    with pytest.raises(ValueError):
        tr.render_board(empty_board(4, 3))
    with pytest.raises(ValueError):
        tr.render_board(empty_board(1, 1))


# ---------------------------------------------------------------- 3. escape-macro

def test_every_cell_parses_as_escape_macro():
    board = [[1, 0, 2, 0], [0, 3, 0, 4], [5, 0, 6, 0], [0, 7, 0, 1]]
    frame = tr.render_board(board, active=(((2,), (2, 2, 2)), 0, 2))
    cells = frame_cells(frame)  # asserts: every line is pure valid cells
    for line in cells:
        for cell in line:
            cell_rgb(cell)  # regex-parses, r/g/b in 0..255


# ---------------------------------------------------------------- 4. color mapping

def test_cell_colors_follow_board_ids():
    board = [[2, 0], [0, 5]]
    frame = tr.render_board(board)
    cells = frame_cells(frame)
    # content line 1 = board rows 0 (fg) / 1 (bg); cell col = board col + 1
    fg, bg = cell_rgb(cells[1][1])
    assert fg == tr.PIECE_COLORS[2]  # board (0, 0) = id 2 -> top half
    assert bg == tr.EMPTY_COLOR  # board (1, 0) = 0
    fg, bg = cell_rgb(cells[1][2])
    assert fg == tr.EMPTY_COLOR  # board (0, 1) = 0
    assert bg == tr.PIECE_COLORS[5]  # board (1, 1) = id 5 -> bottom half
    # border cells use BORDER_COLOR on both halves
    fg, bg = cell_rgb(cells[0][0])
    assert fg == tr.BORDER_COLOR and bg == tr.BORDER_COLOR


def test_piece_colors_are_seven_distinct_rgb():
    assert set(tr.PIECE_COLORS) == {1, 2, 3, 4, 5, 6, 7}
    colors = list(tr.PIECE_COLORS.values())
    assert len(set(colors)) == 7, "seven distinct colors required"
    for c in colors:
        assert isinstance(c, tuple) and len(c) == 3
        assert all(isinstance(v, int) and 0 <= v <= 255 for v in c)
    assert all(isinstance(c, tuple) and len(c) == 3 for c in (tr.EMPTY_COLOR, tr.BORDER_COLOR))
    assert tr.EMPTY_COLOR != tr.BORDER_COLOR
    assert tr.EMPTY_COLOR not in colors
    assert tr.BORDER_COLOR not in colors


# ---------------------------------------------------------------- 5. active overlay

def test_active_overlay_uses_piece_color_and_board_is_untouched():
    board = empty_board(4, 4)
    board[0][2] = 7  # locked cell the overlay must paint over
    snapshot = copy.deepcopy(board)
    t_shape = ((0, 3, 0), (3, 3, 3))  # matrix cells carry the piece id
    frame = tr.render_board(board, active=(t_shape, 1, 0))
    cells = frame_cells(frame)
    # content line 1 = board rows 0 (fg) / 1 (bg); cell col = board col + 1
    fg_top, _ = cell_rgb(cells[1][3])  # board (0, 2): overlay paints over id 7
    assert fg_top == tr.PIECE_COLORS[3]
    for x in (1, 2, 3):  # the shape's bottom row, board cols 1..3
        _, bg = cell_rgb(cells[1][x + 1])
        assert bg == tr.PIECE_COLORS[3]
    # a cell the overlay does not touch keeps the board's own color
    fg, _ = cell_rgb(cells[1][1])  # board (0, 1): empty
    assert fg == tr.EMPTY_COLOR
    assert board == snapshot  # render_board is pure: input board unchanged


def test_active_overlay_out_of_bounds_is_clipped():
    board = empty_board(4, 4)
    frame = tr.render_board(board, active=(((4, 4),), -1, 0))  # left cell off-board
    cells = frame_cells(frame)
    fg, _ = cell_rgb(cells[1][1])  # board col 0 drawn
    assert fg == tr.PIECE_COLORS[4]
    fg, _ = cell_rgb(cells[1][2])  # board col 1: the off-board cell clipped
    assert fg == tr.EMPTY_COLOR


# ---------------------------------------------------------------- 6. no engine import

def test_render_never_imports_tetris_engine():
    importlib.import_module("src.tetris_render")
    importlib.import_module("tetris_render")
    assert "tetris_engine" not in sys.modules
    assert "src.tetris_engine" not in sys.modules


# ---------------------------------------------------------------- 7. render_cell

def test_render_cell_exact_escape_macro():
    cell = tr.render_cell((10, 20, 30), (40, 50, 60))
    assert cell == "\x1b[38;2;10;20;30m\x1b[48;2;40;50;60m▀\x1b[0m"
    assert cell_rgb(cell) == ((10, 20, 30), (40, 50, 60))
