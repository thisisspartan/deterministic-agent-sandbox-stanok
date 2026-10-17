"""CC-282 — reference tests for src/tetris_engine.py.

Covers the ticket contract: pinned constants, pure functions, determinism,
wall-kicks, lock/clear/scoring, game over, and immutability of inputs.
"""
import copy

import tetris_engine as te


# ---------------------------------------------------------------- helpers

def make_state(piece_id, rot=0, x=0, y=0, board=None, width=10, height=20,
               seed=1, rng_calls=1, score=0, lines_cleared=0, level=1,
               game_over=False):
    """Construct a state directly (test fixture for positional edge cases)."""
    if board is None:
        board = [[0] * width for _ in range(height)]
    return te.State(
        seed=seed, width=width, height=height, board=board,
        piece_id=piece_id, piece=te.PIECES[piece_id][rot], rot=rot, x=x, y=y,
        rng_calls=rng_calls, score=score, lines_cleared=lines_cleared,
        level=level, game_over=game_over,
    )


def filled_board(width, height, cells, value=8):
    board = [[0] * width for _ in range(height)]
    for (y, x) in cells:
        board[y][x] = value
    return board


def piece_sequence(seed, n=5):
    """First n piece ids of a game played via hard_drop only."""
    st = te.new_game(seed)
    ids = []
    for _ in range(n):
        ids.append(st.piece_id)
        st = te.hard_drop(st)
    return ids


# ---------------------------------------------------------------- 1. determinism

def test_same_seed_same_sequence():
    assert piece_sequence(42) == piece_sequence(42)
    assert piece_sequence(7) == piece_sequence(7)


def test_different_seed_different_sequence():
    assert piece_sequence(42) != piece_sequence(1234)


# ---------------------------------------------------------------- 2. PIECES

def test_pieces_table_shape():
    assert set(te.PIECES) == {1, 2, 3, 4, 5, 6, 7}
    for pid, states in te.PIECES.items():
        assert len(states) == 4, f"piece {pid} must have 4 rotation states"
        for m in states:
            widths = {len(row) for row in m}
            assert len(widths) == 1, "matrix must be rectangular"
            ones = sum(v for row in m for v in row)
            assert ones == 4, f"piece {pid} must occupy 4 cells"
            for row in m:
                for v in row:
                    assert v in (0, 1), "matrix cells are 0/1"


def test_o_piece_invariant():
    states = te.PIECES[2]
    assert all(tuple(tuple(r) for r in m) == states[0] for m in states)


def test_constants_pinned():
    assert te.DEFAULT_WIDTH == 10
    assert te.DEFAULT_HEIGHT == 20
    assert te.SCORE_TABLE == {1: 100, 2: 300, 3: 500, 4: 800}
    assert te.KICKS == (0, 1, -1, 2, -2)


# ---------------------------------------------------------------- 3. try_move

def test_try_move_blocked_at_wall():
    st = make_state(3, rot=0, x=0, y=5)  # T at the left wall
    assert te.try_move(st, -1) is None


def test_try_move_blocked_over_occupied():
    board = filled_board(10, 20, {(6, 4)})  # occupied cell under T's stem target
    st = make_state(3, rot=0, x=2, y=5, board=board)  # T spans cols 2..4
    assert te.try_move(st, 1) is None


def test_try_move_valid_shifts_and_preserves_original():
    st = make_state(3, rot=0, x=2, y=5)
    moved = te.try_move(st, 1)
    assert moved is not None
    assert moved.x == st.x + 1
    assert st.x == 2  # original untouched
    assert moved.board == st.board


# ---------------------------------------------------------------- 4. try_rotate

def test_try_rotate_wall_kick():
    # vertical I at x=8 on a 10-wide board: rotating to horizontal needs kick -2
    st = make_state(1, rot=1, x=8, y=0)
    rotated = te.try_rotate(st, 1)
    assert rotated is not None
    assert rotated.piece_id == 1
    assert rotated.x == 6  # 6 + 4 == 10 fits exactly
    assert st.x == 8 and st.rot == 1  # original untouched


def test_try_rotate_impossible():
    # S blocked by filled cells for every kick offset in KICKS
    board = filled_board(5, 5, {(0, 0), (0, 1), (0, 2), (1, 4)})
    st = make_state(4, rot=0, x=2, y=0, board=board, width=5, height=5)
    assert te.try_rotate(st, 1) is None
    assert te.try_rotate(st, -1) is None


def test_try_rotate_plain_rotation():
    st = make_state(3, rot=0, x=4, y=5)
    rotated = te.try_rotate(st, 1)
    assert rotated is not None
    assert rotated.rot == 1
    assert rotated.piece == te.PIECES[3][1]
    assert st.rot == 0  # original untouched


# ---------------------------------------------------------------- 5. tick

def test_tick_moves_piece_down_by_one():
    st = make_state(3, rot=0, x=4, y=5)
    fell = te.tick(st)
    assert fell.y == st.y + 1
    assert fell.board == st.board  # no lock yet
    assert st.y == 5


def test_tick_locks_on_rest_and_spawns_next():
    st = make_state(3, rot=0, x=4, y=18)  # T bottom edge at row 19
    fell = te.tick(st)
    # locked cells carry the piece id
    assert fell.board[19][5] == 3
    assert fell.board[18][4] == 3 and fell.board[18][6] == 3
    # next piece spawned at the top
    assert fell.piece_id in (1, 2, 3, 4, 5, 6, 7)
    assert fell.y == 0
    assert fell.game_over is False
    # original state untouched
    assert st.board[19] == [0] * 10
    assert st.y == 18


# ---------------------------------------------------------------- 6. line clearing

def test_full_row_cleared_partial_row_remains():
    board = filled_board(10, 20, {(19, x) for x in range(2, 10)})
    st = make_state(2, rot=0, x=0, y=18, board=board)  # O completes the row
    fell = te.tick(st)
    assert fell.lines_cleared == 1
    # the O's top row shifted down to the bottom; the completed row is gone
    assert fell.board[19][0] == 2 and fell.board[19][1] == 2
    # only the O's two surviving cells remain on the whole board
    assert sum(1 for row in fell.board for v in row if v) == 2
    assert fell.board[0] == [0] * 10  # fresh empty row on top
    assert len(fell.board) == 20


def test_incomplete_row_not_cleared():
    board = filled_board(10, 20, {(19, x) for x in range(3, 10)})
    st = make_state(2, rot=0, x=0, y=18, board=board)  # O leaves a gap
    fell = te.tick(st)
    assert fell.lines_cleared == 0
    assert fell.board[19][2] == 0  # gap preserved


# ---------------------------------------------------------------- 7. score & level

def test_score_single_line():
    board = filled_board(10, 20, {(19, x) for x in range(2, 10)})
    st = make_state(2, rot=0, x=0, y=18, board=board)
    fell = te.tick(st)
    assert fell.score == 100


def test_score_tetris_four_lines():
    board = filled_board(10, 20, {(y, x) for y in range(16, 20) for x in range(1, 10)})
    st = make_state(1, rot=1, x=0, y=16, board=board)  # vertical I completes 4 rows
    fell = te.hard_drop(st)
    assert fell.lines_cleared == 4
    assert fell.score == 800
    assert fell.level == 1


def test_level_grows_every_ten_lines():
    board = filled_board(10, 20, {(19, x) for x in range(2, 10)})
    st = make_state(2, rot=0, x=0, y=18, board=board, lines_cleared=9, score=900)
    fell = te.tick(st)
    assert fell.lines_cleared == 10
    assert fell.level == 2
    assert fell.score == 1000


# ---------------------------------------------------------------- 8. hard_drop

def test_hard_drop_to_floor():
    st = make_state(2, rot=0, x=3, y=0)
    dropped = te.hard_drop(st)
    assert dropped.board[19][3] == 2 and dropped.board[19][4] == 2
    assert dropped.board[18][3] == 2 and dropped.board[18][4] == 2
    assert dropped.y == 0  # next piece spawned
    assert st.board[19] == [0] * 10  # original untouched


def test_hard_drop_onto_stack():
    cells = {(19, x) for x in range(10) if x not in (3, 4)}
    cells |= {(18, 3), (18, 4)}
    board = filled_board(10, 20, cells)
    st = make_state(2, rot=0, x=3, y=0, board=board)
    dropped = te.hard_drop(st)
    # rests on top of the stack at row 17, nothing cleared
    assert dropped.board[17][3] == 2 and dropped.board[17][4] == 2
    assert dropped.lines_cleared == 0


# ---------------------------------------------------------------- 9. game over

def test_game_over_on_blocked_spawn():
    # rows 0-1 are filled except column 0 (incomplete, so nothing clears);
    # O locks at the bottom, then every possible spawn collides with row 0
    board = filled_board(10, 4, {(y, x) for y in (0, 1) for x in range(1, 10)})
    st = make_state(2, rot=0, x=8, y=2, board=board, height=4)
    fell = te.tick(st)
    assert fell.lines_cleared == 0
    assert fell.game_over is True
    assert te.is_game_over(fell) is True


def test_operations_after_game_over_are_noops():
    st = make_state(3, game_over=True)
    assert te.is_game_over(st) is True
    for fn, args in ((te.try_move, (1,)), (te.try_rotate, (1,)),
                     (te.tick, ()), (te.soft_drop, ()), (te.hard_drop, ())):
        result = fn(st, *args)
        assert result.game_over is True
        assert result.board == st.board
        assert result.piece_id == st.piece_id
        assert result.x == st.x and result.y == st.y
    assert te.is_game_over(te.new_game(1)) is False


# ---------------------------------------------------------------- 10. purity

def test_functions_do_not_mutate_input_state():
    st = te.new_game(11)
    snapshot = copy.deepcopy(st)
    te.try_move(st, 1)
    te.try_rotate(st, 1)
    te.tick(st)
    te.soft_drop(st)
    te.hard_drop(st)
    assert st.board == snapshot.board
    assert st.piece_id == snapshot.piece_id
    assert st.piece == snapshot.piece
    assert (st.x, st.y, st.rot) == (snapshot.x, snapshot.y, snapshot.rot)
    assert (st.score, st.lines_cleared, st.level) == (
        snapshot.score, snapshot.lines_cleared, snapshot.level)
    assert st.game_over == snapshot.game_over


def test_soft_drop_falls_or_locks():
    st = make_state(3, rot=0, x=4, y=5)
    fell = te.soft_drop(st)
    assert fell.y == st.y + 1
    st2 = make_state(3, rot=0, x=4, y=18)
    locked = te.soft_drop(st2)
    assert locked.board[19][5] == 3
    assert locked.y == 0
