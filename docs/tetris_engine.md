# tetris_engine — module contract (CC-277)

A standard-tetris engine built from pure, deterministic functions:
no I/O, no time, no global mutable state. Every public function takes an
immutable state snapshot and returns a **new** state; the input state is
never mutated (copy-on-write — states never share mutable structure).
Tests: `tests/tetris_engine_test.py`.

## Constants (pinned)

| Name | Value |
|---|---|
| `DEFAULT_WIDTH` / `DEFAULT_HEIGHT` | `10` / `20` |
| `SCORE_TABLE` | `{1: 100, 2: 300, 3: 500, 4: 800}` (points per 1–4 lines cleared at once) |
| `KICKS` | `(0, 1, -1, 2, -2)` — wall-kick x-offsets tried in this order on rotation |
| `PIECES` | `dict` id → 4 rotation-state matrices; ids `1..7 = I,O,T,S,Z,J,L`; each state is the previous one rotated 90° CW; `O` is invariant (its 4 states are identical); matrices contain only `0`/`1` |

## State — `GameState` (frozen dataclass)

| Field | Meaning |
|---|---|
| `board` | `list[list[int]]`, `height` rows × `width` cols; `0` empty, `1..7` locked piece id |
| `piece_id`, `piece_matrix`, `piece_rot` | active piece: id, its current rotation matrix, index into `PIECES[piece_id]` (0..3) |
| `x`, `y` | top-left corner of `piece_matrix` on the board |
| `rng_state` | `random.Random.getstate()` tuple; the whole piece sequence is produced by one `random.Random(seed)` carried in the state |
| `score`, `lines_cleared`, `level` | `level = lines_cleared // 10 + 1` |
| `game_over` | `bool` — spawn collision flag |

Coordinates: `x` is a column, `y` a row (row 0 = top). A position is invalid
if any filled matrix cell falls outside the left/right/bottom borders or on a
non-zero board cell.

## Functions

- `new_game(seed, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT) -> GameState`
  Empty field; first piece spawned at the top-center spawn point from
  `random.Random(seed)`. Same seed ⇒ identical piece sequence. If the field
  is too small for the spawn, the state starts with `game_over=True`.

- `try_move(state, dx) -> GameState | None`
  Horizontal shift. `None` when the target position is invalid.

- `try_rotate(state, direction) -> GameState | None`
  `+1` = clockwise, `-1` = counter-clockwise. The new rotation is tried at
  `x + kx` for `kx` in `KICKS` order; the first fit wins. `None` if no offset fits.

- `soft_drop(state) -> GameState` / `tick(state) -> GameState`
  One step down; if the piece already rests, perform lock+clear+spawn.

- `hard_drop(state) -> GameState`
  Instant drop to the lowest valid position, then lock+clear+spawn.

- `is_game_over(state) -> bool`
  True when a spawn collided with the board.

**Lock procedure** (internal, used by `soft_drop`/`hard_drop`/`tick`): write
the piece cells to the board as the piece id, remove full rows (rows above
shift down), add `SCORE_TABLE[n]` for `n` rows cleared, recompute
`lines_cleared`/`level`, then spawn the next piece from `rng_state`; a
colliding spawn sets `game_over=True`.

**Game over is absorbing:** in a `game_over` state every operation
(`try_move`, `try_rotate`, `soft_drop`, `hard_drop`, `tick`) is a no-op
returning the same state.

## Purity

No function mutates its input state or shares mutable structure with the
state it returns; states are safe to keep as snapshots and compare by value.
