"""tetris_render — pure renderer: board -> ANSI half-block truecolor frame (CC-303).

stdlib only, no imports at all; the engine module is NOT imported (not even by
name) — the board is read duck-typed as list[list[int]] (0 empty, 1..7 piece
id). render_board(board, active=None) returns exactly `len(board) // 2 + 2`
lines joined by "\\n" with no trailing newline: a top border, len(board)/2
half-block rows (fg = board row 2i, bg = board row 2i+1), a bottom border.
Pure: neither the board nor the active tuple is mutated; identical input gives
byte-identical output. See docs/tetris_render.md.
"""

# Palette (R4): hex literals whose decimal channels are the pinned RGBs.
PIECE_COLORS = {
    1: (0, 255, 255),    # I #00ffff
    2: (255, 255, 0),    # O #ffff00
    3: (160, 0, 255),    # T #a000ff
    4: (0, 255, 0),      # S #00ff00
    5: (255, 0, 0),      # Z #ff0000
    6: (0, 120, 255),    # J #0078ff
    7: (255, 120, 0),    # L #ff7800
}
EMPTY_RGB = (20, 20, 20)     # empty cell, both halves
BORDER_RGB = (120, 120, 120)  # frame border rows

_GLYPH = "▀"  # ▀ U+2580: upper half of the cell is fg, lower half is bg
_RESET = "\x1b[0m"


def _sgr(code, color) -> str:
    return f"\x1b[{code};2;{color[0]};{color[1]};{color[2]}m"


def _segment(fg, bg) -> str:
    """One half-block cell: fg SGR (38;2), bg SGR (48;2), then the glyph."""
    return _sgr(38, fg) + _sgr(48, bg) + _GLYPH


def _cell_color(value) -> tuple:
    return EMPTY_RGB if value == 0 else PIECE_COLORS[value]


def _measure(board):
    """(height, width) of a valid board; ValueError for any malformed one (R2)."""
    height = len(board)
    if height == 0:
        raise ValueError("board must have at least one row, got an empty board")
    if height % 2:
        raise ValueError(f"board height must be even, got {height}")
    width = len(board[0])
    if width == 0:
        raise ValueError("board rows must have at least one cell, got width 0")
    for r, row in enumerate(board):
        if len(row) != width:
            raise ValueError(
                f"board rows must all be the same length: row 0 has {width} "
                f"cells, row {r} has {len(row)}"
            )
        for c, value in enumerate(row):
            if not isinstance(value, int) or not 0 <= value <= 7:
                raise ValueError(
                    f"cell values must be ints in 0..7: board[{r}][{c}] = "
                    f"{value!r}"
                )
    return height, width


def _overlay(board, height, width, active):
    """A private copy of the board with the active piece painted on it (R1).

    The color comes from piece_id, never from the shape's own cell values;
    shape cells landing outside the board are clipped, not an error.
    """
    eff = [list(row) for row in board]
    if active is None:
        return eff
    shape, x, y, piece_id = active
    if not isinstance(piece_id, int) or piece_id not in PIECE_COLORS:
        raise ValueError(
            f"active piece_id must be an int in 1..7, got {piece_id!r}"
        )
    for r, row in enumerate(shape):
        for c, value in enumerate(row):
            if not value:
                continue
            yy, xx = y + r, x + c
            if 0 <= yy < height and 0 <= xx < width:
                eff[yy][xx] = piece_id
    return eff


def _line(top, bottom, width) -> str:
    return "".join(_segment(_cell_color(top[c]), _cell_color(bottom[c]))
                   for c in range(width)) + _RESET


def _border_line(width) -> str:
    """fg == bg == border color on every cell: a solid line."""
    return _segment(BORDER_RGB, BORDER_RGB) * width + _RESET


def render_board(board, active=None) -> str:
    """Render the board as one half-block truecolor frame (docs/tetris_render.md).

    board: list[list[int]], even height, equal row lengths, values 0..7.
    active: None, or (shape_matrix, x, y, piece_id) overlaid on the board.
    Malformed input -> ValueError. The inputs are never mutated.
    """
    height, width = _measure(board)
    eff = _overlay(board, height, width, active)
    border = _border_line(width)
    lines = [border]
    for i in range(height // 2):
        lines.append(_line(eff[2 * i], eff[2 * i + 1], width))
    lines.append(border)
    return "\n".join(lines)
