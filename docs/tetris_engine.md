# tetris_engine — contract (ticket CC-305, SPEC E1..E6)

`src/tetris_engine.py` — pure, deterministic tetris engine. stdlib-only
(`random`, `dataclasses`); no time, I/O, threads or mutable global state.

## API

- `new_game(seed, width, height) -> GameState` — fresh game with the first
  piece spawned top-centered. `ValueError` when `width < 2`, `height < 2` or
  `height` is odd.
- `try_move(state, dx) -> GameState | None` — horizontal shift; `None` when
  blocked by wall/stack or `dx == 0`.
- `try_rotate(state, direction) -> GameState | None` — 90° step, `1` clockwise,
  `-1` counter-clockwise. Wall-kicks `(0, +1, -1, +2, -2)`, first valid wins;
  `None` when no offset fits. Rotating O always succeeds with unchanged shape
  and position.
- `soft_drop(state) -> GameState | None` — one row down; `None` when the piece
  cannot fall.
- `hard_drop(state) -> GameState` — instant drop to the bottom of the fall
  range and lock there (scored like a normal lock).
- `tick(state) -> GameState` — gravity tick, **always** returns a state: one
  row down if the piece falls, otherwise lock + clear + spawn next.
- `is_game_over(state) -> bool`.

Impossible move/rotate/soft_drop return `None`. Once `game_over` is set, every
operation is a no-op returning the unchanged state (E4).

## State (frozen dataclass `GameState`)

`board` (H×W `list[list[int]]`, 0 or locked id 1..7), `piece` (matrix | None),
`piece_id` (1..7), `x`, `y` (board cell of the shape matrix top-left; cell
`(r,c)` occupies `board[y+r][x+c]`), `score`, `lines_cleared`, `level`,
`game_over`. Internal field `rng_state` carries the `random.Random(seed)`
cursor so each game draws one piece sequence from a single seeded generator.

Purity: no operation mutates its input; a returned board shares **no row
object** with the input board (deep copy on every returned state), and rows
produced by a line clear are pairwise distinct objects.

## Rules

- Pieces: I, O, T, S, Z, J, L as ids 1..7 with standard spawn matrices
  (I horizontal, T point-down). I spawns vertically only on boards narrower
  than 4 (the piece must fit the board at spawn).
- Rotation is exact 90° geometry (`ccw∘cw = identity`, 4× same direction =
  identity), including non-square matrices.
- Spawn collides → `game_over=True`, `piece=None`.
- Lock fills the piece cells; full rows are cleared; `SCORE_TABLE =
  {1:100, 2:300, 3:500, 4:800}`; `level = lines_cleared // 10 + 1`.
- Determinism: identical `seed` ⇒ identical trajectory; the sequence of pieces
  per game comes from one `Random(seed)`.

## Tests

`tests/tetris_engine_test.py` (E1..E6 pins, negatives included); the external
oracle `tests/tetris_engine_contract_test.py` runs the same contract.
Entrypoint: `bash scripts/run.sh test tests/tetris_engine_test.py` / `test --all`.
