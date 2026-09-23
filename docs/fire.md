# `src/fire.py` — console fire (CC-108)

Deterministic, multicolor terminal fire. Python 3.11 stdlib only, single
module, zero dependencies.

## Module contract

Four separated concerns:

| Concern | API | Property |
|---|---|---|
| Simulation | `FireSim(width, height, seed)`, `.tick()`, `.heat`, `.base`, `.smoke` | pure, deterministic (seeded `random.Random`) |
| Palette | `palette(heat, is_base, jitter=0.0) -> (r,g,b) \| None` | pure |
| Renderer | `render(sim) -> str`, `frame_at(sim, n) -> str` | pure |
| Loop | `main(argv)`, `_run_loop(sim, fps)` | IO only, `__main__` guard |

### Simulation

- `heat`: 2D grid of floats in `[0, 1]`; row 0 = top, last row = base.
- Per `tick()`: inject heat at the base row(s) (center span), diffuse
  upward, lateral spread, turbulence (perturbs only hot cells, so cold
  cells stay exactly `0.0`), cooling decay; result clamped to `[0, 1]`.
- `base`: per-cell flag for the bottom two rows of the flame body (blue
  combustion zone).
- `smoke`: sparse deterministic list of `SmokeParticle(x, y, life)` (cap
  12); spawns just above the flame top, rises one row per tick, fades,
  and is dropped when dead.
- Same `seed` ⇒ identical frame sequence, always.

### Palette

Hot→cool multi-stop gradient: white-hot `(255,255,240)` → yellow
`(255,220,80)` → orange `(255,140,0)` → red-orange `(220,60,20)` → red
`(160,30,10)` → dark red `(90,15,8)` → fade to black. Base-zone cells use
a blue gradient by heat. Zero heat → `None` (empty cell). All components
int `0..255`. `jitter ∈ [-1, 1]` is a small SEEDED per-cell term
(pure function of `(seed, x, y)`) that breaks color banding.

### Renderer

Grid + smoke → one ANSI frame of `▀` half-block characters, 24-bit
truecolor (`\x1b[38;2;R;G;B m`), `\x1b[0m` per line. Frame dimensions
match the grid: `len(frame.split("\n")) == height`, exactly `width`
visible characters per line. Zero heat → plain space. Smoke renders faint
gray (~`60,60,65`) scaled by particle life.

### Loop / entrypoint

- Real TTY on stdout → ~30 FPS animation: clear screen per frame, flame
  centered in `shutil.get_terminal_size()` (fallback 80×24), cursor hidden.
  SIGINT: stop loop, restore cursor (`\x1b[?25h`), reset ANSI (`\x1b[0m`),
  exit 0.
- No TTY (e.g. `stdin </dev/null`, as `run.sh smoke` uses) → render ONE
  frame to stdout, exit 0 (no infinite loop).
- CLI (argparse): `--seed N`, `--width W`, `--height H`, `--fps N`,
  `--frames N` (render N frames then exit 0), `--frame N` (render exactly
  frame N then exit 0). Frame N (0-based) is the state after N+1 ticks.
- Importing `fire` has no IO side effects (everything IO is under the
  `__main__` guard).

## Usage

```bash
python3 src/fire.py                       # TTY: animate; no TTY: one frame
python3 src/fire.py --seed 7 --frame 12   # one deterministic frame
python3 src/fire.py --frames 30 --width 60 --height 20
bash scripts/run.sh test tests/fire_basic_test.py
bash scripts/run.sh smoke src/fire.py
```

## Tests

`tests/fire_basic_test.py` — import purity, seed determinism (in-process
and via CLI), heat-field bounds/evolution, base-zone flag, smoke
particles, palette range/white-hot/blue base/zero→None, renderer
dimensions/ANSI/half-block/empty frame, CLI `--frame`/`--frames`/headless,
and `run.sh smoke`.
