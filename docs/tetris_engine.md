# tetris_engine — contract (CC-290)

Pure, deterministic Tetris rules simulator: first layer of the TETRIS3 wave
(no renderer/CLI yet; the terminal seam is closed by CC-292). No I/O, no
time, no network — stdlib only (`random`). Tests: `tests/tetris_engine_test.py`.

## Purity

Every public function is pure: it never mutates the input `State` or its
`board`/`piece`, and every returned `State` carries freshly copied
board/piece — no row or matrix object is shared with the input. The only
exception is the documented no-op path (after game over, `soft_drop`/`tick`
return the state unchanged).

## Public API

- `new_game(seed: int, width: int, height: int) -> State` — raises
  `ValueError` when `width < 2`, `height < 2`, or `height` is odd. Creates
  an empty board and spawns the first piece.
- `try_move(state, dx) -> State | None` — `dx` in `{-1, 1}`; a move into a
  wall, past the board boundary, or into an occupied cell returns `None`.
- `try_rotate(state, direction) -> State | None` — `direction`: `1`
  clockwise, `-1` counter-clockwise (90° matrix rotation). On collision the
  rotated piece is tried at x-offsets in the pinned order `(0, +1, -1, +2,
  -2)`; the first valid one wins; all invalid → `None`. O is invariant: its
  rotation yields the same matrix at the same position.
- `soft_drop(state) -> State | None` — one step down if possible, else
  `None` (locking happens via `tick`/`hard_drop`).
- `hard_drop(state) -> State` — falls to the first collision, then locks.
- `tick(state) -> State` — gravity: one step down, or lock if blocked.
- `is_game_over(state) -> bool`.

## State (frozen dataclass)

Constructor field order is the pinned CLI seam:

```
State(board, piece, piece_id, x, y, score=0, lines_cleared=0, level=1,
      game_over=False, rng_state=None)
```

- `board`: `list[list[int]]`, `height` rows × `width` columns; `0` empty,
  `1..7` a locked piece id. Dimensions are invariant under all operations.
- `piece`: active piece matrix (`0/1`) or `None`; `piece_id` `1..7`
  (`0` when `piece is None`); `x`, `y`: top-left corner on the board.
- `score`, `lines_cleared`, `level` (int), `game_over` (bool).
- `rng_state` (internal continuation, defaulted): the `getstate()` of the
  game's single `random.Random(seed)` — one `randrange(1, 8)` per spawn.
  `None` (only from hand-constructed States) means "fresh `Random(0)`".
  Identical seed ⇒ identical piece sequence and trajectory.

Tests may construct `State` directly for scenarios (e.g. a board with a
partially filled row).

## Rules (pinned)

- Pieces 1..7, starting orientations:
  I `[[1,1,1,1]]`, O `[[1,1],[1,1]]`, T `[[1,1,1],[0,1,0]]`,
  S `[[0,1,1],[1,1,0]]`, Z `[[1,1,0],[0,1,1]]`, J `[[1,0,0],[1,1,1]]`,
  L `[[0,0,1],[1,1,1]]` (module constant `PIECES`).
- Spawn: `x = (width - len(piece[0])) // 2`, `y = 0`; a spawn colliding
  with the board sets `game_over = True`.
- Lock: piece cells are written as `piece_id`, fully filled rows are
  removed (board height preserved), `score += SCORE_TABLE[k]` with
  `SCORE_TABLE = {1:100, 2:300, 3:500, 4:800}`, `lines_cleared += k`,
  `level = lines_cleared // 10 + 1`, then the next piece spawns (or game
  over).
- After game over: `try_move`/`try_rotate`/`hard_drop` → `None`;
  `soft_drop`/`tick` return the state unchanged; `is_game_over` → `True`.
- `piece=None` (piece_id 0) is a legal state: `try_move`/`try_rotate`/
  `soft_drop` → `None`; `tick` and `hard_drop` spawn the next piece from
  the carried rng (or end the game).
