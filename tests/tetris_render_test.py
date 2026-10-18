"""CC-291 — tetris_render reference tests: the pinned contract of the pure
board → ANSI half-block frame renderer.

Every test below pins one clause of the ticket contract (docs/tetris_render.md):
frame shape and line count, exact segment bytes, half pairing (fg = upper
board row, bg = lower), the pinned palette, border rows, the active-piece
overlay (clipped to the board, board never mutated), absence of home/clear/
cursor sequences, input validation, determinism, purity, and stdlib-only
imports. No TTY, no subprocess.
"""

import ast
import copy
import importlib
import inspect
import re
import sys

import pytest

import tetris_render as tr


# ---------------------------------------------------------------------------
# palette pinned by the contract (RGB) — the test is the reference
# ---------------------------------------------------------------------------

EMPTY_RGB = (20, 20, 20)
BORDER_RGB = (120, 120, 120)
PALETTE = {
    1: (0, 255, 255),    # I
    2: (255, 255, 0),    # O
    3: (160, 0, 255),    # T
    4: (0, 255, 0),      # S
    5: (255, 0, 0),      # Z
    6: (0, 120, 255),    # J
    7: (255, 120, 0),    # L
}

RESET = "\x1b[0m"
SEGMENT_RE = re.compile(
    "\x1b\\[38;2;(\\d+);(\\d+);(\\d+)m"
    "\x1b\\[48;2;(\\d+);(\\d+);(\\d+)m"
    "\u2580"
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _board(rows, cols, fill=0):
    return [[fill] * cols for _ in range(rows)]


def _parse_line(line, width):
    """Parse one frame line into exactly `width` (fg, bg) pairs followed by
    the reset sequence and nothing else; assert the exact structure."""
    segs = []
    pos = 0
    for _ in range(width):
        m = SEGMENT_RE.match(line, pos)
        assert m is not None, f"not a segment at offset {pos}: {line!r}"
        g = m.groups()
        segs.append(
            ((int(g[0]), int(g[1]), int(g[2])), (int(g[3]), int(g[4]), int(g[5])))
        )
        pos = m.end()
    assert line[pos:] == RESET, f"line must end with the reset sequence: {line!r}"
    return segs


# ---------------------------------------------------------------------------
# 1. frame shape
# ---------------------------------------------------------------------------

def test_frame_shape_10x4():
    # board 10 rows x 4 cols -> exactly len(board)//2 + 2 = 7 lines joined
    # by "\n", no trailing newline; every line = 4 segments + final reset.
    frame = tr.render_board(_board(10, 4))
    lines = frame.split("\n")
    assert len(lines) == 10 // 2 + 2 == 7
    assert not frame.endswith("\n")
    for line in lines:
        assert len(_parse_line(line, 4)) == 4


# ---------------------------------------------------------------------------
# 2. exact bytes of an empty segment: fg == bg == (20,20,20) + U+2580
# ---------------------------------------------------------------------------

def test_empty_segment_exact_bytes():
    frame = tr.render_board(_board(2, 1))
    lines = frame.split("\n")
    assert len(lines) == 2 // 2 + 2 == 3
    expected = "\x1b[38;2;20;20;20m\x1b[48;2;20;20;20m\u2580" + RESET
    assert lines[1] == expected


# ---------------------------------------------------------------------------
# 3. half pairing: fg = UPPER board row of the pair, bg = LOWER
# ---------------------------------------------------------------------------

def test_half_pairing_fg_upper_bg_lower():
    board = [[1, 1, 1], [2, 2, 2]]
    frame = tr.render_board(board)
    lines = frame.split("\n")
    assert len(lines) == 3
    for fg, bg in _parse_line(lines[1], 3):
        assert fg == (0, 255, 255)  # id 1 — board row 0, upper half
        assert bg == (255, 255, 0)  # id 2 — board row 1, lower half


def test_pairing_across_pairs():
    # frame line i (1-based) encodes board rows 2i-2 (upper) and 2i-1 (lower)
    board = [[0, 0], [1, 0], [2, 0], [3, 3]]
    frame = tr.render_board(board)
    lines = frame.split("\n")
    assert len(lines) == 4 // 2 + 2 == 4
    segs1 = _parse_line(lines[1], 2)  # board rows 0,1
    assert segs1[0] == (EMPTY_RGB, PALETTE[1])
    assert segs1[1] == (EMPTY_RGB, EMPTY_RGB)
    segs2 = _parse_line(lines[2], 2)  # board rows 2,3
    assert segs2[0] == (PALETTE[2], PALETTE[3])
    assert segs2[1] == (EMPTY_RGB, PALETTE[3])


# ---------------------------------------------------------------------------
# 4. palette: each id 1..7 renders exactly its RGB; seven distinct colors
# ---------------------------------------------------------------------------

def test_palette_pinned_per_id():
    for piece_id, rgb in PALETTE.items():
        board = [[piece_id], [0]]
        frame = tr.render_board(board)
        (fg, bg), = _parse_line(frame.split("\n")[1], 1)
        assert fg == rgb
        assert bg == EMPTY_RGB


def test_palette_colors_are_distinct():
    assert len(set(PALETTE.values())) == 7


def test_piece_colors_constant_matches_palette():
    assert tr.PIECE_COLORS == PALETTE


# ---------------------------------------------------------------------------
# 5. borders: line 0 and the last line — all segments fg == bg == (120,120,120)
# ---------------------------------------------------------------------------

def test_border_rows_are_border_color():
    board = _board(4, 3, fill=5)
    frame = tr.render_board(board)
    lines = frame.split("\n")
    for line in (lines[0], lines[-1]):
        segs = _parse_line(line, 3)
        assert len(segs) == 3
        for fg, bg in segs:
            assert fg == BORDER_RGB
            assert bg == BORDER_RGB


# ---------------------------------------------------------------------------
# 6. active figure: overlay paints the piece color, clipped to the board;
#    the board is never mutated (deep check before/after)
# ---------------------------------------------------------------------------

def test_active_overlay_paints_piece_color_board_unchanged():
    board = _board(4, 4)
    shape = [[1, 0], [1, 1]]
    values_before = copy.deepcopy(board)
    frame = tr.render_board(board, active=(shape, 2, 2))
    lines = frame.split("\n")
    segs = _parse_line(lines[2], 4)  # frame line 2 -> board rows 2,3
    # shape cells land on (2,2), (3,2), (3,3); (0,1) of the shape is empty
    assert segs[2] == (PALETTE[1], PALETTE[1])
    assert segs[3] == (EMPTY_RGB, PALETTE[1])
    assert segs[0] == (EMPTY_RGB, EMPTY_RGB)
    assert segs[1] == (EMPTY_RGB, EMPTY_RGB)
    assert board == values_before  # deep value check
    assert shape == [[1, 0], [1, 1]]


def test_active_overlay_clipped_to_board():
    board = _board(2, 2)
    shape = [[4, 4], [4, 4]]
    frame = tr.render_board(board, active=(shape, 1, 1))  # only (1,1) is inside
    lines = frame.split("\n")
    segs = _parse_line(lines[1], 2)
    assert segs[1] == (EMPTY_RGB, PALETTE[4])
    assert segs[0] == (EMPTY_RGB, EMPTY_RGB)


def test_active_overlay_negative_offset_clipped():
    board = _board(2, 2)
    shape = [[6, 6], [6, 6]]
    frame = tr.render_board(board, active=(shape, -1, 0))  # only col 0 lands
    lines = frame.split("\n")
    segs = _parse_line(lines[1], 2)
    assert segs[0] == (PALETTE[6], PALETTE[6])
    assert segs[1] == (EMPTY_RGB, EMPTY_RGB)


def test_active_overlay_overwrites_board_cells():
    board = [[5, 0], [0, 0]]
    frame = tr.render_board(board, active=([[3]], 0, 0))
    lines = frame.split("\n")
    segs = _parse_line(lines[1], 2)
    assert segs[0] == (PALETTE[3], EMPTY_RGB)


# ---------------------------------------------------------------------------
# 7. the frame contains no home/clear/cursor sequences (CLI's job)
# ---------------------------------------------------------------------------

def test_frame_has_no_home_clear_or_cursor():
    board = _board(4, 4, fill=2)
    frame = tr.render_board(board, active=([[1, 1]], 0, 0))
    for forbidden in ("\x1b[H", "\x1b[2J", "\x1b[?25"):
        assert forbidden not in frame


# ---------------------------------------------------------------------------
# 8. validation
# ---------------------------------------------------------------------------

def test_odd_row_count_rejected():
    with pytest.raises(ValueError):
        tr.render_board(_board(3, 4))


def test_empty_board_rejected():
    with pytest.raises(ValueError):
        tr.render_board([])


def test_ragged_rows_rejected():
    with pytest.raises(ValueError):
        tr.render_board([[0, 0], [0, 0, 0]])


def test_out_of_range_values_rejected():
    with pytest.raises(ValueError):
        tr.render_board([[0, 8], [0, 0]])
    with pytest.raises(ValueError):
        tr.render_board([[0, -1], [0, 0]])


def test_zero_width_rows_rejected():
    with pytest.raises(ValueError):
        tr.render_board([[], []])


def test_active_out_of_range_value_rejected():
    with pytest.raises(ValueError):
        tr.render_board(_board(2, 2), active=([[9]], 0, 0))


# ---------------------------------------------------------------------------
# 9. determinism
# ---------------------------------------------------------------------------

def test_identical_input_identical_bytes():
    board = _board(4, 3, fill=4)
    active = ([[2, 2]], 1, 1)
    a = tr.render_board(board, active=active)
    b = tr.render_board(board, active=active)
    assert a == b
    assert a.encode("utf-8") == b.encode("utf-8")


def test_different_boards_do_not_interfere():
    b1 = _board(2, 2, fill=1)
    b2 = _board(2, 2, fill=2)
    f1 = tr.render_board(b1)
    f2 = tr.render_board(b2)
    assert tr.render_board(b1) == f1
    assert f1 != f2


# ---------------------------------------------------------------------------
# 10. purity: no mutation, no shared rows; the engine is not imported
# ---------------------------------------------------------------------------

def test_board_and_shape_not_mutated_rows_not_shared():
    board = _board(4, 4, fill=7)
    rows_before = list(board)  # identity of the caller's row objects
    values_before = copy.deepcopy(board)
    shape = [[1, 1], [1, 1]]
    shape_rows_before = list(shape)
    shape_values_before = copy.deepcopy(shape)

    tr.render_board(board, active=(shape, 0, 0))

    assert board == values_before
    for row, orig in zip(board, rows_before):
        assert row is orig  # same objects, untouched
    assert shape == shape_values_before
    for row, orig in zip(shape, shape_rows_before):
        assert row is orig


def test_import_does_not_pull_tetris_engine():
    # Fresh import of the renderer with both modules absent from sys.modules:
    # if tetris_render imported tetris_engine, the engine would appear here.
    sys.modules.pop("tetris_render", None)
    sys.modules.pop("tetris_engine", None)
    importlib.import_module("tetris_render")
    assert "tetris_engine" not in sys.modules


# ---------------------------------------------------------------------------
# 11. the renderer imports nothing besides the stdlib
# ---------------------------------------------------------------------------

def test_renderer_imports_stdlib_only():
    tree = ast.parse(inspect.getsource(tr))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module is not None:
                imported.add(node.module.split(".")[0])
    assert imported <= sys.stdlib_module_names
