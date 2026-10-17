# tetris_render — module contract (CC-278)

A pure half-block truecolor console renderer: board state → frame string.
No I/O, no global mutable state; the input board is never mutated. The module
does **not** import `src/tetris_engine` — duck typing: `board = list[list[int]]`,
`0` empty, locked piece id `1..7`. Tests: `tests/tetris_render_test.py`.

## Constants (pinned)

| Name | Value |
|---|---|
| `HALF_BLOCK` | `"▀"` (U+2580 UPPER HALF BLOCK: fg paints the top half, bg the bottom) |
| `ANSI_FG` / `ANSI_BG` | `"\x1b[38;2;{r};{g};{b}m"` / `"\x1b[48;2;{r};{g};{b}m"` — SGR truecolor prefixes |
| `ANSI_RESET` | `"\x1b[0m"` |
| `PIECE_COLORS` | `dict` id `1..7 = I,O,T,S,Z,J,L` → seven **distinct** `(r,g,b)` tuples, components `0..255` |
| `EMPTY_COLOR` | `(24, 24, 24)` — dark gray, empty cell |
| `BORDER_COLOR` | `(136, 136, 136)` — field border, distinct from every piece color and `EMPTY_COLOR` |

## Functions

- `render_cell(top_color, bottom_color) -> str`
  One half-block cell in the escape-maket `fg → bg → glyph → ANSI_RESET`:
  `"\x1b[38;2;tr;tg;tbm" + "\x1b[48;2;br;bg;bbm" + "▀" + "\x1b[0m"`.

- `render_board(board, active=None) -> str`
  Render the board state as a terminal frame string.

  - `board`: `height` rows × `width` cols; `0` empty, `1..7` piece id. The
    height must be a **positive even** number: each pair of board rows becomes
    one terminal row of half-block cells (fg = color of the upper row,
    bg = color of the lower row). Odd (or zero) height → `ValueError`;
    ragged rows → `ValueError`.
  - `active`: `None`, or `(shape_matrix, x, y)` — an overlay of the active
    piece drawn with its own color (matrix cells carry the piece id, same
    encoding as board cells); `x`, `y` is the top-left corner of the matrix
    on the board; cells falling outside the field are clipped. The board is
    not mutated (the overlay is applied to a copy).

  Frame layout: a border of `BORDER_COLOR` cells on all four sides
  (`width + 2` cells per row; content rows carry a border cell at each end),
  `height // 2` content rows between them; rows separated by `"\n"`; every
  colored cell ends with `ANSI_RESET`. Total rows: `height // 2 + 2`.

## Purity

`render_board` never mutates `board` or `active`; the overlay is painted into
a private copy. Rendering the same board twice yields the identical string.
