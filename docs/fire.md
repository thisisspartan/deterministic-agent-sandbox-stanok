# Fire — terminal flame (max-propagation simulation)

A bright, tall, genuinely multicolored terminal fire rendered with 24-bit
truecolor ANSI. Pure Python stdlib, no dependencies.

## Run

```
python3 src/fire.py
```

- Requires a TTY; when stdout is a pipe or redirected (headless), the module
  loads and does nothing (no animation, no output).
- Stop with **Ctrl-C** (SIGINT): the cursor is restored (`\x1b[?25h`), ANSI
  is reset (`\x1b[0m`), and the process exits with status 0.
- Renders at **~30 FPS**, clearing and homing the screen per frame, with the
  flame centered in `shutil.get_terminal_size()` (fallback 80x24).

## Tests

- `bash scripts/run.sh test tests/fire_test.py` — full suite (stdlib unittest)
- `bash scripts/run.sh smoke src/fire.py` — sanity-load without animating

## How it works

Four layers (layers 1–3 pure, layer 4 IO only under `__main__`):

1. **Simulation** (`FireSimulation`) — a `height x width` grid (~64 x 32),
   `y = 0` is the TOP. Each tick every cell takes the **max of the three
   cells one row below it** (the row closer to the fuel; out-of-range
   neighbors count as 0) minus a small SEEDED random decay
   (`rng.uniform(0, 0.12)`). This max-propagation ("tropical") model raises a
   sharp, multi-tongued front instead of a flat cone, and heat decays only
   slowly going up, so the whole flame column stays hot from base to tip.
   The bottom `BASE_ROWS = 3` rows are the fuel band: driven hot with
   per-column variation (`uniform(0.85, 1.0)`) around a slowly
   random-walking (swaying) center, so the base is white-hot and the tongues
   are uneven. All heat is clamped to `[0, 1]`; the PRNG is
   `random.Random(seed)`, so a given seed produces deterministic frames.
   Smoke particles spawn above random flame tongues and drift upward with a
   slight horizontal wander while fading.
2. **Palette** (`palette(heat, is_base, seed)`) — hot to cool:
   white-hot (255,255,240) -> yellow (255,220,80) -> orange (255,140,0) ->
   red-orange (220,60,20) -> red (160,30,10) -> dark red (90,15,8);
   zero heat -> `None` (plain space). Combustion-zone (base) cells render a
   **blue-dominant** gradient by heat (120,180,255 -> 80,120,255, always
   `b > r`). A small SEEDED per-cell jitter (±6) breaks banding; all
   channels clamp to 0–255.
3. **Renderer** (`render(...)`) — a frame of exactly `height` lines x
   `width` cells. Every lit cell is a SOLID full-block character (`█`), so the
   flame reads as one solid bright mass (no dotted/striped look); smoke cells
   are faint gray (`░`, ~60,60,65); zero-heat cells are plain spaces with no
   escape. Color is emitted as 24-bit truecolor ANSI
   (`\x1b[38;2;R;G;B m`) whenever it changes.
4. **Loop** (`main()`) — IO only: TTY guard, cursor hide, 30 FPS pacing,
   clear/home per frame, terminal centering, SIGINT restore + exit 0.

## Color model (bottom to top)

| Zone | Heat | Color |
|------|------|-------|
| Combustion base (bottom 3 rows) | 0.7–1.0 | blue-dominant (b > r) |
| Core, just above the base | ~0.9–1.0 | white-hot (255,255,240) |
| Upper body | ~0.5–0.9 | yellow (255,220,80) |
| Mid body | ~0.3–0.5 | orange (255,140,0) |
| Tips | ~0.15–0.3 | red (160,30,10) |
| Flickering tips | ~0.05–0.15 | dark red (90,15,8) |
| Above the flame | — | faint gray smoke (60,60,65) |

The slow upward decay keeps every column of the flame hot enough that the
full gradient — blue base, white-hot core, yellow/orange/red body, dark-red
tips — is visible in a single frame.
