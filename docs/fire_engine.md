# fire_engine — module contract (CC-287)

Pure, deterministic flame simulator in the DOOM-fire style: no I/O, no
time, no network, no files — stdlib `random` only. First layer of the
"console fire" wave: the renderer/CLI consumers arrive in later tickets
(the terminal seam is pinned in CC-289).

## Public API (pinned)

Exactly one public name: `FireEngine`.

`FireEngine(seed: int, width: int, height: int)`

- `width < 2` or `height < 2` → `ValueError`. `seed` — arbitrary int
  (negative seeds are valid).
- State: grid of `height` rows × `width` columns, cells are int heat
  `0..255`. Initial state: all zeros. Row `height-1` is the bottom row.
- `rng = random.Random(seed)` — one instance per engine, consumed only
  in the fixed traversal order below.

### `step()` — one simulation tick

Traversal order is fixed and part of the determinism contract:
bottom row left→right, then rows bottom-to-top (`y = height-2 … 0`),
cells left→right. Rows below already hold this tick's values when a row
is computed (in-place update).

- **Bottom row:** every cell = fresh fuel `rng.randint(180, 255)`
  (no cooling).
- **All other cells `(x, y)`:** four heat sources from below —
  `(x, y+1)`, `(x-1, y+1)`, `(x+1, y+1)`, `(x, y+2)`; a source outside
  the grid is replaced by the value of cell `(x, y+1)`. New value =
  `sum(four_sources) // 4 - rng.randint(0, 3)`, clamped to `[0, 255]`.
  The `rng.randint(0, 3)` call happens for every cell always, even when
  the value clamps — the rng sequence never depends on values.

### `grid` — property

A **snapshot** of the state: a new `list[list[int]]` (deep copy) on
every access. Rows and cells are shared with neither the engine's
internal state nor previous snapshots; mutating a snapshot never affects
the engine or any other snapshot.

## Invariants

- Determinism: two engines with identical `(seed, width, height)` and the
  same number of ticks produce identical grids. Different seeds —
  different states (at minimum the bottom row).
- After any `step()`: all cells in `[0, 255]`; every bottom-row cell in
  `[180, 255]`.
- Engines are independent: stepping one never changes another engine or
  any previously taken snapshot.
- No public names besides `FireEngine` (module constants are private).

Tests: `tests/fire_engine_test.py` (`bash scripts/run.sh test
tests/fire_engine_test.py`).
