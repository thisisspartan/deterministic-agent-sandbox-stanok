"""tetris_render — pure board → ANSI half-block frame renderer (CC-291).

Pure data transform: no I/O, no time, no network, stdlib only (nothing is
imported beyond `__future__`). It does NOT import tetris_engine — it works
on plain data (list[list[int]]). Purity: the input board and the active
shape are never mutated and no row of theirs is shared with anything the
caller can see; identical input yields byte-identical output. The frame is
a plain string: home/clear/cursor sequences are the CLI's responsibility
(CC-292). The contract is pinned in docs/tetris_render.md.
"""

from __future__ import annotations

# Palette (pinned by the contract, RGB).
EMPTY_COLOR = (20, 20, 20)
BORDER_COLOR = (120, 120, 120)
PIECE_COLORS: dict[int, tuple[int, int, int]] = {
    1: (0, 255, 255),    # I
    2: (255, 255, 0),    # O
    3: (160, 0, 255),    # T
    4: (0, 255, 0),      # S
    5: (255, 0, 0),      # Z
    6: (0, 120, 255),    # J
    7: (255, 120, 0),    # L
}

_RESET = "\x1b[0m"
_HALF_BLOCK = "▀"  # U+2580 upper half block


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _color(cell: int) -> tuple[int, int, int]:
    return EMPTY_COLOR if cell == 0 else PIECE_COLORS[cell]


def _segment(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> str:
    """One cell: fg = upper half color, bg = lower half color."""
    return (
        f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m"
        f"\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"
        f"{_HALF_BLOCK}"
    )


def _validate_matrix(matrix, name: str, *, even_height: bool) -> None:
    """Validate a duck-typed list[list[int]]: non-empty, rows of equal
    length >= 1, values 0..7; for a board also an even number of rows."""
    try:
        rows = len(matrix)
    except TypeError:
        raise ValueError(f"{name} must be a list of rows") from None
    if rows == 0:
        raise ValueError(f"{name} must not be empty")
    if even_height and rows % 2 != 0:
        raise ValueError(f"{name} must have an even number of rows, got {rows}")
    try:
        width = len(matrix[0])
    except TypeError:
        raise ValueError(f"{name} rows must be lists of ints") from None
    if width < 1:
        raise ValueError(f"{name} rows must have length >= 1")
    for y, row in enumerate(matrix):
        try:
            row_len = len(row)
        except TypeError:
            raise ValueError(f"{name}[{y}] must be a list of ints") from None
        if row_len != width:
            raise ValueError(
                f"{name} rows must all have equal length {width}, got {row_len} at row {y}"
            )
        for x, cell in enumerate(row):
            if cell not in range(8):
                raise ValueError(f"{name}[{y}][{x}] must be 0..7, got {cell!r}")


# ---------------------------------------------------------------------------
# public API (name pinned by the contract)
# ---------------------------------------------------------------------------

def render_board(board, active=None) -> str:
    """Render a board (optionally with an active-piece overlay) as an ANSI
    half-block frame: len(board)//2 + 2 lines joined by "\\n", no trailing
    newline. Line 0 and the last line are borders; frame line i (1-based)
    encodes board rows 2i-2 (upper half, fg) and 2i-1 (lower half, bg).
    Each line is exactly len(board[0]) segments plus the final reset.

    board: list[list[int]], even number of rows of equal length >= 1,
    values 0 or 1..7 — otherwise ValueError. active: None or
    (shape_ids, x, y); shape_ids cells are 0 or piece ids 1..7, overlaid
    at offset (x, y), clipped to the board. Neither board nor shape_ids is
    mutated; the frame carries no home/clear/cursor sequences.
    """
    _validate_matrix(board, "board", even_height=True)
    height = len(board)
    width = len(board[0])

    # Working copy: the caller's board is never mutated or shared.
    cells = [row[:] for row in board]

    if active is not None:
        try:
            shape_ids, x, y = active
        except (TypeError, ValueError):
            raise ValueError("active must be (shape_ids, x, y)") from None
        _validate_matrix(shape_ids, "active shape_ids", even_height=False)
        for sy, srow in enumerate(shape_ids):
            for sx, cell in enumerate(srow):
                if cell:
                    by, bx = y + sy, x + sx
                    if 0 <= by < height and 0 <= bx < width:
                        cells[by][bx] = cell

    border = _segment(BORDER_COLOR, BORDER_COLOR) * width + _RESET
    lines = [border]
    for i in range(1, height // 2 + 1):
        upper, lower = cells[2 * i - 2], cells[2 * i - 1]
        lines.append(
            "".join(_segment(_color(upper[c]), _color(lower[c])) for c in range(width))
            + _RESET
        )
    lines.append(border)
    return "\n".join(lines)
