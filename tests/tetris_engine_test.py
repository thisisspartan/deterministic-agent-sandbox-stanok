"""CC-290 — tetris_engine reference tests: the pinned contract of the pure
deterministic Tetris simulator.

Every test below pins one clause of the ticket contract (docs/tetris_engine.md):
public function names, State field order, piece shapes and spawn positions,
rotation + wall-kick order, drop/lock semantics, the score table, level
formula, game-over no-ops, the piece=None state, purity (no mutation of the
input, no shared rows in the output), and determinism from a single
Random(seed) per game. No TTY, no subprocess, no I/O.
"""

import copy
import random

import pytest

import tetris_engine as te


# ---------------------------------------------------------------------------
# helpers: direct State construction (allowed by the contract for scenarios)
# ---------------------------------------------------------------------------

def _empty_board(width=10, height=20):
    return [[0] * width for _ in range(height)]


def _matrix(shape_id):
    return [row[:] for row in te.PIECES[shape_id]]


def _state(board, piece, piece_id, x, y, **kw):
    # Constructor field order is the pinned seam: board, piece, piece_id,
    # x, y, score, lines_cleared, level, game_over.
    return te.State(board, piece, piece_id, x, y, **kw)


def _spawn_sequence(seed, width=10, height=40, count=20):
    """piece_id of the first `count` spawned pieces, plain hard-drop play.

    A 40-row board so 20 hard-dropped pieces cannot stack up to the spawn
    area — on 10x20 the same play legitimately ends around spawn 12.
    """
    state = te.new_game(seed, width, height)
    ids = [state.piece_id]
    for _ in range(count - 1):
        state = te.hard_drop(state)
        assert state is not None
        ids.append(state.piece_id)
    return ids


def _count_full_rows(board):
    return sum(1 for row in board if all(cell != 0 for cell in row))


# ---------------------------------------------------------------------------
# 1. determinism
# ---------------------------------------------------------------------------

def test_identical_seed_identical_trajectory():
    a = te.new_game(7, 10, 20)
    b = te.new_game(7, 10, 20)
    for _ in range(30):
        a = te.tick(a)
        b = te.tick(b)
    assert a.board == b.board
    assert a.score == b.score
    assert a.piece == b.piece
    assert (a.piece_id, a.x, a.y) == (b.piece_id, b.x, b.y)
    assert (a.lines_cleared, a.level, a.game_over) == (b.lines_cleared, b.level, b.game_over)


def test_different_seed_different_piece_sequence():
    assert _spawn_sequence(7) != _spawn_sequence(8)


def test_spawn_position_and_shape_pinned():
    # Spawn: x = (width - len(piece[0])) // 2, y = 0; the piece comes from
    # the game's single Random(seed) via randrange(1, 8).
    expected_id = random.Random(7).randrange(1, 8)
    state = te.new_game(7, 10, 20)
    assert state.piece_id == expected_id
    assert state.piece == te.PIECES[expected_id]
    assert state.x == (10 - len(te.PIECES[expected_id][0])) // 2
    assert state.y == 0
    assert not state.game_over
    assert not te.is_game_over(state)


# ---------------------------------------------------------------------------
# 2. purity: no mutation of the input, no shared rows in the output
# ---------------------------------------------------------------------------

def test_functions_are_pure():
    state = te.new_game(1, 10, 20)
    board_before = copy.deepcopy(state.board)
    piece_before = copy.deepcopy(state.piece)
    xy_before = (state.x, state.y)
    orig_board_rows = list(state.board)
    orig_piece_rows = list(state.piece)

    results = [
        te.try_move(state, 1),
        te.try_move(state, -1),
        te.try_rotate(state, 1),
        te.soft_drop(state),
        te.hard_drop(state),
        te.tick(state),
    ]
    for out in results:
        assert out is not None
        # the input state was not mutated
        assert state.board == board_before
        assert state.piece == piece_before
        assert (state.x, state.y) == xy_before
        # the returned board shares no row object with the input board
        assert out.board is not state.board
        assert len(out.board) == len(orig_board_rows)
        for row, orig in zip(out.board, orig_board_rows):
            assert row is not orig
        # the returned piece shares no row object with the input piece
        if out.piece is not None:
            for row, orig in zip(out.piece, orig_piece_rows):
                assert row is not orig


# ---------------------------------------------------------------------------
# 3. movement into wall / boundary / occupied cell → None
# ---------------------------------------------------------------------------

def test_move_into_wall_or_occupied_cell_returns_none():
    o = _matrix(2)  # O, 2x2
    # left wall: piece at x=0 cannot move left
    assert te.try_move(_state(_empty_board(), [r[:] for r in o], 2, 0, 5), -1) is None
    # right boundary: piece at x=8 cannot move right (would reach x=9,10)
    assert te.try_move(_state(_empty_board(), [r[:] for r in o], 2, 8, 5), 1) is None
    # occupied cell (after a lock): target cell (3,5) is taken
    board = _empty_board()
    board[5][3] = 4
    assert te.try_move(_state(board, [r[:] for r in o], 2, 1, 5), 1) is None
    # a legal move succeeds and lands the piece one column over
    moved = te.try_move(_state(_empty_board(), [r[:] for r in o], 2, 4, 5), 1)
    assert moved is not None and moved.x == 5


# ---------------------------------------------------------------------------
# 4. rotation and wall-kicks
# ---------------------------------------------------------------------------

def test_rotate_blocked_by_wall_kicks_out():
    # vertical I hugging the right wall area (x=8, board width 10): the
    # flat orientation only fits after a wall-kick; the first valid offset
    # in the pinned order (0, +1, -1, +2, -2) is -2 → x=6.
    vertical_i = [[1], [1], [1], [1]]
    out = te.try_rotate(_state(_empty_board(), [r[:] for r in vertical_i], 1, 8, 5), 1)
    assert out is not None
    assert out.piece == [[1, 1, 1, 1]]
    assert out.x == 6 and out.y == 5


def test_rotate_wall_kick_order_first_valid_wins():
    # x=7: kicks 0 and +1 are out of bounds, -1 is valid → x=6 (not -2).
    vertical_i = [[1], [1], [1], [1]]
    out = te.try_rotate(_state(_empty_board(), [r[:] for r in vertical_i], 1, 7, 5), 1)
    assert out is not None and out.x == 6
    # x=5: kick 0 is already valid → position unchanged
    out = te.try_rotate(_state(_empty_board(), [r[:] for r in vertical_i], 1, 5, 5), 1)
    assert out is not None and out.x == 5


def test_rotate_all_kicks_invalid_returns_none():
    # vertical I exactly at the right wall (x=9): even kick -2 lands at
    # x=7, spanning columns 7..10 — out of bounds; every kick fails.
    vertical_i = [[1], [1], [1], [1]]
    assert te.try_rotate(_state(_empty_board(), [r[:] for r in vertical_i], 1, 9, 5), 1) is None


def test_rotate_o_is_invariant():
    o = _matrix(2)
    for direction in (1, -1):
        out = te.try_rotate(_state(_empty_board(), [r[:] for r in o], 2, 4, 5), direction)
        assert out is not None
        assert out.piece == o
        assert out.x == 4 and out.y == 5


def test_rotate_directions_are_90_degree_matrix_rotations():
    t = _matrix(3)  # T = [[1,1,1],[0,1,0]]
    out = te.try_rotate(_state(_empty_board(), [r[:] for r in t], 3, 4, 5), 1)
    assert out is not None and out.piece == [[0, 1], [1, 1], [0, 1]]
    out = te.try_rotate(_state(_empty_board(), [r[:] for r in t], 3, 4, 5), -1)
    assert out is not None and out.piece == [[1, 0], [1, 1], [1, 0]]


def test_rotate_into_occupied_cell_without_valid_kick_returns_none():
    # horizontal I at y=5, blocked below-left so the vertical orientation
    # collides with the board at every kick offset in range.
    board = _empty_board()
    for x in range(0, 10):
        board[6][x] = 5  # a full row directly under the piece
    flat_i = _matrix(1)
    assert te.try_rotate(_state(board, [r[:] for r in flat_i], 1, 3, 5), 1) is None


# ---------------------------------------------------------------------------
# 5. soft_drop: a step down, None at the floor
# ---------------------------------------------------------------------------

def test_soft_drop_steps_down_then_none_at_floor():
    state = te.new_game(1, 10, 20)
    y0 = state.y
    stepped = te.soft_drop(state)
    assert stepped is not None and stepped.y == y0 + 1
    assert stepped.piece == state.piece and stepped.x == state.x
    # drop the piece to the floor with soft_drop steps, then it must stop
    while True:
        nxt = te.soft_drop(state)
        if nxt is None:
            break
        state = nxt
    assert te.soft_drop(state) is None
    # the piece is one row above the bottom for a 1-row piece: verify by
    # locking it via tick and finding its id in the bottom row
    locked = te.tick(state)
    assert any(cell == state.piece_id for cell in locked.board[-1])


# ---------------------------------------------------------------------------
# 6. hard_drop: lands on the floor/board, then the next piece spawns
# ---------------------------------------------------------------------------

def test_hard_drop_lands_and_spawns_next_from_same_rng():
    seed = 42
    rng = random.Random(seed)
    first_id = rng.randrange(1, 8)
    second_id = rng.randrange(1, 8)

    state = te.new_game(seed, 10, 20)
    assert state.piece_id == first_id
    landed = te.hard_drop(state)
    assert landed is not None
    # the piece is embedded at the bottom of the board
    rows = len(state.piece)
    land_y = 20 - rows
    for py, prow in enumerate(state.piece):
        for px, cell in enumerate(prow):
            if cell:
                assert landed.board[land_y + py][state.x + px] == first_id
    # the next piece comes from the same seed's rng sequence
    assert landed.piece_id == second_id
    assert landed.piece == te.PIECES[second_id]
    assert landed.x == (10 - len(te.PIECES[second_id][0])) // 2 and landed.y == 0

    # hard_drop onto an already-occupied column lands on top of the stack
    stacked = te.hard_drop(landed)
    assert stacked is not None
    assert _count_full_rows(stacked.board) == 0  # nothing was cleared here
    assert stacked.piece is not None


# ---------------------------------------------------------------------------
# 7. line clearing and the pinned score table
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("k,expected_score", [(1, 100), (2, 300), (3, 500), (4, 800)])
def test_line_clear_scores_follow_the_table(k, expected_score):
    # k bottom rows filled except column 0; a vertical I hard-dropped into
    # column 0 completes exactly those k rows.
    board = _empty_board()
    for row in board[20 - k:]:
        for x in range(1, 10):
            row[x] = 3
    vertical_i = [[1], [1], [1], [1]]
    state = _state(board, vertical_i, 1, 0, 0)
    out = te.hard_drop(state)
    assert out is not None
    assert out.score == expected_score
    assert out.lines_cleared == k
    assert len(out.board) == 20  # board height preserved
    assert all(len(row) == 10 for row in out.board)
    assert _count_full_rows(out.board) == 0  # the full rows were removed
    assert out.level == 1


def test_partial_row_is_not_cleared():
    board = _empty_board()
    for x in range(1, 9):  # bottom row missing TWO cells
        board[19][x] = 3
    flat_i = _matrix(1)
    state = _state(board, flat_i, 1, 0, 0)
    out = te.hard_drop(state)
    assert out is not None
    assert out.score == 0 and out.lines_cleared == 0
    assert _count_full_rows(out.board) == 0


# ---------------------------------------------------------------------------
# 8. level progression
# ---------------------------------------------------------------------------

def test_level_tracks_lines_cleared():
    board = _empty_board()
    for x in range(1, 10):
        board[19][x] = 6
    vertical_i = [[1], [1], [1], [1]]
    state = _state(board, vertical_i, 1, 0, 0, lines_cleared=9, level=1)
    out = te.hard_drop(state)
    assert out is not None
    assert out.lines_cleared == 10
    assert out.level == out.lines_cleared // 10 + 1 == 2


# ---------------------------------------------------------------------------
# 9. game over
# ---------------------------------------------------------------------------

def test_game_over_on_blocking_spawn_and_noops_after():
    board = _empty_board()
    for x in range(10):
        board[0][x] = 7  # any spawn collides with a full top row
    state = _state(board, None, 0, 0, 0, rng_state=random.Random(3).getstate())
    over = te.tick(state)  # tick with piece=None spawns → spawn collides
    assert te.is_game_over(over) is True
    assert over.game_over is True
    # after game_over: try_move/try_rotate/hard_drop → None
    assert te.try_move(over, 1) is None
    assert te.try_move(over, -1) is None
    assert te.try_rotate(over, 1) is None
    assert te.hard_drop(over) is None
    # soft_drop/tick return the state unchanged
    assert te.soft_drop(over) == over
    assert te.tick(over) == over
    assert te.is_game_over(over) is True


def test_game_over_reached_through_play():
    # a narrow board fills up until a spawn collides
    state = te.new_game(7, 2, 2)
    steps = 0
    while not te.is_game_over(state) and steps < 200:
        state = te.hard_drop(state)
        assert state is not None
        steps += 1
    assert te.is_game_over(state) is True
    assert te.try_move(state, 1) is None
    assert te.soft_drop(state) == state


# ---------------------------------------------------------------------------
# 10. new_game validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "seed,width,height",
    [(1, 1, 20), (1, 0, 20), (1, 10, 1), (1, 10, 3), (1, 10, 0), (1, 10, -2)],
)
def test_new_game_rejects_invalid_dimensions(seed, width, height):
    with pytest.raises(ValueError):
        te.new_game(seed, width, height)


def test_new_game_accepts_valid_minimal_dimensions():
    state = te.new_game(1, 2, 2)
    assert len(state.board) == 2 and all(len(row) == 2 for row in state.board)
    assert state.piece is not None and 1 <= state.piece_id <= 7
    assert state.score == 0 and state.lines_cleared == 0 and state.level == 1
    assert state.game_over is False


# ---------------------------------------------------------------------------
# 11. size invariants after an arbitrary series of operations
# ---------------------------------------------------------------------------

def test_board_dimensions_invariant_under_arbitrary_operations():
    width, height = 10, 20
    state = te.new_game(7, width, height)

    def check(tag):
        assert len(state.board) == height, tag
        assert all(len(row) == width for row in state.board), tag

    ops = [
        lambda s: te.try_move(s, -1),
        lambda s: te.try_move(s, 1),
        lambda s: te.try_rotate(s, 1),
        lambda s: te.try_rotate(s, -1),
        lambda s: te.soft_drop(s),
        lambda s: te.tick(s),
    ]
    for step in range(120):
        if te.is_game_over(state):
            break
        if step % 7 == 6:
            state = te.hard_drop(state)
            assert state is not None
        else:
            nxt = ops[step % len(ops)](state)
            if nxt is not None:
                state = nxt
        check(f"after step {step}")


# ---------------------------------------------------------------------------
# piece=None is a legal state (piece_id 0)
# ---------------------------------------------------------------------------

def test_piece_none_state_semantics():
    state = _state(_empty_board(), None, 0, 0, 0, rng_state=random.Random(11).getstate())
    assert te.try_move(state, 1) is None
    assert te.try_move(state, -1) is None
    assert te.try_rotate(state, 1) is None
    assert te.try_rotate(state, -1) is None
    assert te.soft_drop(state) is None
    # tick and hard_drop spawn the next piece from the carried rng
    rng = random.Random(11)
    expected_id = rng.randrange(1, 8)
    spawned = te.tick(state)
    assert spawned.piece_id == expected_id
    assert spawned.piece == te.PIECES[expected_id]
    assert spawned.x == (10 - len(te.PIECES[expected_id][0])) // 2 and spawned.y == 0
    hd = te.hard_drop(state)
    assert hd is not None and hd.piece_id == expected_id  # same carried rng state


# ---------------------------------------------------------------------------
# tick: gravity steps down, then locks
# ---------------------------------------------------------------------------

def test_tick_gravity_steps_then_locks():
    state = te.new_game(1, 10, 20)
    pid = state.piece_id
    rows = len(state.piece)
    for _ in range(20):
        nxt = te.tick(state)
        state = nxt
        assert len(state.board) == 20
    # after enough ticks the first piece must have locked into the board
    assert any(cell == pid for row in state.board for cell in row)
    # and a new piece is in play (or the game is over)
    assert te.is_game_over(state) or state.piece is not None
