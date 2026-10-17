# tetris_render — module contract (CC-283)

Half-block truecolor console renderer: pure functions, board state ->
frame string. No I/O, no global mutable state. The module does **not**
import `src/tetris_engine` — the board is duck-typed:
`list[list[int]]`, 0 empty, 1..7 locked piece id.

## Half-block model

Board rows come in pairs; each pair of board rows becomes ONE terminal
line. The glyph `▀` (U+2580) draws its upper half in the foreground
color and its lower half in the background color, so:
fg = color of the top board row, bg = color of the bottom board row.
Board height must therefore be **even** (odd height -> `ValueError`).

## Constants (pinned)

- `HALF_BLOCK = "▀"` (U+2580).
- `ANSI_SGR_FG = "\x1b[38;2;{r};{g};{b}m"`, `ANSI_SGR_BG = "\x1b[48;2;{r};{g};{b}m"` —
  truecolor SGR prefixes; `ANSI_RESET = "\x1b[0m"`.
- `PIECE_COLORS: dict[int, tuple]` — ids 1..7 -> seven **distinct**
  RGB tuples (components 0..255): 1 I cyan, 2 O yellow, 3 T purple,
  4 S green, 5 Z red, 6 J blue, 7 L orange.
- `EMPTY_COLOR = (24, 24, 24)` — dark gray; `BORDER_COLOR` — the frame
  color, distinct from every piece color and from `EMPTY_COLOR`.

## Functions

- `render_cell(top_color, bottom_color) -> str` — one half-block cell,
  exact escape-macro: `fg -> bg -> glyph -> reset`, i.e.
  `\x1b[38;2;r;g;bm\x1b[48;2;r;g;bm▀\x1b[0m`. Colors are `(r, g, b)`
  tuples of ints 0..255; anything else raises `ValueError`.
- `render_board(board, active=None) -> str` — frame string, lines joined
  by `"\n"`:
  - `board`: rectangular `list[list[int]]` with **even** height (odd
    height or ragged rows -> `ValueError`; a cell value outside
    `0`/`1..7` -> `ValueError`).
  - `active`: `None`, or `(shape_matrix, x, y)` — an overlay painted
    over the board. `shape_matrix` is a matrix of tuples; cells are 0
    (skip) or a **piece id 1..7**, drawn in `PIECE_COLORS[id]` (so the
    renderer needs no engine knowledge). `x`/`y` are the board column/row
    of the matrix top-left cell; out-of-bounds cells are clipped.
  - Frame: a border of `BORDER_COLOR` cells around the whole perimeter
    (top/bottom lines of `width + 2` cells; each content line is
    border + `width` cells + border). Total lines = `height // 2 + 2`.
  - Every cell of the frame — content and border — is a complete
    escape-macro ending with `ANSI_RESET`.

## Invariants

- Pure: `render_board` never mutates `board` or the active matrix; it
  renders from a private color grid.
- A board cell 0 renders `EMPTY_COLOR` on its half; a cell with id k
  renders `PIECE_COLORS[k]`; the active overlay paints over locked cells.
- Importing `src.tetris_render` never puts `tetris_engine` or
  `src.tetris_engine` into `sys.modules`.

Tests: `tests/tetris_render_test.py` (`bash scripts/run.sh test
tests/tetris_render_test.py`).
