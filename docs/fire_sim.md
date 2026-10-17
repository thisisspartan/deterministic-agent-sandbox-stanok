# fire_sim — simulation + palette (`src/fire_sim.py`)

Stage 1 of 3 of the console-fire program: **pure numerics only** — no rendering,
no CLI, no IO of any kind, no module-level RNG, no global state, no time.
The renderer and CLI (later tickets) are built on top of these names, so every
public name below is a contract, pinned by `tests/fire_sim_test.py`.

## Constants

| Name | Value | Meaning |
|---|---|---|
| `DEFAULT_SEED` | `1` | default seed for later stages |
| `IGNITION_LOW` | `0.85` | base-row values are re-ignited into `[IGNITION_LOW, 1.0]` |
| `COOL_LOW` / `COOL_HIGH` | `0.02` / `0.18` | per-step cooling factor bounds |
| `EMPTY_THRESHOLD` | `0.05` | heat below this is an empty cell (`heat_to_rgb` -> `None`) |

## Functions

`new_field(width: int, height: int) -> list[list[float]]`
: A cold field: `height` rows x `width` columns, all values in `[0, 1]`
  (row 0 is the top, the last row is the combustion zone).
  `ValueError` if `width < 1` or `height < 1`.

`advance(field: list[list[float]], rng: random.Random) -> list[list[float]]`
: One simulation step. **Pure**: never mutates `field`; returns a new field of
  the same shape. The bottom row is re-ignited each step into
  `[IGNITION_LOW, 1.0]`. Every other cell: `next = cur * (1 - cool) + bleed * below`
  where `cool` is drawn from `[COOL_LOW, COOL_HIGH]` and `bleed` (the upward
  bleed from the cell directly below, read from the OLD field) is drawn from
  internal bounds kept below the mean cooling factor — so heat decays
  geometrically with height while flames still reach upward. All values are
  clamped to `[0, 1]`. rng draws happen in a fixed row-major order.

`simulate(seed: int, width: int, height: int, n: int) -> list[list[list[float]]]`
: `n` successive fields starting from `new_field(width, height)`; element `i`
  is the field after `i + 1` advances. All randomness comes from a single
  `random.Random(seed)`. `ValueError` if `n < 1` (invalid dimensions propagate
  from `new_field`).

`heat_to_rgb(heat: float, rng: random.Random) -> tuple[int, int, int] | None`
: `heat` outside `[0, 1]` -> `ValueError`. `heat < EMPTY_THRESHOLD` -> `None`
  (empty cell). Otherwise a 24-bit RGB from linear interpolation between the
  gradient stops dark red -> orange -> yellow -> near-white (as heat
  approaches 1.0), plus a small per-channel jitter drawn from `rng`; each
  channel clamped to `0..255`.

## Determinism rule (the core contract)

- same seed + same dimensions -> identical fields;
- same heat value + same rng state -> identical RGB.

All randomness flows through an explicit `random.Random` (created only inside
`simulate` from `seed`). No module-level RNG, no global state, no time, no IO.

## Run the tests

`bash scripts/run.sh test tests/fire_sim_test.py` — or the whole suite:
`bash scripts/run.sh test --all`. Smoke: `bash scripts/run.sh smoke src/fire_sim.py`.
