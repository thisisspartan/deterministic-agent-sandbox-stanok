# Multicolored terminal fire (`src/fire_color.py`)

Run: `python3 src/fire_color.py`
Stop: press **Ctrl-C** — the cursor is restored, ANSI state is reset, exit code 0.

## How it works

1. **Simulation** (`Fire`): a 2D heat field (values in [0, 1]) where heat is
   injected at the base, advected upward with 3-neighbor smoothing and
   cooling, perturbed by a bounded per-cell value-noise (turbulence) so the
   flame sways with multiple tongues, and flickered globally per frame. A
   seeded PRNG (`random.Random(seed)`) makes every frame deterministic.
   The bottom rows carry a **combustion-zone flag**, and a sparse set of
   deterministic **smoke particles** spawns above the flame top, rises, and
   fades.
2. **Palette** (`palette`): `(heat, is_base, jitter) -> (r, g, b) | None`.
   Hot → cool gradient: white-hot (255,255,240) → yellow (255,220,80) →
   orange (255,140,0) → red-orange (220,60,20) → red (160,30,10) → dark red
   (90,15,8) → None (empty cell). Base-zone cells use a blue gradient
   (120,180,255 → 80,120,255). Smoke is faint gray (~60,60,65). A small
   seeded per-cell jitter breaks color banding.
3. **Renderer** (`render_frame`): grid + particles → one frame string of
   24-bit truecolor ANSI (`ESC[38;2;R;G;B m`) using half-block `▀`/`█`
   characters for 2x vertical resolution; frame is `height/2` lines by
   `width` cells; zero heat renders as a plain space.
4. **Loop** (`main`, `__main__` guard only): hides the cursor, animates at
   ~30 FPS, clears the screen each frame, and centers the flame in
   `shutil.get_terminal_size()` (fallback 80x24).

## Color model

- **Blue** combustion base (where fresh fuel meets air),
- **white-hot core** brighter than the edges,
- **yellow/orange** body, **red** tips,
- faint **gray smoke** above the flame.

Tests: `bash scripts/run.sh test tests/fire_color_test.py`
Smoke: `bash scripts/run.sh smoke src/fire_color.py`
