# tetris_render — contract (CC-291)

Pure board → ANSI half-block frame renderer: second layer of the TETRIS3
wave (no CLI yet; the terminal seam is named and closed by CC-292, where a
real PTY checks the boundary). No I/O, no time, no network — stdlib only
(nothing is imported beyond `__future__`). `tetris_engine` is NOT imported:
the module works on plain data (`list[list[int]]`).
Tests: `tests/tetris_render_test.py`.

## Purity

`render_board` never mutates the input `board` or the active `shape_ids`,
shares no row of theirs with anything the caller can see, and identical
input yields byte-identical output.

## Public API

- `render_board(board, active=None) -> str` — the single public function.

### Input

- `board`: duck-typed `list[list[int]]` — an even number of rows
  (`len(board) >= 2`), all rows of equal length `>= 1`, values `0` (empty)
  or piece ids `1..7`. An odd row count, an empty board, ragged rows, a
  zero-length row, or a value outside `0..7` raises `ValueError`.
- `active`: `None` or `(shape_ids, x, y)`. `shape_ids` is a
  `list[list[int]]` of `0` or piece ids `1..7`, overlaid on the board with
  offset `(x, y)` (top-left of the shape). Overlay cells outside the board
  are clipped (no error); overlay cells win over board cells. The overlay
  does not mutate `board`. Invalid `shape_ids` values raise `ValueError`.

### Frame (byte-level)

- Exactly `len(board)//2 + 2` lines joined by `"\n"`, no trailing `"\n"`.
- Line `0` and line `len(board)//2 + 1` are borders: every segment has
  `fg == bg ==` border color.
- Frame line `i` (`1..len(board)//2`) encodes board rows `2i-2` (upper
  half of the character, fg) and `2i-1` (lower half, bg).
- Each line is exactly `len(board[0])` segments of the form
  `"\x1b[38;2;R;G;Bm\x1b[48;2;R;G;Bm▀"` (▀ U+2580, fg = upper row color,
  bg = lower row color), then the final `"\x1b[0m"`.
- The frame contains no `"\x1b[H"`, `"\x1b[2J"`, `"\x1b[?25"` — home,
  clear and cursor are the CLI's responsibility (CC-292).

### Palette (pinned, RGB)

- Module constants: `EMPTY_COLOR = (20, 20, 20)`,
  `BORDER_COLOR = (120, 120, 120)`, and `PIECE_COLORS`:

  | id | piece | RGB |
  |----|-------|-----|
  | 1 | I | (0, 255, 255) |
  | 2 | O | (255, 255, 0) |
  | 3 | T | (160, 0, 255) |
  | 4 | S | (0, 255, 0) |
  | 5 | Z | (255, 0, 0) |
  | 6 | J | (0, 120, 255) |
  | 7 | L | (255, 120, 0) |

  Input ids outside `0..7` never reach the palette — validation rejects
  them.
