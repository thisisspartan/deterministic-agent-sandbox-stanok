# fire_render (TASK-STANOK-CC-241 / FIRE-02)

Terminal driver + half-block renderer for the Doom fire. Pure string building:
it reads a `FireField`-shaped object and produces terminal text. No process
loop, no file/socket I/O, no subprocess (the loop is FIRE-03). The palette
comes from `src/fire_engine.py`, which this module imports and never modifies.

## Contract

`src/fire_render.py`

- `ENTER = "\x1b[?1049h\x1b[?25l"` — enter the alternate screen, hide the cursor.
- `EXIT = "\x1b[?1049l\x1b[?25h\x1b[0m"` — leave the alternate screen, show the
  cursor, reset SGR.

- `PAIR_CACHE` — a dict keyed by `(top, bottom)` palette **indices**, holding
  all `37 × 37 = 1369` entries, each exactly

  ```
  "\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m▀"
  ```

  (fg = `PALETTE[top]`, bg = `PALETTE[bottom]`, then the U+2580 UPPER HALF
  BLOCK). Built once at import; the RGB values are decimal, as truecolor SGR
  requires.

- `render_frame(field) -> str` — one full frame from any object exposing
  `width`, `height`, `buffer` (flat, `buffer[y * width + x]`):

  ```
  "\x1b[H" + "\n".join(terminal_row(y) for y in 0, 2, 4, ...) + "\x1b[0m"
  ```

  - `"\x1b[H"` homes the cursor; there is **no** clear (`2J`/`2K`) — every cell
    of the frame is repainted, so clearing would only add flicker.
  - A terminal row pairs two field rows: top row `y`, bottom row `y+1`. It is
    `width` cached cells; the cell at column `x` takes fg from `buffer[y][x]`
    and bg from `buffer[y + 1][x]` — one `▀` draws two fire pixels.
  - The frame ends with `"\x1b[0m"` so the shell is left in a clean state.
  - The field is only read; `render_frame` mutates nothing.

- `frame_bytes(frame) -> bytes` — `frame.encode("utf-8")`, for callers that
  write bytes to a terminal.

## Why the cache

The render path runs over `width × height / 2` cells per frame. Formatting an
SGR escape per pixel would rebuild the same 1369 strings every frame; instead
`render_frame` does a dict lookup and `"".join(...)` over cached strings — no
f-string evaluation in the hot path. The cache is derived from `PALETTE` at
import, so it can never drift from the engine's palette.

## Tests

`tests/fire_render_test.py` (pytest, run via
`scripts/run.sh test tests/fire_render_test.py`)

- `ENTER` / `EXIT`: exact byte sequences.
- `PAIR_CACHE`: 1369 entries, every `(top, bottom)` index pair present, a
  pinned entry with decimal RGB written out literally, the two-SGR-then-half-block
  shape, and equality with a naively formatted reference over 50 seeded random
  pairs.
- `render_frame`: the exact string for a hand-built 2×2 field; home prefix and
  reset suffix appear exactly once and no clear/cursor-move codes appear; row
  pairing is `(0,1)`, `(2,3)` with fg from the top row and bg from the bottom;
  each terminal row is `width` half-block cells; equality with the naive
  reference for a seeded `FireField(5, 4)` stepped twice (once with `wind=1`);
  the field buffer is unchanged by rendering.
- `frame_bytes`: equals `frame.encode("utf-8")`, with the 3-byte utf-8 half
  block counted.
