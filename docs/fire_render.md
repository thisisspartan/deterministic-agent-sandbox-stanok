# fire_render — frame renderer (`src/fire_render.py`)

Stage 2 of 3 of the console-fire program: **pure string-in/string-out** —
turns ONE heat field (`list[list[float]]`, rows x cols, values in `[0, 1]`,
as produced by `fire_sim`) into ONE frame string using the half-block glyph
(U+2580) and 24-bit ANSI truecolor. No CLI, no terminal probing, no sleeps,
no writes to stdout, no module-level RNG, no time, no IO. The CLI (stage 3)
calls these names. The contract is pinned by `tests/fire_render_test.py`.

## Constants

| Name | Value | Meaning |
|---|---|---|
| `HALF_BLOCK` | `"▀"` (U+2580) | the glyph: upper half = foreground, lower half = background |
| `FALLBACK_COLUMNS` | `80` | default canvas width the CLI may use |
| `FALLBACK_ROWS` | `24` | default canvas height the CLI may use |
| `ANSI_RESET` | `"\x1b[0m"` | emitted after every colored glyph |

## Functions

`render_frame(field: list[list[float]], color_rng: random.Random) -> str`
: Renders one field into `height // 2` lines joined by `"\n"`, each line
  exactly `width` half-block glyphs. **Pairing rule:** two field rows per
  character line — row `2i` is the UPPER half (foreground) of line `i`,
  row `2i + 1` the LOWER half (background). Height must be even; odd height
  -> `ValueError`.

  **Escape layout** per character cell, where colors come from
  `fire_sim.heat_to_rgb(heat, color_rng)`:
  - both halves `None` (empty) -> a bare `HALF_BLOCK`, no escape codes;
  - otherwise -> `"\x1b[38;2;{r};{g};{b}m"` for the upper color (if any),
    then `"\x1b[48;2;{r};{g};{b}m"` for the lower color (if any), then the
    glyph, then `ANSI_RESET`. A `None` half emits no escape for that half.

  `color_rng` feeds `heat_to_rgb` for every cell, top-left to bottom-right,
  row-major — a single deterministic stream. **Pure:** `field` is never
  mutated.

`compose_frame(frame: str, columns: int, rows: int) -> str`
: Centers a frame string in a `rows` x `columns` canvas: returns exactly
  `rows` lines joined by `"\n"` — each frame line padded with leading spaces
  so it is horizontally centered (`(columns - len(line)) // 2` spaces), the
  canvas filled below the frame with blank lines. Frame taller than the
  canvas -> `ValueError`; any frame line wider than the canvas ->
  `ValueError`. Widths are measured in string characters (escape sequences
  included).

## Determinism rule (the core contract)

Same field + same `color_rng` seed state -> byte-identical frame string.
All randomness flows through the explicit `random.Random` passed by the
caller. No module-level RNG, no global state, no time, no IO.

## Terminal sizes

Canvas size is the CLI's concern: `render_frame` takes only the field, and
`compose_frame` takes `columns`/`rows` as arguments. `FALLBACK_COLUMNS` /
`FALLBACK_ROWS` are defaults the CLI may use when it cannot probe a
terminal — this module never queries the environment.

## Run the tests

`bash scripts/run.sh test tests/fire_render_test.py` — or the whole suite:
`bash scripts/run.sh test --all`. Smoke: `bash scripts/run.sh smoke src/fire_render.py`.
