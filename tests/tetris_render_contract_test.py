"""Calibrated contract oracle for src/tetris_render.py (SPEC-TETRIS-CONSOLE R1..R5).

Independence policy: RGB/segment literals are transcribed from the SPEC (R3/R4);
expected frames are re-built independently in this file from those constants —
never from the renderer's own output. Mutants RM1..RM6 (see specs/STATUS.md).
GREEN on reference, RED on each targeted mutant.
"""
import ast
import copy
import inspect
import re

import pytest

try:
    from src import tetris_render as rend
except ImportError:
    import tetris_render as rend

RESET = "\x1b[0m"
BORDER_RGB = (120, 120, 120)
EMPTY_RGB = (20, 20, 20)
PIECE_COLORS = {
    1: (0, 255, 255), 2: (255, 255, 0), 3: (160, 0, 255), 4: (0, 255, 0),
    5: (255, 0, 0), 6: (0, 120, 255), 7: (255, 120, 0),
}
GLYPH = "▀"

SEG_RE = re.compile(
    r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m" + GLYPH)
LINE_RE = re.compile(r"(?:\x1b\[38;2;\d+;\d+;\d+m\x1b\[48;2;\d+;\d+;\d+m"
                     + GLYPH + r")+\x1b\[0m")


def _seg(fg, bg):
    return (f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m"
            f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m{GLYPH}")


def _color(v):
    return EMPTY_RGB if v == 0 else PIECE_COLORS[v]


def _expected_frame(board, active=None):
    """Independent frame builder from the SPEC pins (R2..R4)."""
    h, w = len(board), len(board[0])
    eff = [[v for v in row] for row in board]
    if active is not None:
        shape, x, y, pid = active
        for r, row in enumerate(shape):
            for c, v in enumerate(row):
                if v:
                    yy, xx = y + r, x + c
                    if 0 <= yy < h and 0 <= xx < w:
                        eff[yy][xx] = pid
    border = _seg(BORDER_RGB, BORDER_RGB) * w + RESET
    lines = [border]
    for t in range(h // 2):
        top, bottom = eff[2 * t], eff[2 * t + 1]
        lines.append("".join(_seg(_color(top[c]), _color(bottom[c]))
                             for c in range(w)) + RESET)
    lines.append(border)
    return "\n".join(lines)


def _empty_board(w, h):
    return [[0] * w for _ in range(h)]


def _segments(line):
    return [tuple(map(int, m)) for m in SEG_RE.findall(line)]


# ---- R1: seam — no engine import; active is a 4-tuple ---------------------------

def test_no_import_of_engine_or_peers():
    tree = ast.parse(inspect.getsource(rend))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
        elif isinstance(node, ast.Import):
            imported.extend(a.name for a in node.names)
    for name in imported:
        for forbidden in ("tetris_engine", "water", "galaxian", "ticketcheck"):
            assert forbidden not in name, f"renderer imports {name}"


# ---- R2/R3: frame geometry and exact segment encoding ----------------------------

def test_frame_exact_for_empty_board():
    board = _empty_board(10, 20)
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    lines = out.split("\n")
    assert len(lines) == 20 // 2 + 2
    assert not out.endswith("\n")
    for ln in lines:
        assert LINE_RE.fullmatch(ln), ln
        assert ln.count(RESET) == 1
    # border rows: fg == bg == border rgb on every cell
    segs = _segments(lines[0])
    assert len(segs) == 10
    for seg in segs:
        assert seg == (120, 120, 120, 120, 120, 120)
    # mid rows: every cell empty color
    segs = _segments(lines[1])
    for seg in segs:
        assert seg == (20, 20, 20, 20, 20, 20)


def test_frame_exact_small_board_and_fg_bg_split():
    board = _empty_board(4, 2)
    board[0] = [1, 2, 0, 0]     # fg of screen row 0
    board[1] = [0, 0, 3, 4]     # bg of screen row 0
    out = rend.render_board(board)
    assert out == _expected_frame(board)
    mid = out.split("\n")[1]
    segs = _segments(mid)
    assert len(segs) == 4
    assert segs[0][:3] == PIECE_COLORS[1] and segs[0][3:] == EMPTY_RGB
    assert segs[1][:3] == PIECE_COLORS[2] and segs[1][3:] == EMPTY_RGB
    assert segs[2][:3] == EMPTY_RGB and segs[2][3:] == PIECE_COLORS[3]
    assert segs[3][:3] == EMPTY_RGB and segs[3][3:] == PIECE_COLORS[4]


def test_all_palette_ids_render_pinned_rgb():
    board = _empty_board(10, 20)
    board[0] = [1, 2, 3, 4, 5, 6, 7, 0, 1, 7]
    board[19] = [7, 6, 5, 4, 3, 2, 1, 0, 0, 0]
    out = rend.render_board(board)
    assert out == _expected_frame(board)


# ---- R1: active overlay — color from piece_id, never from shape cell values ----

def test_active_color_follows_piece_id_not_shape_values():
    board = _empty_board(10, 20)
    # shape cells carry the value 7; the painted color must follow piece_id=3
    active = (((7, 0), (7, 7)), 2, 10, 3)
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    mid = out.split("\n")[6]                      # screen row covering board rows 10,11
    segs = _segments(mid)
    assert segs[2][:3] == PIECE_COLORS[3]        # fg = piece color, not color 7
    assert segs[2][3:] != PIECE_COLORS[7]


def test_active_out_of_bounds_is_clipped_frame_unchanged():
    board = _empty_board(10, 20)
    active = (((1, 1), (1, 1)), 8, 19, 5)        # right half of O hangs off-board
    out = rend.render_board(board, active=active)
    assert out == _expected_frame(board, active=active)
    assert len(out.split("\n")) == 12


def test_active_none_default_renders_board_only():
    board = _empty_board(6, 4)
    board[2] = [1, 0, 0, 0, 0, 2]
    assert rend.render_board(board) == _expected_frame(board)
    assert rend.render_board(board, None) == _expected_frame(board)


# ---- R2: validation negatives ----------------------------------------------------

def test_validation_rejects_bad_inputs():
    with pytest.raises(ValueError):
        rend.render_board([])
    with pytest.raises(ValueError):
        rend.render_board(_empty_board(10, 19))          # odd height
    with pytest.raises(ValueError):
        rend.render_board([[0, 0], [0, 0, 0]])       # ragged
    bad = _empty_board(10, 4)
    bad[1][3] = 8
    with pytest.raises(ValueError):
        rend.render_board(bad)
    bad2 = _empty_board(10, 4)
    bad2[0][0] = -1
    with pytest.raises(ValueError):
        rend.render_board(bad2)
    bad3 = _empty_board(10, 4)
    bad3[0][0] = "1"
    with pytest.raises(ValueError):
        rend.render_board(bad3)
    with pytest.raises(ValueError):
        rend.render_board(_empty_board(10, 4), active=(((1,),), 0, 0, 0))
    with pytest.raises(ValueError):
        rend.render_board(_empty_board(10, 4), active=(((1,),), 0, 0, 8))


# ---- R5: no cursor/erase controls in a frame; purity -----------------------------

def test_frame_contains_no_cursor_or_erase_sequences():
    board = _empty_board(10, 20)
    board[0][0] = 1
    out = rend.render_board(board, active=(((1, 1),), 0, 0, 1))
    for seq in ("\x1b[H", "\x1b[2J", "\x1b[?25", "\x1b[?25l", "\x1b[?25h"):
        assert seq not in out, seq


def test_purity_no_mutation_no_aliasing():
    board = _empty_board(10, 20)
    board[3] = [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]
    shape = ((1, 0), (1, 1))
    before_board = copy.deepcopy(board)
    before_shape = copy.deepcopy(shape)
    out1 = rend.render_board(board, active=(shape, 4, 9, 4))
    out2 = rend.render_board(board, active=(shape, 4, 9, 4))
    assert out1 == out2 == _expected_frame(board, active=(shape, 4, 9, 4))
    assert board == before_board
    assert shape == before_shape
    assert isinstance(out1, str)
