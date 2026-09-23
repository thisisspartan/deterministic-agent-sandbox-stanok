# `src/fire.py` — deterministic multicolor terminal fire

A pure, deterministic 2D heat-field fire: seeded PRNG drives every draw, so a
fixed seed reproduces every frame byte-for-byte. Stdlib only, no side effects
on import.

## Flame proportions (CC-114)

The flame is a **central cone**, not a mountain filling the terminal:

- **Central base:** base-row injection happens only in the central third of
  the terminal — columns `[w//3, 2*w//3]` (inclusive) — with per-cell ignition
  probability, so the base is a ragged band with internal gaps, not a solid
  line.
- **Span cap:** in the bottom 6 rows the colored span (rightmost − leftmost
  + 1) is at most `w//2`.
- **Scales with the terminal:** on a wide terminal the flame stays central
  and proportional to the width; it does not stretch to fill it.

Kept from earlier contracts: tapering cone, internal gaps/tongues (cold
pockets in the lower body), blue combustion base (bottom rows), white-hot
core, per-frame flicker, sparse smoke above the flame top, per-cell color
jitter, and full determinism.

## Public API

- `FireSim(width, height, seed=42, inject=True)` — `sim.heat[y][x]` floats in
  `[0, 1]` (`y=0` top), `sim.base[y][x]` blue-zone flag (bottom `height//10`
  rows), `sim.smoke` particle list.
- `sim.tick()` — one frame: turbulence-offset upward diffusion, decay,
  central-third base injection, smoke update.
- `palette(heat, is_base, blank=0.01)` — `(r, g, b)` or `None` (blank).
- `render(sim, color_mode="truecolor")` — one ANSI frame of half-block cells;
  modes `"truecolor"` (default, 24-bit escapes), `"256"` (`rgb_to_256`),
  `"none"` (no escapes).
- `rgb_to_256(rgb)`, `detect_color_mode(env=None)`, `jittered_rgb(rgb, x, y)`
  — CC-113 color-capability helpers.
- CLI: `--seed/--width/--height/--fps/--frames N/--frame N/--color`; headless
  renders one frame and exits; TTY animates and exits 0 on SIGINT.

## Tests

`bash scripts/run.sh test tests/fire_*_test.py` — basic, realism, polish,
shape, color, and flame-width contracts.
