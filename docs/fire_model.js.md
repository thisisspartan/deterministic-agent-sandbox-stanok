# fire_model — Doom Fire heat model (pure logic)

CommonJS module with no external dependencies and no I/O. It exports exactly
one function: `createFireModel`.

## `createFireModel(w, h, opts)`

### Parameters
- `w`, `h` — positive integers (grid width/height in cells). Any other value
  (0, negatives, fractions, strings, `null`, `undefined`) throws `TypeError`.
- `opts` — optional object:
  - `maxHeat` — positive number, default `255`.
  - `decay` — number in `(0, 1]`, default `0.08`.
  - `seed` — optional non-negative integer. If given, the internal PRNG
    (self-contained xorshift32) is seeded and the simulation is fully
    deterministic. If absent, a random seed is used.

### Returns
A model object:
- `w`, `h`, `maxHeat` — numbers.
- `grid` — 2D array `grid[y][x]`; `y = 0` is the TOP row, `y = h-1` is the
  BOTTOM row (the heat source). All values are numbers in `[0, maxHeat]`,
  initialized to `0`.
- `step()` — advances the simulation by one frame, computed on a new
  double-buffered state (no cell reads a value already updated this frame):
  1. Bottom row (`y = h-1`): each cell gets stochastic heat
     `maxHeat * (0.7 + 0.3 * rand())` — values in `[0.7*maxHeat, maxHeat]`,
     varying between cells.
  2. Every cell `(x, y)` for `y < h-1`:
     `newTemp = max(0, below - decay * rand() * maxHeat)` where
     `below = grid[y+1][x + dx]`, `dx ∈ {-1, 0, 1}` is a random jitter and
     `x + dx` is clamped to `[0, w-1]`.
  3. All values are clamped to `[0, maxHeat]`.

The module is pure: no I/O, no terminal calls; the only side effect is
mutating its own `grid`.

## Guarantees (verified by `tests/fire_model.test.js`)
- Grid shape `h` rows × `w` cells; all values always in `[0, maxHeat]`.
- Bottom row after any `step()` lies in `[0.7*maxHeat, maxHeat]` and has at
  least two distinct values (for `w >= 2`).
- A cell never exceeds the max of the row below after a `step()`.
- After sufficient warm-up, per-row average temperatures strictly decrease
  from the bottom row upward (with a fixed seed).
- Deterministic for a given seed; different seeds produce different grids.
- Works for `3×3`, `200×60` and `1×1` grids.
