# tetris_engine — pure deterministic tetris core (CC-302)

`src/tetris_engine.py` — stdlib only (`random`, `dataclasses`); no time, no
I/O, no global mutable state. Every function is pure: it never mutates its
input state and the returned board shares no row (identity) with the input.

## API

- `new_game(seed, width, height) -> GameState` — empty board, first piece
  spawned. Raises `ValueError` when `width < 2`, `height < 2`, or `height`
  is odd.
- `try_move(state, dx) -> GameState | None` — horizontal shift; `None` if
  blocked by wall or locked cells.
- `try_rotate(state, direction) -> GameState | None` — 90° step
  (`1` = CW, `-1` = CCW). Wall-kicks try horizontal offsets `(0, +1, -1, +2, -2)`
  in order; the first valid one wins; `None` if none fits. Rotating O always
  succeeds with the same shape and position.
- `soft_drop(state) -> GameState | None` — one row down; `None` if blocked.
- `hard_drop(state) -> GameState` — instant lock at the bottom of the fall.
- `tick(state) -> GameState` — gravity: one row down, or lock + clear + spawn.
  Never returns `None`.
- `is_game_over(state) -> bool`.

## State

`GameState` is a frozen dataclass with pinned attributes: `board`
(`list[list[int]]`, H×W, 0 empty or piece id 1..7), `piece` (matrix | None),
`piece_id`, `x`, `y`, `score`, `lines_cleared`, `level`, `game_over`. The
internal `rng_state` field carries the state of the game's single
`random.Random(seed)` inside the immutable state, so branching from one
state never leaks randomness between branches.

## Rules

- Pieces: I,O,T,S,Z,J,L = ids 1..7, canonical spawn matrices (minimal
  bounding boxes); rotation rotates the matrix 90°.
- Spawn: top row, horizontally centered. A spawn collision sets
  `game_over=True`; afterwards every operation is a no-op returning the
  unchanged state.
- Lock: the piece writes its id into the board; fully filled rows are
  removed and fresh empty rows appear on top — every row of a returned
  board is a distinct object (no aliasing).
- Scoring: `SCORE_TABLE = {1:100, 2:300, 3:500, 4:800}`;
  `level = lines_cleared // 10 + 1`.
- Determinism: one piece sequence per game from one `random.Random(seed)`;
  equal seeds give identical trajectories (pieces and positions).

Tests: `tests/tetris_engine_test.py` (reference), `tests/tetris_engine_contract_test.py`
(calibrated oracle).
