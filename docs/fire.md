# Terminal Fire (`src/fire.js`)

## Run

```sh
node src/fire.js
```

Stop with **Ctrl-C** — the animation stops cleanly: the cursor is restored
(`\x1b[?25h`), ANSI state is reset (`\x1b[0m`), and the process exits with 0.

## How it works

Four separated concerns in one module (`src/fire.js`, CommonJS, zero
dependencies):

1. **Simulation** (`createFireSim(width, height, seed)`) — a 2D heat field,
   row `0` = top. Each tick: heat is injected at the base (wide, uneven,
   flickering), diffuses upward with ~1.5 % cooling per row, and is
   horizontally perturbed by seeded 2-D value noise (turbulence — the flame
   sways and licks). A taper mask keeps the flame wide at the base and
   narrow at the tip. A particle system adds faint gray smoke rising above
   the flame tip. All randomness comes from a seeded PRNG (mulberry32), so
   the same seed produces byte-identical frames. Heat is normalized to
   `[0, 1]`.
2. **Palette** (`palette(heat)`) — heat → truecolor ANSI
   (`\x1b[38;2;R;G;B m`) via a multi-stop gradient: dark red → red → orange
   → yellow → white-hot core. Zero heat → empty cell (`''`), which renders
   as a plain space.
3. **Renderer** (`render(grid, smoke, width, height)`) — grid + smoke → one
   ANSI frame. Each character is a half-block `▀`: the top half of the cell
   takes the foreground color (grid row `2r`), the bottom half the background
   color (grid row `2r+1`), giving 2× vertical resolution. A grid of
   `width × height` (even height) renders to `height/2` lines of `width`
   columns. Smoke pixels render as faint gray `░`.
4. **Loop** — starts only when run as main on a TTY
   (`require.main === module && process.stdout.isTTY`): hides the cursor,
   repaints the frame centered in `stdout.columns × stdout.rows` (fallback
   80×24) at **30 FPS** (grid height = 2 × rows), and handles SIGINT.

## Tests

```sh
bash scripts/run.sh test tests/fire.test.js
bash scripts/run.sh smoke src/fire.js
```
