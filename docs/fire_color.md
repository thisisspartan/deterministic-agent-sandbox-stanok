# fire_color — realistic multicolored terminal fire

## Run

```
python3 src/fire_color.py
```

- Animates at ~30 FPS, flame centered in the window
  (`shutil.get_terminal_size()`, fallback 80x24), screen cleared and cursor
  hidden while animating.
- Stop with **Ctrl-C**: the loop stops, the cursor is restored
  (`\x1b[?25h`) and the ANSI state reset (`\x1b[0m`), exit code 0.
- If stdin/stdout are not ttys (CI, pipes), it prints a short deterministic
  frame dump and exits 0 instead of animating.

## How it works

`src/fire_color.py` separates four concerns:

1. **Simulation** — `new_state(width, height, seed)` / `step(state)`:
   a 2D heat field (row 0 = base/bottom, values normalized to [0, 1])
   advanced by a seeded PRNG (`random.Random(seed)`, so frames are
   deterministic). Each tick: fuel is injected along a wide base line with
   turbulence gaps (roughly 1 in 5 base cells stays dead, so the base is
   never a solid line); heat is carried upward with per-cell turbulence
   (random shear, upward licks, pockets) and modulated by a global flicker;
   then it is multiplied by a strong quadratic per-row cooling
   `1 - (y/H)**2` and cut outside a hard center taper
   `half_width(y) = 0.45·width·(1 - y/H)^0.8` — the flame is a CONE, wide at
   the base and narrowing to a point, with large blank areas around it.
   The state also carries a **base-zone flag** (bottom rows with live heat —
   where fresh fuel meets air) and sparse **smoke particles** that rise
   above the flame top and fade out.
2. **Palette** — `palette(heat, is_base, salt)`: multi-stop hot-to-cool
   gradient `white-hot (255,255,240) → yellow (255,220,80) → orange
   (255,140,0) → red-orange (220,60,20) → red (160,30,10) → dark red
   (90,15,8)`; heat below the blank threshold **0.10** maps to `None`
   (empty cell, no ANSI escape). Base-zone cells render a blue combustion
   gradient (`(80,120,255) → (120,180,255)`). A small seeded per-cell jitter
   (`salt`) breaks color banding.
3. **Renderer** — `render(state)`: grid + particles → one ANSI frame using
   24-bit truecolor (`\x1b[38;2;R;G;B m`) and half-block `▀` characters for
   vertical resolution; frame dimensions always match the grid; blank cells
   are plain spaces.
4. **Loop** — `main()` (only IO, behind the `__main__` guard): ~30 FPS,
   centered in the terminal, clean Ctrl-C teardown.

## Color model

Blue combustion base (fresh fuel + air, b > r) · white-hot core ·
yellow/orange body · red tips · faint gray smoke (≈ 60,60,65) above.

## Tests

- `bash scripts/run.sh test tests/fire_color_test.py` — 9 tests:
  determinism, heat range/evolution, palette, multicolor families, blue
  base, ANSI dimensions, blank field, smoke rise/fade.
- `bash scripts/run.sh test tests/fire_shape_test.py` — 4 shape-contract
  tests: cone taper (top rows far sparser than bottom rows), mostly-blank
  top, non-solid base, cold heat renders blank.
- `bash scripts/run.sh smoke src/fire_color.py`.
