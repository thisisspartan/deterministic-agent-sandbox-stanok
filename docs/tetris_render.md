# tetris_render — module contract (CC-303)

A pure terminal renderer: a board (`list[list[int]]`, duck-typed) plus an
optional active piece -> one ANSI half-block truecolor frame string. stdlib
only, **no imports at all** — the engine module is NOT imported, not even by
name through `importlib`. No I/O, no global mutable state: `render_board` is a
pure function; identical input gives byte-identical output and neither the
board nor the `active` tuple is ever mutated.

Tests: `bash scripts/run.sh test tests/tetris_render_test.py`
(oracle: `tests/tetris_render_contract_test.py`).

## API (names pinned)

```
PIECE_COLORS          # dict {1..7: (r, g, b)} — module field
EMPTY_RGB            # (20, 20, 20)
BORDER_RGB           # (120, 120, 120)
render_board(board, active=None) -> str
```

`board` is read duck-typed as `list[list[int]]`: `0` = empty cell, `1..7` =
piece id. `active` is `None` or the 4-tuple `(shape_matrix, x, y, piece_id)`.

## R1 — the seam and the active overlay

The renderer knows nothing about the engine: the board is a plain nested list.
`active` overlays the falling piece on top of the board:

```
for (r, row) in enumerate(shape_matrix):
    for (c, value) in enumerate(row):
        if value:                       # a filled shape cell
            yy, xx = y + r, x + c
            if 0 <= yy < len(board) and 0 <= xx < len(board[0]):
                effective[yy][xx] = piece_id
```

The painted color comes from `piece_id`, **never** from the shape's own cell
values (a shape cell holding `7` under `piece_id=3` paints color 3). Shape
cells landing outside the board are clipped silently — not an error. The
overlay is applied to a private copy; the input board is untouched.
`piece_id` outside `1..7` -> `ValueError`.

## R2 — frame geometry

With `H = len(board)`, `W = len(board[0])`, the frame is exactly
`H // 2 + 2` lines joined by `"\n"`, **no trailing `"\n"`**:

```
line 0            top border
line 1 .. H/2     half-block rows   (screen row i = board rows 2i, 2i+1)
line H/2 + 1      bottom border
```

`ValueError` for: an empty board (`len(board) == 0`), an odd `H`, rows of
differing lengths (ragged), a row of width 0, or a cell value that is not an
`int` in `0..7`.

## R3 — the wire format

Every line is a concatenation of exactly `W` segments

```
"\x1b[38;2;R;G;Bm" + "\x1b[48;2;R;G;Bm" + "▀"      # ▀ U+2580, UTF-8 e2 96 80
```

(fg SGR and bg SGR back to back, no spaces inside the codes), terminated by
exactly one `"\x1b[0m"`; no other `"\x1b[0m"` inside a line. The glyph splits
the cell: **fg (`38;2`) is the upper half = board row `2i`, bg (`48;2`) is the
lower half = board row `2i+1`.**

- empty cell (`0`): fg = bg = `EMPTY_RGB` (20, 20, 20).
- border lines (first and last): `W` segments with fg = bg = `BORDER_RGB`
  (120, 120, 120) — fg == bg makes a solid line.

## R4 — palette (seven distinct colors)

| id | piece | hex | RGB |
|---|---|---|---|
| 1 | I | `#00ffff` | (0, 255, 255) |
| 2 | O | `#ffff00` | (255, 255, 0) |
| 3 | T | `#a000ff` | (160, 0, 255) |
| 4 | S | `#00ff00` | (0, 255, 0) |
| 5 | Z | `#ff0000` | (255, 0, 0) |
| 6 | J | `#0078ff` | (0, 120, 255) |
| 7 | L | `#ff7800` | (255, 120, 0) |

## R5 — what a frame never contains, and purity

No cursor or erase controls: `\x1b[H`, `\x1b[2J`, `\x1b[?25` (the frame is a
plain string a caller may print anywhere). Inputs are never mutated and share
nothing with the result; two calls with equal inputs return the same string.
