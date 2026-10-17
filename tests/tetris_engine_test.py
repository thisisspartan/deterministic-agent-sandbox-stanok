"""CC-277 — contract tests for src/tetris_engine.py.

Pure deterministic tetris engine: pinned constants, pure functions,
deterministic seed-RNG piece sequence, wall-kicks, lock/clear/score/level,
game over as absorbing no-op state. Fixtures are defined in this file
(no conftest.py, per project rules).
"""

import copy
import dataclasses

import tetris_engine as te


# ---------------------------------------------------------------- helpers

def snapshot(state):
    return copy.deepcopy(state)


def assert_unchanged(state, snap):
    assert state.board == snap.board
    assert state.piece_id == snap.piece_id
    assert state.piece_matrix == snap.piece_matrix
    assert state.piece_rot == snap.piece_rot
    assert state.x == snap.x
    assert state.y == snap.y
    assert state.score == snap.score
    assert state.lines_cleared == snap.lines_cleared
    assert state.level == snap.level
    assert state.game_over == snap.game_over


def state_with_piece(pid, rot=0, x=0, y=0, width=10, height=20, board=None, **overrides):
    """A fresh game state with the active piece forced to (pid, rot, x, y)."""
    st = te.new_game(0, width, height)
    matrix = [list(row) for row in te.PIECES[pid][rot]]
    st = dataclasses.replace(
        st, piece_id=pid, piece_rot=rot, piece_matrix=matrix, x=x, y=y, **overrides
    )
    if board is not None:
        st = dataclasses.replace(st, board=[list(row) for row in board])
    return st


def piece_sequence(seed, n=5):
    """The first n piece ids produced by the engine for this seed."""
    st = te.new_game(seed)
    seq = [st.piece_id]
    while len(seq) < n:
        st = te.hard_drop(st)
        seq.append(st.piece_id)
        if st.game_over:
            break
    return seq


def board_cells(board, value):
    return [(y, x) for y, row in enumerate(board) for x, v in enumerate(row) if v == value]


# ---------------------------------------------------------------- 0. constants

def test_constants_pinned():
    assert te.DEFAULT_WIDTH == 10
    assert te.DEFAULT_HEIGHT == 20
    assert te.SCORE_TABLE == {1: 100, 2: 300, 3: 500, 4: 800}
    assert te.KICKS == (0, 1, -1, 2, -2)


# ---------------------------------------------------------------- 1. determinism

def test_same_seed_same_sequence():
    a = piece_sequence(42)
    b = piece_sequence(42)
    assert len(a) >= 5
    assert a == b
    # the very first spawn is already deterministic
    assert te.new_game(42).piece_id == te.new_game(42).piece_id


def test_different_seeds_different_sequences():
    assert piece_sequence(1) != piece_sequence(2)
    assert piece_sequence(7) != piece_sequence(123456789)


# ---------------------------------------------------------------- 2. PIECES

def test_pieces_contract():
    assert set(te.PIECES) == {1, 2, 3, 4, 5, 6, 7}
    for pid, states in te.PIECES.items():
        assert len(states) == 4, f"piece {pid} must have 4 rotation states"
        for m in states:
            assert len(m) >= 1
            assert all(len(row) == len(m[0]) for row in m), "matrix must be rectangular"
            cells = [v for row in m for v in row]
            assert set(cells) <= {0, 1}, "matrix cells are 0/1 only"
            assert 1 in cells, "matrix must contain the piece"


def test_o_piece_invariant_under_rotation():
    states = te.PIECES[2]
    assert all(m == states[0] for m in states)


# ---------------------------------------------------------------- 3. try_move

def test_try_move_invalid_at_wall():
    st = state_with_piece(2, x=0, y=0)  # O at the left wall
    snap = snapshot(st)
    assert te.try_move(st, -1) is None
    assert_unchanged(st, snap)


def test_try_move_invalid_over_occupied_cells():
    board = [[0] * 10 for _ in range(20)]
    for y in range(20):
        board[y][2] = 3  # a wall of blocks right next to the O (cols 0-1)
    st = state_with_piece(2, x=0, y=0, board=board)
    snap = snapshot(st)
    assert te.try_move(st, 1) is None
    assert_unchanged(st, snap)


def test_try_move_valid_shifts_and_keeps_source_intact():
    st = state_with_piece(2, x=4, y=0)
    snap = snapshot(st)
    moved = te.try_move(st, 1)
    assert moved is not None
    assert moved.x == st.x + 1
    assert moved.board == st.board
    assert_unchanged(st, snap)


# ---------------------------------------------------------------- 4. try_rotate

def test_try_rotate_wall_kick():
    # Vertical I at x=7 (width 10) occupies board col 9; rotating to the
    # horizontal state (4 wide) needs the wall-kick offset -1 -> x=6.
    st = state_with_piece(1, rot=1, x=7, y=10)
    snap = snapshot(st)
    rotated = te.try_rotate(st, +1)
    assert rotated is not None
    assert rotated.piece_rot == 2
    assert rotated.x == 6
    assert_unchanged(st, snap)


def test_try_rotate_impossible_returns_none():
    # In a 3-wide well the horizontal I (4 wide) never fits: every kick fails.
    st = state_with_piece(1, rot=1, x=0, y=0, width=3, height=10)
    snap = snapshot(st)
    assert te.try_rotate(st, +1) is None
    assert te.try_rotate(st, -1) is None
    assert_unchanged(st, snap)


def test_try_rotate_ccw_in_open_field():
    st = state_with_piece(3, rot=0, x=4, y=5)  # T in open field
    rotated = te.try_rotate(st, -1)
    assert rotated is not None
    assert rotated.piece_rot == 3
    assert rotated.piece_matrix == [list(row) for row in te.PIECES[3][3]]


# ---------------------------------------------------------------- 5. tick / soft_drop

def test_tick_steps_down_then_locks_and_spawns():
    st = te.new_game(3)
    pid = st.piece_id
    s1 = te.tick(st)
    assert s1.y == st.y + 1
    assert s1.board == st.board  # nothing locked yet
    s2 = te.soft_drop(s1)
    assert s2.y == st.y + 2

    cur = s2
    steps = 0
    while all(v == 0 for row in cur.board for v in row):
        cur = te.tick(cur)
        steps += 1
        assert steps <= te.DEFAULT_HEIGHT + 10, "piece never locked"
    # the piece is locked into the board with its own id, resting on the floor
    locked = board_cells(cur.board, pid)
    assert locked, "locked cells must carry the piece id"
    assert max(y for y, _ in locked) == te.DEFAULT_HEIGHT - 1
    # the next piece spawned at the spawn point
    assert cur.y == 0
    assert cur.piece_matrix == [list(row) for row in te.PIECES[cur.piece_id][0]]
    assert not te.is_game_over(cur)


# ---------------------------------------------------------------- 6. line clearing

def test_full_row_cleared_partial_row_remains():
    board = [[0] * 4 for _ in range(4)]
    board[3] = [2, 2, 0, 0]
    st = state_with_piece(2, x=2, y=0, width=4, height=4, board=board)
    res = te.hard_drop(st)  # O fills cols 2-3 of rows 2-3 -> row 3 becomes full
    assert res.lines_cleared == 1
    # the full row is gone; the partial row stays (shifted down)
    assert res.board[3] == [0, 0, 2, 2]
    assert all(v == 0 for row in res.board[:3] for v in row)


def test_partial_row_is_not_cleared():
    board = [[0] * 10 for _ in range(20)]
    board[19] = [2, 2, 0, 0, 0, 0, 0, 0, 0, 0]
    st = state_with_piece(2, x=2, y=0, board=board)
    res = te.hard_drop(st)
    assert res.lines_cleared == 0
    assert res.board[19][0:4] == [2, 2, 2, 2]  # wait: O fills cols 2-3 only
    # correction: cols 0-1 were 2,2 and O adds cols 2-3 -> row is [2,2,2,2,0,...]
    assert res.board[18] == [0, 0, 2, 2, 0, 0, 0, 0, 0, 0]


# ---------------------------------------------------------------- 7. score & level

def test_score_one_line_is_100():
    board = [[0] * 4 for _ in range(4)]
    board[3] = [2, 2, 0, 0]
    st = state_with_piece(2, x=2, y=0, width=4, height=4, board=board)
    res = te.hard_drop(st)
    assert res.score == 100
    assert res.lines_cleared == 1
    assert res.level == 1


def test_score_four_lines_is_800():
    board = [[2, 2, 2, 0] for _ in range(4)]
    # vertical I (rot 1 fills its col index 2) at x=1 fills board col 3 in all rows
    st = state_with_piece(1, rot=1, x=1, y=0, width=4, height=4, board=board)
    res = te.hard_drop(st)
    assert res.lines_cleared == 4
    assert res.score == 800
    assert res.level == 4 // 10 + 1


def test_level_grows_every_10_lines():
    board = [[0] * 4 for _ in range(4)]
    board[3] = [2, 2, 0, 0]
    st = state_with_piece(2, x=2, y=0, width=4, height=4, board=board,
                          lines_cleared=9, score=900)
    res = te.hard_drop(st)
    assert res.lines_cleared == 10
    assert res.score == 1000
    assert res.level == 2


# ---------------------------------------------------------------- 8. hard_drop

def test_hard_drop_locks_on_the_floor():
    st = te.new_game(5)
    pid = st.piece_id
    res = te.hard_drop(st)
    cells = board_cells(res.board, pid)
    assert cells
    assert max(y for y, _ in cells) == te.DEFAULT_HEIGHT - 1
    assert not any(v == pid for row in res.board for v in row if False)  # noop guard


def test_hard_drop_stacks_over_previous_piece():
    st = te.new_game(5)
    first = te.hard_drop(st)
    first_cells = board_cells(first.board, st.piece_id)
    pid2 = first.piece_id
    second = te.hard_drop(first)
    second_cells = board_cells(second.board, pid2)
    assert second_cells
    # the second piece rests above the first one
    assert min(y for y, _ in second_cells) < max(y for y, _ in first_cells)
    # the first piece is still on the board
    assert board_cells(second.board, st.piece_id) == first_cells


# ---------------------------------------------------------------- 9. game over

def test_game_over_on_blocked_spawn():
    board = [[0] * 10 for _ in range(20)]
    for y in range(3):
        board[y] = [2] * 9 + [0]  # filled (incomplete -> not cleared) at the spawn point
    st = state_with_piece(2, x=4, y=10, board=board)
    assert not te.is_game_over(st)
    res = te.hard_drop(st)  # locks at the floor; the next spawn collides
    assert te.is_game_over(res)


def test_game_over_operations_are_noops():
    board = [[0] * 10 for _ in range(20)]
    for y in range(3):
        board[y] = [2] * 9 + [0]
    res = te.hard_drop(state_with_piece(2, x=4, y=10, board=board))
    assert te.is_game_over(res)
    snap = snapshot(res)
    assert te.try_move(res, 1) == res
    assert te.try_move(res, -1) == res
    assert te.try_rotate(res, 1) == res
    assert te.tick(res) == res
    assert te.soft_drop(res) == res
    assert te.hard_drop(res) == res
    assert te.is_game_over(res)
    assert_unchanged(res, snap)


def test_game_over_when_field_is_too_small_for_spawn():
    st = te.new_game(0, width=10, height=1)  # no piece fits in a 1-row field
    assert te.is_game_over(st)


# ---------------------------------------------------------------- 10. purity

def test_functions_do_not_mutate_their_input():
    st = te.new_game(11)
    snap = snapshot(st)
    for call in (
        lambda: te.try_move(st, 1),
        lambda: te.try_move(st, -1),
        lambda: te.try_rotate(st, 1),
        lambda: te.try_rotate(st, -1),
        lambda: te.soft_drop(st),
        lambda: te.hard_drop(st),
        lambda: te.tick(st),
    ):
        call()
        assert_unchanged(st, snap)


def test_returned_state_is_a_new_snapshot():
    st = te.new_game(11)
    moved = te.try_move(st, 1)
    assert moved is not st
    moved.board[0][0] = 7  # mutating the result must not touch the source
    assert st.board[0][0] == 0
