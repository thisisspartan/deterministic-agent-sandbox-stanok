# `src/fire.py` — deterministic multicolor terminal fire

A pure, deterministic terminal fire: a 2D heat-field simulation rendered as
ANSI half-block (`▀`) cells. Stdlib only, no side effects on import. A fixed
seed reproduces every frame byte-for-byte.

## Concerns

1. **Simulation** — `FireSim`: a deterministic 2D heat grid of floats in
   `[0, 1]`. Per tick: turbulence-offset upward diffusion from the row below
   (with per-cell cold pockets that carve internal gaps), decay, base-row heat
   injection (central third only, so the flame is a cone, not a wall), and a
   sparse smoke-particle list rising above the flame top. One seeded
   `random.Random` drives every draw.
2. **Palette** — pure `(heat, is_base) -> (r, g, b) | None`: a multi-stop
   hot→cold gradient, a blue combustion gradient for base-zone cells, `None`
   below the blank threshold.
3. **Renderer** — pure `render(sim, color_mode="truecolor") -> str`: one ANSI
   frame of half-block cells. `color_mode` picks the escape style:
   `"truecolor"` (24-bit, default), `"256"` (`\x1b[38;5;Nm` via `rgb_to_256`),
   `"16"` (basic SGR via `fire16`, see below), or `"none"` (no escapes).
4. **Loop** — IO only, under `if __name__ == "__main__"`: ~30 FPS animation on
   a TTY, a single headless frame otherwise, deterministic `--frame N` /
   `--frames N` CLI modes, and a clean SIGINT shutdown.

## `fire16` — the 16-color flame ramp

`fire16(heat: float, is_base: bool, blank: float = 0.10) -> int | None`

Pure and deterministic (no PRNG, no wall clock). Maps a cell's heat to a basic
ANSI color index in `0..15`, or `None` for a blank cell. This is the dedicated
heat→basic-16 flame ramp used by the `"16"` color mode, replacing the old
nearest-RGB quantization (`rgb_to_16`) that collapsed almost every cell onto
red and never used the bright hot colors.

- `heat <= 0.0` → `None`.
- **Base** (blue combustion zone, `is_base`): `heat < 0.5` → `4` (blue);
  `heat >= 0.5` → `12` (bright blue).
- **Flame body** (else): `heat < blank` → `None`; otherwise a hot→cold ramp
  over the basic palette, using the BRIGHT hot colors for the core:
  - `heat < 0.30` → `1` (red)
  - `heat < 0.55` → `9` (bright red)
  - `heat < 0.75` → `3` (yellow)
  - `heat < 0.90` → `11` (bright yellow)
  - `heat >= 0.90` → `7` (white)

In the `"16"` renderer branch the index is computed as
`fire16(row[x], flags[x], BLANK_THRESHOLD)` (positional). Encoding stays basic
SGR: index `N` in `0..7` → `\x1b[3Xm\x1b[0m▀` (X=N); `N` in `8..15` →
`\x1b[9Xm\x1b[0m▀` (X=N-8); `None` → plain space. A smoke cell on a blank cell
renders as index `8` (bright black). The `"truecolor"`, `"256"`, and `"none"`
branches, `rgb_to_16`, `ANSI16_RGB`, `rgb_to_256`, `palette`, `jittered_rgb`,
the simulation, and determinism are all unchanged.

## `--probe` — the 16-color swatch card

`fire.py --probe` prints a **static** 16-color swatch card to stdout and exits
0. No simulation, no animation loop, works headless (no TTY needed),
deterministic. The card shows all 16 basic colors, one half-block (`▀`) per
index `0..15`, each encoded with basic SGR + reset (index `0..7` →
`\x1b[3Xm\x1b[0m▀`, index `8..15` → `\x1b[9Xm\x1b[0m▀`), laid out as 2 rows of
8. It lets a user see exactly which of the 16 basic colors their terminal
actually renders. When `--probe` is given it takes precedence over
`--frame`/`--frames`/`--color` (print the card and exit 0).
