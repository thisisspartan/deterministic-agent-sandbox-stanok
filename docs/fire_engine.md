# fire_engine — pure Doom fire logic (no I/O)

Module: `src/fire_engine.py` (TASK-STANOK-CC-248). Pure math only: no terminal
escape codes, no file/socket I/O.

## Contract

- `PALETTE` — exactly 37 RGB tuples (the classic Doom fire palette); index ==
  fire intensity 0..36.
- `FireField(width, height, rng=None)` — flat buffer `buffer[y * width + x]`,
  y=0 top; the bottom row `y=height-1` is the source row, seeded to 36.
  `rng` is an injectable `random.Random` (default: the module `random`) so
  tests are deterministic.
- `step(wind=0)` — one bottom-up pass, y from `height-1` down to 1, for each x:
  - `src = buf[y][x]`; if `src == 0` → `buf[y-1][x] = 0` (zero stays zero);
  - else draw `rand = rng.randint(0, 3)`; `dst = x - rand + 1 + wind`;
    if `0 <= dst < width`: `buf[y-1][dst] = max(0, src - (rand & 1))`
    (decay by 1 when rand is odd, clamped at 0). Out-of-bounds `dst` is
    skipped — no wrap.
  - `wind` is clamped to `[-3, 3]`. The source row is never modified.
- `color_at(value)` → `PALETTE[value]`; values are always 0..36 by construction.

## Tests

`tests/fire_engine_test.py` (pytest, run via `scripts/run.sh test ...`):
palette shape/endpoints, source-row seeding, exact propagation with a pinned
seed (`random.Random(42)`), decay clamping, zero-persistence, out-of-bounds
skip, wind symmetry and clamping, `color_at` bounds. All rng use is seeded or
scripted — no flaky asserts.
