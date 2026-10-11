# fire_engine (TASK-STANOK-CC-240 / FIRE-01)

Pure Doom Fire logic — palette + fire matrix + one propagation step. No
terminal escape codes, no file/socket I/O. Stdlib only: `random`.

## Contract

`src/fire_engine.py`

- `PALETTE` — a list of exactly 37 RGB tuples, the classic Doom fire palette
  (index 0 darkest `(0x07,0x07,0x07)` … index 36 brightest `(0xFF,0xFF,0xFF)`).

- `class FireField(width, height, rng=None)`
  A fire matrix stored as a flat list indexed `buffer[y * width + x]`, with
  `y=0` the top row and `y=height-1` the **source row**, seeded to `36`
  (`SOURCE_VALUE`). Every other cell starts at `0`.
  - `rng` is an injectable `random.Random`; when omitted it defaults to the
    module-level `random`. Injecting a seeded `random.Random(seed)` makes
    `step` fully deterministic.

- `FireField.step(wind=0)` — one bottom-up propagation pass, in place.
  For `y` from `height-1` down to `1`, for each `x` in `0..width-1`:
  - `src = buffer[y][x]`; if `src == 0` → `buffer[y-1][x] = 0`.
  - else `rand = rng.randint(0, 3)`; `dst = x - rand + 1 + wind`; if
    `0 <= dst < width` → `buffer[y-1][dst] = max(0, src - (rand & 1))`.
    An out-of-bounds `dst` is skipped — **no wrap**.
  - `wind` is clamped to `[-3, 3]`.
  The source row is only ever read, never written. Because the pass runs
  bottom-up and reads row `y` while writing row `y-1`, each row is computed
  from the row below it; within a row, later `x` values overwrite the same
  target column (last write wins), exactly as the algorithm specifies.

- `color_at(value) -> PALETTE[value]` — module-level. `value` is always
  `0..36` by construction.

## Determinism

`step` calls `rng.randint(0, 3)` exactly once per non-zero source pixel, in
row-major order (bottom row first). With a seeded `random.Random` the whole
frame is reproducible; tests pin seeds and assert exact rows.

## Tests

`tests/fire_engine_test.py` (pytest, run via
`scripts/run.sh test tests/fire_engine_test.py`)

- `PALETTE`: length 37, first/last entries, pinned intermediate entries, and
  the `(int,int,int)` byte-triple shape.
- `color_at`: returns `PALETTE[value]` at 0 / 18 / 36.
- Construction: source row seeded to 36, other rows 0, flat `y*width+x` layout.
- `step`: exact propagation for a seeded field; source row untouched; decay
  clamps at 0 (never negative, never exceeds the source); wind shifts the
  propagation symmetrically (`-1 / 0 / +1`) and is clamped to `[-3, 3]`;
  a zero source row stays zero; out-of-bounds `dst` is skipped without wrap.
