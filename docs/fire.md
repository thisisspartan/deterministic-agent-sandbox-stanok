# fire — terminal fire

## Run

```sh
node src/fire.js
```

Starts the animated flame (requires an interactive TTY).

## Stop

Press **Ctrl-C**. The animation stops, the cursor is restored
(`\x1b[?25h`), ANSI state is reset (`\x1b[0m`), and the process exits 0.

## How it works

A three-stage pipeline, all pure and deterministic given a seed:

1. **Simulation** (`createSim` / `tick`) — a 2D heat field (row 0 = top).
   Each tick injects heat at the base (wide base, swaying center, per-column
   random-walk turbulence), diffuses it upward with per-cell perturbation,
   cools it faster toward the top, and modulates everything with a global
   per-frame flicker. A seeded PRNG (mulberry32) makes every frame
   deterministic. Faint gray smoke particles spawn above the flame tip and
   rise while fading. Heat values stay in `[0, 1]`.
2. **Palette** (`palette`) — heat → 24-bit RGB via a multi-stop gradient:
   transparent → dark red → red → orange → yellow → white-hot.
   Zero heat → empty cell (no escape sequence).
3. **Renderer** (`renderFrame`) — grid → one ANSI frame of half-block
   characters (`▀`), each representing two vertical heat samples.
   Frame size is `ceil(height/2)` rows × `width` columns.

## Loop

Started only when run as main on a TTY (`require.main === module` guard).
~30 FPS: each tick clears the screen and repaints one frame, flame centered
in `process.stdout.columns` × `process.stdout.rows` (fallback 80×24).
Requiring the module (tests, `scripts/run.sh smoke`) never starts the loop.
