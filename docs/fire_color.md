# fire_color — realistic multicolored terminal fire

## Run

```
python3 src/fire_color.py
```

- Runs in the terminal at ~30 FPS, flame centered in the window
  (`shutil.get_terminal_size()`, fallback 80x24), screen cleared and cursor
  hidden while animating.
- Stop with **Ctrl-C**: the loop stops, the cursor is restored
  (`\x1b[?25h`) and the ANSI state reset (`\x1b[0m`), exit code 0.
- If stdin/stdout are not ttys (CI, pipes), it prints a short deterministic
  frame dump and exits 0 instead of animating.

## How it works

`src/fire_color.py` separates four concerns:

1. **Simulation** — `new_state(width, height, seed)` / `step(state)`:
   a 2D heat field (row 0 = base, values normalized to [0, 1]) advanced by a
   seeded PRNG (`random.Random(seed)`, so frames are deterministic):
   fuel is injected along a wide base, heat diffuses upward with per-row
   decay and a center taper (wide base, tapering tongues), per-frame global
   flicker modulates intensity, and per-cell turbulence (random horizontal
   mixing + licks/gaps) makes the flame sway. Each state also carries
   a **base-zone flag** (bottom rows with live heat) and sparse
   **smoke particles** that rise above the flame top and fade out.
2. **Palette** — `palette(heat, is_base, salt)`: multi-stop hot-to-cool
   gradient `white-hot (255,255,240) → yellow (255,220,80) → orange
   (255,140,0) → red-orange (220,60,20) → red (160,30,10) → dark red
   (90,15,8)`, with zero heat mapping to `None` (empty cell). Base-zone
   cells render a blue combustion gradient (`(80,120,255) → (120,180,255)`).
   A small seeded per-cell jitter breaks color banding.
3. **Renderer** — `render(state)`: grid + particles → one ANSI frame using
   24-bit truecolor (`\x1b[38;2;R;G;B m`) and half-block `▀` characters for
   vertical resolution; frame dimensions always match the grid.
4. **Loop** — `main()` (only IO): hidden behind the `__main__` guard,
   ~30 FPS, centered in the terminal, clean SIGINT/SIGTERM teardown.

## Color model

Blue combustion base (fresh fuel + air, b > r) · white-hot core ·
yellow/orange body · red tips · faint gray smoke (≈ 60,60,65) above.

## Tests

`bash scripts/run.sh test tests/fire_color_test.py` (9 tests: determinism,
heat range/evolution, palette order, multicolor families, blue base,
ANSI dimensions, blank field, smoke rise/fade) and
`bash scripts/run.sh smoke src/fire_color.py`.
