# `src/fire.py` — deterministic multicolor terminal fire (CC-109)

Stdlib-only Python 3.11 module. No IO at import time. Four separated
concerns:

## 1. Simulation — `FireSim(width, height, seed=0, inject=True)`

- `sim.heat[y][x]`: 2D grid of floats in `[0, 1]`; `y = 0` is the TOP row,
  `y = h-1` the bottom (base) row.
- `sim.base[y][x]`: per-cell flag for the blue combustion zone (bottom 2 rows).
- `sim.smoke`: sparse deterministic list of `SmokeParticle(x, y, life)`
  (life in `(0, 1]`, capped at 12), rising above the flame top and fading.
- `sim.tick()`: one deterministic frame (single seeded `random.Random(seed)`):
  1. global per-frame **flicker** multiplier `uniform(0.92, 1.08)`;
  2. heat **rises** one row per tick (`0.7` from below + `0.15` from each
     diagonal-below neighbor) with cooling `* 0.94` and `- 0.006` decay;
  3. per-cell multiplicative **turbulence** `uniform(0.85, 1.15)` on heated
     cells (sway / licking / multiple tongues);
  4. base row re-ignites each tick: `flick * uniform(0.6, 1.0)` per cell
     (`inject=False` decays instead — used by the decay test);
  5. smoke particles rise (`y -= 1`), drift sideways, fade (`life -= 0.06`),
     a new particle spawns (p = 0.5/tick) just above the current flame top.

Two sims with the same seed produce identical frame sequences.

## 2. Palette (pure)

- `palette(heat, is_base) -> (r, g, b) | None`
  - `heat < 0.05` (blank threshold, ≤ 0.10) → `None` (empty cell);
  - base-zone cells: blue-dominant gradient by heat (always `b > r`);
  - other cells: multi-stop gradient
    white-hot `(255,255,240)` → yellow `(255,220,80)` → orange `(255,140,0)`
    → red-orange `(220,60,20)` → red `(160,30,10)` → dark red `(90,15,8)`;
  - `palette(1.0, False) == (255, 255, 240)` exactly.
- `jittered_rgb(rgb, x, y)`: deterministic per-cell jitter in `[-4, +3]` per
  channel that breaks color banding — adjacent cells with identical heat are
  never pixel-identical.

## 3. Renderer (pure)

`render(sim)` → one ANSI frame string: `height` lines of `width` cells; each
visible cell is a 24-bit truecolor escape (`\x1b[38;2;R;G;B m`) followed by a
half-block `▀`; blank cells (and zero-heat frames) are plain spaces. Smoke
particles render as faint gray (~`(60,60,65)`, fading with life).

## 4. Loop (IO only) — `main()`, under `if __name__ == "__main__"`

- CLI (argparse): `--seed N --width W --height H --fps N --frames N --frame N`.
- `--frame N`: render exactly frame N (N ticks) to stdout, exit 0.
- No TTY (or `--frames N`): render N (default 1) frames to stdout, exit 0 —
  headless-safe, no infinite loop.
- Real TTY: ~30 FPS animation, flame centered in `shutil.get_terminal_size()`
  (fallback 80x24), clear per frame, cursor hidden; SIGINT stops the loop,
  restores the cursor (`\x1b[?25h`), resets ANSI (`\x1b[0m`), exits 0.

## Contracts / verification

- Basic contract: `tests/fire_basic_test.py` (17 tests, protected).
- Realism contract: `tests/fire_realism_test.py` (9 tests: multicolor 4
  families, blue base `b > r`, white-hot core brighter than cool edge,
  consecutive-frame flicker, moving flame top, smoke above flame top,
  banding-free jitter, heat rises and decays).
- Run: `bash scripts/run.sh test tests/fire_realism_test.py`
  `bash scripts/run.sh test tests/fire_basic_test.py`
  `bash scripts/run.sh smoke src/fire.py`
