# fire

Deterministic multicolor terminal fire (Python 3.11 stdlib only, single
module `src/fire.py`).

## What it does

Simulates a 2D heat field (`FireSim`, seedable `random.Random`, one
`tick()` per frame) and renders one ANSI frame per tick: half-block
(`▀`) cells in a multi-stop hot->cold flame gradient with per-cell
jitter, a blue combustion-zone base, and sparse rising smoke. A fixed
seed reproduces every frame byte-for-byte.

## How to run

```
python3 src/fire.py                          # TTY: ~30 FPS animation
python3 src/fire.py < /dev/null             # headless: exactly one frame
python3 src/fire.py --frame N               # deterministic frame N
python3 src/fire.py --frames N              # N deterministic frames, exit 0
```

Flags: `--seed` (default 42), `--width`, `--height`, `--fps`, `--frame`,
`--frames`, `--color {truecolor,256,16,none}`. The animation runs until
SIGINT (clean exit 0); headless runs never loop.

## Color modes (`render(sim, color_mode=...)`)

- `truecolor` (default): `\x1b[38;2;R;G;Bm\x1b[0m▀` — 24-bit escapes.
- `256`: `\x1b[38;5;Nm\x1b[0m▀` with `N = rgb_to_256(jittered rgb)`,
  N in 0..255.
- `16`: **basic SGR codes only** (CC-117) — the most compatible color
  encoding that exists. With `N = rgb_to_16(jittered rgb)`:
  N in 0..7 renders `\x1b[3Xm\x1b[0m▀` (X = N); N in 8..15 renders
  `\x1b[9Xm\x1b[0m▀` (X = N − 8). No `\x1b[38;5;N` escapes are emitted,
  because terminals that drop extended SGR sequences do so even for
  N in 0..15 but usually still understand the basic `\x1b[3Xm` /
  `\x1b[9Xm` codes. `rgb_to_16` is unchanged (returns 0..15).
- `none`: plain `▀`, no ANSI escapes.

Blank cells (heat below the 0.10 threshold) render as plain spaces in
every mode.

## Detection (`detect_color_mode(env=None)`)

`none` on an explicit opt-out (`NO_COLOR` non-empty or `TERM=dumb`);
`truecolor` when `COLORTERM` contains `truecolor`/`24bit` (case-
insensitive, wins over `TERM`); otherwise `256`. `--color` always wins.

## Public API

`FireSim(width, height, seed=42, inject=True)`, `sim.tick()`,
`palette(heat, is_base, blank=0.01)`, `jittered_rgb(rgb, x, y)`,
`rgb_to_16(rgb)`, `rgb_to_256(rgb)`, `detect_color_mode(env=None)`,
`render(sim, color_mode="truecolor")`, `main(argv=None)`.

## Tests

```
bash scripts/run.sh test tests/fire_basic_test.py
bash scripts/run.sh test tests/fire_realism_test.py
bash scripts/run.sh test tests/fire_polish_test.py
bash scripts/run.sh test tests/fire_shape_test.py
bash scripts/run.sh test tests/fire_color_test.py
bash scripts/run.sh test tests/fire_color16_test.py
bash scripts/run.sh test tests/fire_width_test.py
bash scripts/run.sh smoke src/fire.py
```
