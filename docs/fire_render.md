# fire_render — terminal driver constants + half-block frame renderer

Module: `src/fire_render.py` (TASK-STANOK-CC-249, FIRE2-02). Pure string
building: no process loop, no I/O (that is FIRE2-03). Imports `PALETTE` from
`src/fire_engine.py`; does not modify it.

## Contract

- `ENTER = "\x1b[?1049h\x1b[?25l"` — enter the alternate screen, hide the cursor.
- `EXIT = "\x1b[?1049l\x1b[?25h\x1b[0m"` — leave the alternate screen, show the
  cursor, reset SGR. The driver writes `ENTER` once at startup and `EXIT` once
  at shutdown; a frame contains neither.
- `PAIR_CACHE` — a mapping of all 37×37 = 1369 palette index pairs to the exact
  escape string
  `"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m▀"`
  (fg = top color, bg = bottom color, `▀` = U+2580 UPPER HALF BLOCK). Built
  ONCE at import; the only place any f-string runs. Keyed by the `(top, bottom)`
  tuple; a flat `top * 37 + bottom` integer resolves to the same entry.
- `render_frame(field) -> str` — one full frame from a FireField-like object
  (reads only `width`, `height`, `buffer`; never mutates it):
  - starts with `"\x1b[H"` (cursor home — no clear-screen, every cell is
    repainted), ends with `"\x1b[0m"`, rows joined with `"\n"`;
  - terminal row `i` pairs field rows `(2i, 2i+1)`: fg from the top row's
    palette color, bg from the bottom row's — a terminal of N rows shows a field
    of 2N; each row is `width` cached `▀` cells;
  - odd height: a trailing unpaired field row is rendered as a full block
    (fg == bg), never dropped; `height == 0` yields `"\x1b[H\x1b[0m"`;
  - the hot path only joins cached strings — no per-pixel formatting.
- `frame_bytes(frame) -> bytes` — `frame.encode("utf-8")` (`▀` is 3 bytes) for
  callers writing bytes to the terminal.

## Tests

`tests/fire_render_test.py` (pytest, run via `scripts/run.sh test ...`):
`ENTER`/`EXIT` exact; `PAIR_CACHE` size 1369, full key coverage, spot-checked
escape strings, flat-index equivalence, and a seeded property check that every
cached entry equals a naively formatted reference; `render_frame` exact strings
for 2×2 / 4×4 / duck-typed and real `FireField` buffers, fg-vs-bg asymmetry,
frame structure (home without clear, single reset, row and cell counts, newline
only), odd-height and single-row handling, empty field, non-mutation and
reproducibility; `frame_bytes` equals the UTF-8 encoding.
