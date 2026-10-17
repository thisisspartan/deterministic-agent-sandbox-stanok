"""CC-278 — tetris_render: a pure half-block truecolor console renderer.

Board state -> frame string. No I/O, no global mutable state; the input
board is never mutated. The module does NOT import src/tetris_engine —
duck typing: board = list[list[int]], 0 empty, piece id 1..7.

Module contract: see docs/tetris_render.md.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence, Tuple

Color = Tuple[int, int, int]
Board = Sequence[Sequence[int]]
Active = Tuple[Sequence[Sequence[int]], int, int]

# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------

HALF_BLOCK = "▀"  # U+2580 UPPER HALF BLOCK: fg paints the top half, bg the bottom

ANSI_FG = "\x1b[38;2;{r};{g};{b}m"  # SGR truecolor foreground prefix
ANSI_BG = "\x1b[48;2;{r};{g};{b}m"  # SGR truecolor background prefix
ANSI_RESET = "\x1b[0m"

# id 1..7 = I,O,T,S,Z,J,L -> seven distinct truecolor RGB tuples (0..255).
PIECE_COLORS: Dict[int, Color] = {
    1: (0, 255, 255),    # I — cyan
    2: (255, 255, 0),    # O — yellow
    3: (160, 32, 240),   # T — purple
    4: (0, 255, 0),      # S — green
    5: (255, 0, 0),      # Z — red
    6: (0, 0, 255),      # J — blue
    7: (255, 165, 0),    # L — orange
}

EMPTY_COLOR: Color = (24, 24, 24)      # dark gray — empty cell
BORDER_COLOR: Color = (136, 136, 136)  # field border — distinct from every other color


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _fg(color: Color) -> str:
    r, g, b = color
    return ANSI_FG.format(r=r, g=g, b=b)


def _bg(color: Color) -> str:
    r, g, b = color
    return ANSI_BG.format(r=r, g=g, b=b)


def _color_of(value: int) -> Color:
    """Board/matrix cell value -> its color (0 = empty, 1..7 = piece color)."""
    if value == 0:
        return EMPTY_COLOR
    return PIECE_COLORS[value]


def _overlay(board: Board, active: Optional[Active]) -> Board:
    """A copy of the board with the active piece painted in; cells falling
    outside the field are clipped. The input board is never mutated."""
    if active is None:
        return board
    matrix, x, y = active
    grid = [list(row) for row in board]
    for r, row in enumerate(matrix):
        for c, v in enumerate(row):
            if not v:
                continue
            by, bx = y + r, x + c
            if 0 <= by < len(grid) and 0 <= bx < len(grid[by]):
                grid[by][bx] = v
    return grid


# ---------------------------------------------------------------------------
# Public API (pure functions)
# ---------------------------------------------------------------------------

def render_cell(top_color: Color, bottom_color: Color) -> str:
    """One half-block cell: fg -> bg -> glyph -> ANSI_RESET."""
    return _fg(top_color) + _bg(bottom_color) + HALF_BLOCK + ANSI_RESET


def render_board(board: Board, active: Optional[Active] = None) -> str:
    """Render the board state as a terminal frame string.

    board:  list[list[int]], height rows x width cols; 0 empty, 1..7 piece id.
            The height must be a positive EVEN number: each pair of board rows
            becomes one terminal row via half-block cells (fg = color of the
            upper row, bg = color of the lower row). Odd height -> ValueError.
    active: None, or (shape_matrix, x, y) — an overlay of the active piece
            drawn with its own color (matrix cells carry the piece id);
            cells outside the field are clipped. The board is not mutated.

    The frame is bordered on all sides (border cells use BORDER_COLOR),
    rows are separated by "\\n", and every colored cell ends with ANSI_RESET.
    """
    height = len(board)
    if height == 0 or height % 2 != 0:
        raise ValueError("board height must be a positive even number")
    width = len(board[0])
    if any(len(row) != width for row in board):
        raise ValueError("board rows must all have the same width")

    grid = _overlay(board, active)
    border_cell = render_cell(BORDER_COLOR, BORDER_COLOR)

    lines = [border_cell * (width + 2)]
    for top in range(0, height, 2):
        cells = [border_cell]
        for x in range(width):
            cells.append(
                render_cell(_color_of(grid[top][x]), _color_of(grid[top + 1][x]))
            )
        cells.append(border_cell)
        lines.append("".join(cells))
    lines.append(border_cell * (width + 2))
    return "\n".join(lines)
