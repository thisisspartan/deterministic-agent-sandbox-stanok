# `src/fire.py` — deterministic multicolor terminal fire (CC-110)

Stdlib-only Python 3.11. Four separated concerns, all pure except the loop:

## 1. Simulation — `FireSim(width, height, seed=42, inject=True)`
- `sim.heat`: 2D float grid `[y][x]`, values in `[0, 1]`, `y = 0` at the top,
  base row `height - 1` at the bottom.
- Per `sim.tick()`: the new row `y` is the decayed average (`DECAY = 0.92`)
  of three cells of the row below, sampled with a per-row turbulence offset
  (±1) from the seeded `random.Random(seed)` — heat rises one row per tick
  while swaying and licking. The base row is re-ignited each tick: 80% of
  cells get heat in `[0.85, 1.0]`, leaving gaps that form multiple tongues
  on a wide base tapering upward.
- `sim.base[y][x]`: bool per-cell flag for the bottom rows (blue
  combustion zone).
- `sim.smoke`: sparse list of `SmokeParticle(x, y, life)` (capped at 12),
  rising above the current flame top, drifting, fading (life ≤ 1, removed
  at ≤ 0 or out of bounds).
- One seeded PRNG drives every draw → a fixed seed reproduces every frame
  byte-for-byte.

## 2. Palette — `palette(heat, is_base) -> (r, g, b) | None`
- Non-base: multi-stop gradient, hottest → coldest: white-hot
  `(255, 255, 240)` → yellow `(255, 220, 80)` → orange `(255, 140, 0)` →
  red-orange `(220, 60, 20)` → red `(160, 30, 10)` → dark red
  `(90, 15, 8)` → ember `(70, 10, 6)`; `None` for heat below the blank
  threshold (0.01 ≤ 0.10) and for zero heat.
- Base zone: blue combustion gradient `(25, 45, 90)` → `(80, 130, 220)` →
  `(150, 200, 255)`; blue-dominant for any positive heat.
- `jittered_rgb(rgb, x, y)`: bounded per-cell jitter (≤ 8 per channel,
  clamped to `[0, 255]`), deterministic in the cell coordinates, breaks
  color banding between equal-heat neighbors.

## 3. Renderer — `render(sim) -> str`
- One frame of exactly `height` newline-joined rows of `width` cells.
- Cell = `\x1b[38;2;R;G;B m\x1b[0m` + `▀` (24-bit truecolor half-block) or a
  plain space for zero/blank heat; smoke cells render faint gray
  `~(60, 60, 65)`. No trailing newline.

## 4. Loop / CLI (only under `if __name__ == "__main__":`)
- TTY stdout → animation at `--fps` (default 30), screen cleared per frame,
  flame centered in `shutil.get_terminal_size()` (fallback 80×24).
- No TTY (e.g. `run.sh smoke`) → renders exactly one frame and exits 0.
- Flags: `--seed N`, `--width W`, `--height H`, `--fps N`,
  `--frames N` (render N frames, exit 0), `--frame N` (render exactly frame
  N, exit 0). Invalid values are rejected by argparse (rc=2).
- SIGINT: stops the loop, restores the cursor (`\x1b[?25h`), resets ANSI
  (`\x1b[0m`), exits 0. A closed output pipe (`| head`) is handled cleanly.

Performance: one O(width·height) pass per tick; ~300 frames at 80×24
render in ~1–2 s (budget 5 s) on CPython 3.11.

Run the contracts:

```
bash scripts/run.sh test tests/fire_basic_test.py
bash scripts/run.sh test tests/fire_realism_test.py
bash scripts/run.sh test tests/fire_polish_test.py
bash scripts/run.sh smoke src/fire.py
```
