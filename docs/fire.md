# fire — terminal fire (`src/fire.js`)

## Run

```
node src/fire.js
```

Shows an animated flame centered in the terminal (`stdout.columns x rows`,
fallback 80x24), rendering at ~30 FPS.

## Stop

Press **Ctrl-C** (SIGINT): the interval stops, the cursor is restored
(`ESC [?25h`), ANSI state is reset (`ESC [0m`), and the process exits 0.

## How it works

Three pure stages, one IO loop (`src/fire.js`, zero dependencies):

1. **Simulation** — a 2D heat-field grid (`createSim`/`step`), driven by a
   seeded PRNG (mulberry32) so frames are deterministic. Each tick: heat is
   injected at the centered, wide base (per-column noise → not a static
   cone), advects one row upward, is sampled through a per-column turbulence
   sway (stronger near the top → the flame sways and licks), and cools.
   Global per-frame flicker modulates the base intensity. Values stay in
   `[0, 1]`. Smoke particles spawn above the flame tip, rise, drift and fade.
2. **Palette** — heat → 24-bit truecolor (`ESC [38;2;R;G;B m`) through a
   multi-stop gradient: white-hot core → yellow → orange → red → dark red.
   Zero heat → empty cell (plain space, no escape). Smoke renders as faint
   gray.
3. **Renderer** — grid → one ANSI frame string; each lit cell is a half-block
   `▀` (lower half transparent, giving a soft glow); frame rows/cols equal
   the grid dimensions.
4. **Loop** — runs only when executed as main on a TTY: hides the cursor,
   clears the screen each frame, ~30 FPS.

## Tests

```
bash scripts/run.sh test tests/fire.test.js
bash scripts/run.sh smoke src/fire.js
```
