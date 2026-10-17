"""CC-278 — contract tests for src/tetris_render.py.

Half-block truecolor console renderer: board state -> frame string.
Fixtures are defined in this file (no conftest.py, per project rules).
The tests do not import src/tetris_engine.
"""

import copy
import re
import sys
from pathlib import Path

import pytest

import tetris_render as tr

# ---------------------------------------------------------------- helpers

# Escape-maket of one half-block cell: fg -> bg -> glyph -> reset
# (fg = color of the upper board row, bg = color of the lower board row).
_CELL_PATTERN = (
    r"\x1b\[38;2;(\d{1,3});(\d{1,3});(\d{1,3})m"
    r"\x1b\[48;2;(\d{1,3});(\d{1,3});(\d{1,3})m"
    r"▀\x1b\[0m"
)
CELL_RE = re.compile(_CELL_PATTERN)
ROW_RE = re.compile("(?:" + _CELL_PATTERN + ")+")


def frame_rows(frame):
    return frame.split("\n")


def content_rows(frame, height):
    """The height//2 content rows, i.e. everything between the border rows."""
    rows = frame_rows(frame)
    return rows[1 : 1 + height // 2]


def parse_cells(row):
    """Split one frame row into its cells; the row must be exactly a
    sequence of half-block cells. Returns (tr,tg,tb,br,bg,bb) int tuples."""
    assert ROW_RE.fullmatch(row) is not None, f"row is not a cell sequence: {row!r}"
    return [tuple(int(v) for v in m.groups()) for m in CELL_RE.finditer(row)]


def empty_board(width, height):
    return [[0] * width for _ in range(height)]


# ---------------------------------------------------------------- 0. constants

def test_constants_pinned():
    assert tr.HALF_BLOCK == "▀"  # U+2580
    assert tr.ANSI_RESET == "\x1b[0m"


# ---------------------------------------------------------------- 1. empty board frame

def test_empty_board_frame_shape_and_reset():
    board = empty_board(4, 4)
    frame = tr.render_board(board)
    rows = frame_rows(frame)
    # content rows = height // 2, plus the top and bottom border rows
    assert len(rows) == 4 // 2 + 2
    assert tr.ANSI_RESET in frame
    assert tr.HALF_BLOCK in frame
    # every row (borders included) is exactly width + 2 cells
    for row in rows:
        assert len(parse_cells(row)) == 4 + 2


# ---------------------------------------------------------------- 2. odd height

def test_odd_height_raises_value_error():
    board = empty_board(4, 3)
    with pytest.raises(ValueError):
        tr.render_board(board)
    board = empty_board(4, 21)
    with pytest.raises(ValueError):
        tr.render_board(board)


# ---------------------------------------------------------------- 3. every cell parses

def test_every_cell_parses_as_escape_maket():
    board = empty_board(6, 6)
    board[0][0] = 1
    board[3][5] = 7
    frame = tr.render_board(board, active=([[2, 2]], 4, 5))
    for row in frame_rows(frame):
        assert ROW_RE.fullmatch(row) is not None
        for cell in parse_cells(row):
            assert len(cell) == 6
            for v in cell:
                assert 0 <= v <= 255


# ---------------------------------------------------------------- 4. cell colors

def test_cell_color_follows_piece_id_or_empty():
    for pid in range(1, 8):
        board = empty_board(4, 4)
        board[0][0] = pid  # upper half of content row 0, col 0
        board[1][2] = pid  # lower half of content row 0, col 2
        frame = tr.render_board(board)
        top = parse_cells(content_rows(frame, 4)[0])
        color = tuple(tr.PIECE_COLORS[pid])
        empty = tuple(tr.EMPTY_COLOR)
        # cell (row 0, col 0): fg = piece color, bg = empty
        assert top[1][:3] == color
        assert top[1][3:] == empty
        # cell (row 0, col 2): fg = empty, bg = piece color
        assert top[3][:3] == empty
        assert top[3][3:] == color
        # a fully empty cell: both halves EMPTY_COLOR
        assert top[2] == empty + empty


def test_border_cells_use_border_color():
    board = empty_board(4, 4)
    frame = tr.render_board(board)
    rows = frame_rows(frame)
    border = tuple(tr.BORDER_COLOR)
    for row in rows:
        cells = parse_cells(row)
        assert cells[0] == border + border
        assert cells[-1] == border + border
    # the top and bottom border rows are all-border cells
    for edge in (rows[0], rows[-1]):
        assert all(c == border + border for c in parse_cells(edge))


# ---------------------------------------------------------------- 5. PIECE_COLORS

def test_piece_colors_are_seven_distinct_rgb():
    assert set(tr.PIECE_COLORS) == {1, 2, 3, 4, 5, 6, 7}
    colors = [tr.PIECE_COLORS[pid] for pid in range(1, 8)]
    for c in colors:
        assert isinstance(c, tuple) and len(c) == 3
        assert all(isinstance(v, int) and 0 <= v <= 255 for v in c)
    assert len(set(colors)) == 7, "the seven piece colors must be distinct"
    assert tr.EMPTY_COLOR not in colors
    assert tr.BORDER_COLOR not in colors
    assert tr.BORDER_COLOR != tr.EMPTY_COLOR


# ---------------------------------------------------------------- 6. active overlay

def test_active_overlay_drawn_in_own_color():
    board = empty_board(4, 4)
    board[0][0] = 4  # a locked cell that must stay visible
    snap = copy.deepcopy(board)
    # matrix cells carry the piece id (3); the cell at (x=4, y=3) falls
    # outside the board and must be clipped, not crash
    matrix = [[3, 3, 0], [0, 3, 3]]
    frame = tr.render_board(board, active=(matrix, 2, 2))

    assert board == snap  # purity: the board is not mutated

    rows = content_rows(frame, 4)
    row0 = parse_cells(rows[0])  # board rows 0-1
    row1 = parse_cells(rows[1])  # board rows 2-3
    color = tuple(tr.PIECE_COLORS[3])
    empty = tuple(tr.EMPTY_COLOR)

    # the locked cell (0, 0) is still rendered with its own color
    assert row0[1][:3] == tuple(tr.PIECE_COLORS[4])
    # overlay cells (2, 2) and (2, 3): fg = piece color
    assert row1[3][:3] == color and row1[3][3:] == empty
    assert row1[4][:3] == color and row1[4][3:] == color
    # overlay cell (3, 3): bg = piece color; (3, 4) clipped without effect
    assert row1[4][3:] == color


def test_active_none_and_overlay_do_not_change_board_render():
    board = empty_board(4, 4)
    assert tr.render_board(board, active=None) == tr.render_board(board)


# ---------------------------------------------------------------- 7. no engine import

def test_module_does_not_import_tetris_engine():
    repo_root = str(Path(__file__).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    sys.modules.pop("src.tetris_render", None)
    sys.modules.pop("src.tetris_engine", None)
    sys.modules.pop("tetris_engine", None)
    import src.tetris_render  # noqa: F401  (fresh import of the module under test)
    assert "src.tetris_engine" not in sys.modules
    assert "tetris_engine" not in sys.modules


# ---------------------------------------------------------------- 8. render_cell maket

def test_render_cell_exact_escape_maket():
    cell = tr.render_cell((10, 20, 30), (40, 50, 60))
    assert cell == "\x1b[38;2;10;20;30m\x1b[48;2;40;50;60m▀\x1b[0m"
    assert CELL_RE.fullmatch(cell) is not None
    # fg == bg degenerates to a solid-colored cell
    solid = tr.render_cell((1, 2, 3), (1, 2, 3))
    assert solid == "\x1b[38;2;1;2;3m\x1b[48;2;1;2;3m▀\x1b[0m"
