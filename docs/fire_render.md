# fire_render

Pure, deterministic renderer that turns a fire model state into a string frame.

## Exports

- `renderFrame(state, { mode = 'ansi256' })` → `string`
- `ramp(h)` → `[r, g, b]`

`state` is `{ width, height, heat }` where `heat` is a `Float64Array`,
row-major, row 0 = top. `renderFrame` only reads these three fields — it never
requires or mutates the model.

## `renderFrame`

Returns exactly `height` lines joined by `'\n'`, with **no trailing newline**.
Row 0 (top) is the first line. Two modes:

- **ansi256** (default): each cell is `'\x1b[38;2;r;g;bm' + '█'`, where
  `(r, g, b) = ramp(heat)` with each channel rounded to the nearest integer.
- **symbols**: each cell is exactly one character, with no escape sequences.

## `ramp(h)` stops (piecewise-linear, `h` in `[0, 1]`)

| h    | r   | g   | b   |
| ---- | --- | --- | --- |
| 0    | 0   | 0   | 0   |
| 0.25 | 128 | 0   | 0   |
| 0.5  | 255 | 64  | 0   |
| 0.75 | 255 | 160 | 0   |
| 1    | 255 | 255 | 255 |

Out-of-range `h` is clamped to `[0, 1]`.

## Symbol map

| heat range | char |
| ---------- | ---- |
| `0`        | `' '` |
| `(0, 0.25]` | `'░'` |
| `(0.25, 0.5]` | `'▒'` |
| `(0.5, 0.75]` | `'▓'` |
| `(0.75, 1]` | `'█'` |
