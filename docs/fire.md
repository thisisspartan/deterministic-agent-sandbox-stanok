# fire — TrueColor terminal fire

A terminal fire animation in pure Python 3 stdlib (no third-party
libraries, no `curses`): a heat-diffusion simulator, a sub-pixel
half-block TrueColor renderer, a 256-entry palette generator and a raw
ANSI CLI.

## Architecture

```
src/main.py          CLI entry point (argparse, TTY guard)
src/fire/
  simulator.py       FireSimulation — heat buffer, no I/O
  renderer.py        FireRenderer — heat buffer -> ANSI frame string
  palette.py         generate_fire_palette / generate_blue_fire_palette
  cli.py             FireApp — terminal control, frame loop, signals
```

Layers are strictly separated: the simulator only manipulates its heat
buffer (no terminal dependency), the renderer only turns a buffer into a
frame string, and `FireApp` owns the terminal (alternate screen, cursor,
`SIGWINCH` resize, key polling, frame pacing).

## Physical model

The fire is a 1-D upward heat diffusion over a 2-D buffer
`buffer[y][x]` of ints in `[0..255]`: row 0 is the top, row `height - 1`
is the bottom fuel line.

- **Ignition** — `ignite_bottom()`: each bottom-row cell gets a random
  heat in `[200, 255]`; with probability 0.05 a cell is skipped (a gap in
  the fuel line).
- **Step** — `step(wind)`: rows `0..height-2` are recomputed top-to-bottom
  from the row below (the source row is not yet updated):

  ```
  dst_x = clamp(x - wind + choice(-1, 0, 1), 0, width - 1)
  buffer[y][dst_x] = max(0, buffer[y+1][x] - randint(decay_min, decay_max))
  ```

  with default decay `randint(1, 4)`. The bottom row is untouched.
- **Wind** — `update_wind()` drifts a target wind smoothly inside
  `[-2, 2]`: `target_wind = 2 * sin(phase)`, `phase += uniform(0.05, 0.2)`
  per tick; `step` uses `round(target_wind)` when no wind is given.
- **Embers** — `spawn_sparks(count=3)` injects rare very-hot particles
  (heat 250-255) into rows `height-2`/`height-3`; each tick they rise 2
  rows (the main flame rises 1), so embers shoot out above the flame.

## Half-block rendering

The character `▀` (U+2580, Upper Half Block) draws the upper half of a
terminal cell in the Foreground color and the lower half in the Background
color. A heat buffer of height `2 * H` therefore renders into `H` terminal
lines with vertical resolution `2 * H`:

```
for y in 0, 2, 4, ...:
    for x in 0..width-1:
        fg = palette[buffer[y][x]]      -> \033[38;2;R;G;Bm
        bg = palette[buffer[y+1][x]]    -> \033[48;2;R;G;Bm
        emit fg code if fg != previous fg
        emit bg code if bg != previous bg
        emit '▀'
frame ends with \033[0m
```

A color code is emitted only when it differs from the previous pixel's —
the terminal color state persists across the whole frame, which keeps
frames compact.

## Palette

A palette is a list of exactly 256 `(r, g, b)` tuples; index 0 is
`(0, 0, 0)`. Colors are obtained by piecewise linear interpolation
between control points; for index `i` in segment `[i0, i1]` with colors
`c0, c1`:

```
t = (i - i0) / (i1 - i0)
color(i) = round(c0 + (c1 - c0) * t)   per channel
```

Fire palette control points:

| index | color          | meaning            |
|-------|----------------|--------------------|
| 0     | (0, 0, 0)      | black / background |
| 32    | (140, 0, 0)    | dark red           |
| 96    | (255, 100, 0)  | bright orange      |
| 180   | (255, 220, 50) | golden yellow      |
| 240   | (255, 255, 230)| white              |
| 255   | (220, 240, 255)| white-blue sparks  |

Brightness (`r + g + b`) is monotonically non-decreasing from index 0 to
240; the final 241..255 segment cools slightly toward blue sparks. The
blue palette (`--palette blue`) has the same structure shifted to the
blue/cyan range.

## Running

```
python3 src/main.py --fps 45
```

Options: `--fps N` (1..60, default 30), `--palette fire|blue` (default
`fire`), `--wind N|auto` (static wind -3..3 or auto, default `auto`).
Requires a TTY on stdout (otherwise a note is printed and the program
exits cleanly). Press `q` or `Ctrl+C` to quit; the terminal is restored
(normal screen, visible cursor, default colors) on exit.

## Headless smoke test

`tests/smoke_test.py` runs 100 frames of the full pipeline
(ignite -> step -> render) at a 120x80 heat buffer (120x40 virtual
terminal) without any TTY output and fails if the average frame time
exceeds 33 ms (< 30 FPS).
