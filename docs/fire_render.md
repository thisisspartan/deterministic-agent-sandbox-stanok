# fire_render — Doom Fire renderer

Part 2 of the terminal 2D fire feature. A **pure** mapping from a temperature
matrix (produced by `src/fire_model.js`) to a string frame buffer. No I/O, no
terminal calls, CommonJS, no external dependencies.

## Exports

### `renderFrame(grid, opts)`
- **`grid`** — 2D array `grid[y][x]` of finite numbers in `[0, maxHeat]`;
  `y = 0` is the **TOP** row.
- **`opts`** (optional object):
  - `maxHeat` — positive number, default `255`.
  - `palette` — `"ansi256"` (default) or `"symbols"`.
- **Returns** — an array of `h` strings (one per row, top first). Each row
  renders exactly `w` **visible** characters; ANSI escape sequences are not
  counted as visible characters.

Cell mapping:

| Palette   | Temperature 0         | Temperature > 0                                                        |
| --------- | --------------------- | ---------------------------------------------------------------------- |
| `ansi256` | space (background)    | `█` wrapped in `\033[38;5;<n>m … \033[0m`; index `n` monotonic in temp |
| `symbols` | space                 | one of `░▒▓█` chosen monotonically (colder → `░`, hottest → `█`)    |

In `ansi256`, `n = PALETTE[pos]` where `pos` is the normalized palette
position; `PALETTE` is non-decreasing so hotter temperatures always map to a
higher (brighter) ANSI-256 index.

### `PALETTE`
A 256-entry array of ANSI-256 indices (the temperature→color ramp), exported so
the mapping can be inspected directly. `PALETTE[0]` is the darkest (black),
`PALETTE[255]` is the hottest (bright, near-white / red-hot end). The ramp is
monotonically non-decreasing.

### `SYMBOLS`
The 4-character `░▒▓█` gradient table used in `symbols` mode (cold → hot).

## Validation
`renderFrame` throws `TypeError` if `grid` is not an array of arrays of
finite numbers, if `maxHeat` is not a positive number, or if `palette` is not
`"ansi256"` or `"symbols"`.

## Run
```
bash scripts/run.sh test tests/fire_render.test.js
```
