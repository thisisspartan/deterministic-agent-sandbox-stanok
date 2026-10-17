"""tetris_render — half-block truecolor console renderer (CC-283).

Pure functions: board state -> frame string. No I/O, no global mutable
state, and NO import of src/tetris_engine — the board is duck-typed
(list[list[int]]: 0 empty, 1..7 locked piece id).

Board rows come in pairs: each pair of board rows becomes ONE terminal
line drawn with the upper-half block glyph "▀" — fg color = the color of
the top board row, bg color = the color of the bottom board row.

Contract documentation: docs/tetris_render.md.
"""
from __future__ import annotations

HALF_BLOCK = "▀"  # U+2580 UPPER HALF BLOCK
ANSI_SGR_FG = "\x1b[38;2;{r};{g};{b}m"  # truecolor foreground prefix
ANSI_SGR_BG = "\x1b[48;2;{r};{g};{b}m"  # truecolor background prefix
ANSI_RESET = "\x1b[0m"

# Standard Tetris piece colors: seven distinct RGB tuples, keyed by piece id.
PIECE_COLORS = {
    1: (0, 240, 240),  # I — cyan
    2: (240, 240, 0),  # O — yellow
    3: (168, 0, 240),  # T — purple
    4: (0, 240, 0),    # S — green
    5: (240, 0, 0),    # Z — red
    6: (0, 96, 240),   # J — blue
    7: (240, 144, 0),  # L — orange
}
EMPTY_COLOR = (24, 24, 24)  # dark gray
BORDER_COLOR = (112, 112, 128)  # frame: distinct from every cell color


def _check_color(color):
    try:
        r, g, b = color
    except (TypeError, ValueError):
        raise ValueError(f"color must be an (r, g, b) tuple: {color!r}") from None
    for v in (r, g, b):
        if not isinstance(v, int) or not 0 <= v <= 255:
            raise ValueError(f"color components must be ints in 0..255: {color!r}")
    return r, g, b


def _cell_color(value):
    """Color of one board cell: 0 -> EMPTY_COLOR, piece id -> PIECE_COLORS."""
    if value == 0:
        return EMPTY_COLOR
    try:
        return PIECE_COLORS[value]
    except KeyError:
        raise ValueError(f"invalid cell value (must be 0 or a piece id 1..7): {value!r}") from None


def render_cell(top_color, bottom_color) -> str:
    """One half-block cell: fg -> bg -> glyph -> reset."""
    r, g, b = _check_color(top_color)
    fg = ANSI_SGR_FG.format(r=r, g=g, b=b)
    r, g, b = _check_color(bottom_color)
    bg = ANSI_SGR_BG.format(r=r, g=g, b=b)
    return f"{fg}{bg}{HALF_BLOCK}{ANSI_RESET}"


def render_board(board, active=None) -> str:
    """Board state -> frame string (lines joined by "\\n").

    board:  list[list[int]], even height, rectangular rows.
    active: None, or (shape_matrix, x, y) — an overlay painted over the
            board; matrix cells are 0 or a piece id, drawn in that piece's
            color; out-of-bounds cells are clipped. The inputs are never
            mutated.
    """
    height = len(board)
    if height % 2 != 0:
        raise ValueError(f"board height must be even (got {height})")
    width = len(board[0]) if height else 0
    for row in board:
        if len(row) != width:
            raise ValueError("board rows must all have the same length")

    colors = [[_cell_color(board[y][x]) for x in range(width)] for y in range(height)]

    if active is not None:
        matrix, x, y = active
        for r, row in enumerate(matrix):
            for c, value in enumerate(row):
                if not value:
                    continue
                by, bx = y + r, x + c
                if 0 <= by < height and 0 <= bx < width:
                    colors[by][bx] = _cell_color(value)

    border = render_cell(BORDER_COLOR, BORDER_COLOR)
    lines = [border * (width + 2)]
    for top in range(0, height, 2):
        cells = [border]
        for x in range(width):
            cells.append(render_cell(colors[top][x], colors[top + 1][x]))
        cells.append(border)
        lines.append("".join(cells))
    lines.append(border * (width + 2))
    return "\n".join(lines)
