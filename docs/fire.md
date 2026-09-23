# Fire — deterministic multicolor terminal fire

A pure-stdlib (Python 3.11, zero dependencies) deterministic fire rendered
with 24-bit truecolor half-block (`▀`) cells.

## Run / stop

- Run: `python3 src/fire.py` — ~30 FPS animation on a TTY, centered in the
  terminal.
- Stop: `Ctrl-C` (cursor restored, ANSI reset, exit 0).
- Flags: `--seed N` (default 42), `--width N` / `--height N` (default:
  terminal size), `--fps N` (default 30), `--frame N` (render exactly frame
  N and exit), `--frames N` (render N frames and exit).
- Non-TTY stdout (pipes, `scripts/run.sh`): exactly one frame is rendered
  and the process exits 0 — never an infinite loop.

## How it works

`src/fire.py` has four separated concerns:

1. **Simulation** (`FireSim`): a 2D heat field `heat[y][x]` of floats in
   `[0, 1]`, `y = 0` at the top, fuel injected at the base row. Each tick:
   upward diffusion from the row below with a per-row turbulence wobble
   (±1 column), strong per-row cooling (`DECAY = 0.84`), probabilistic
   base-row injection (`INJECT_PROB = 0.70`, leaving ragged gaps), and a
   sparse list of smoke particles rising above the flame top. One seeded
   `random.Random` drives every draw, so a fixed seed reproduces every
   frame byte-for-byte.
2. **Flame shape**: the cone taper precomputed per cell gates rising
   rows — a row `r` rows above the base only carries heat within a half
   width of `(w/2) * (1 - r/h)`, shrinking to a point at the top. Cells
   outside the cone stay cold, so the flame is a tapering cone (wide at
   the base, narrow at the tip) with a ragged silhouette, not a solid
   block.
3. **Palette** (`palette(heat, is_base, blank)`): `None` (blank cell) for
   heat below the blank threshold (`BLANK_THRESHOLD = 0.10`), so
   near-dead heat never fills the grid; a blue combustion gradient for
   base-zone cells (blue-dominant, `b > r`); otherwise a multi-stop
   hot→cold gradient: white-hot `(255,255,240)` at the peak → yellow →
   orange → red-orange → dark red. Per-cell seeded jitter (`jittered_rgb`,
   ≤ 8 per channel) breaks color banding.
4. **Renderer** (`render(sim)`): one ANSI frame of exactly `height` rows ×
   `width` cells; colored cells are `\x1b[38;2;R;G;Bm\x1b[0m▀`, blank cells
   are plain spaces; smoke particles render as faint gray.

Color model: blue combustion base zone → white-hot core → yellow-orange
→ red body → smoke above the flame top.

## Tests

- `bash scripts/run.sh test tests/fire_basic_test.py` — contract (imports,
  determinism, heat bounds, palette, renderer, CLI).
- `bash scripts/run.sh test tests/fire_realism_test.py` — realism (4 color
  families, blue base, white-hot core, flicker, turbulence, smoke, no
  banding, heat rises and decays).
- `bash scripts/run.sh test tests/fire_polish_test.py` — polish (300 frames
  at 80x24 < 5 s, `--frame`/`--frames` determinism, small terminals,
  non-TTY safety).
- `bash scripts/run.sh test tests/fire_shape_test.py` — shape (taper:
  top 6 rows under half the bottom 6; top 50%+ blank; base < 90% lit;
  cold heat renders blank).
- `bash scripts/run.sh smoke src/fire.py` — module smoke load.
