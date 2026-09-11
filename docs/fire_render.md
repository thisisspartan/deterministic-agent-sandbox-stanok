# fire_render

Maps a fire model state to a string frame for display. Pure and deterministic:
`renderFrame` only reads `state.heat`, `state.width`, `state.height` — it never
requires or mutates the model. Built-in Node.js modules only.

## Exports

- `renderFrame(state, { mode = 'ansi256' })` → `string`
  `state` is `{ width, height, heat }` where `heat` is a `Float64Array`,
  row-major with row 0 = top. Returns `height` lines joined by `\n`, with
  **no** trailing newline; row 0 is the first line.

- `ramp(h)` → `[r, g, b]`
  Piecewise-linear color ramp for `h` in `[0, 1]`; each channel rounded to the
  nearest integer.

## Modes

- **ansi256** (default): each cell is
  `'\x1b[38;2;r;g;bm' + '█'` where `(r, g, b) = ramp(heat)`.
- **symbols**: each cell is exactly one character, with no escape sequences.

## Ramp stops

| h    | color        |
|------|--------------|
| 0    | (0, 0, 0)    |
| 0.25 | (128, 0, 0)  |
| 0.5  | (255, 64, 0) |
| 0.75 | (255, 160, 0)|
| 1    | (255, 255, 255) |

Colors between stops are linearly interpolated per channel.

## Symbol map

| heat        | char |
|-------------|------|
| 0           | ` ` (space) |
| (0, 0.25]   | `░` |
| (0.25, 0.5] | `▒` |
| (0.5, 0.75] | `▓` |
| (0.75, 1]   | `█` |
