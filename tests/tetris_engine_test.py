"""CC-302 — tetris engine reference tests (pins E1..E6, with negatives).

pytest; fixtures are defined inside this file. The engine is a pure
functional core: every operation returns a NEW state (or None for an
illegal move/rotate/soft_drop) and never mutates its input.
"""
import copy
import dataclasses

import pytest

try:
    from src import tetris_engine as eng
except ImportError:
    import tetris_engine as eng

SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}


def _snap(state):
    """Deep snapshot of the pinned state attributes."""
    return (copy.deepcopy(state.board), state.piece, state.piece_id,
            state.x, state.y, state.score, state.lines_cleared,
            state.level, state.game_over)


def _find_piece(pid, width=10, height=20, max_seed=400):
    for seed in range(1, max_seed + 1):
        st = eng.new_game(seed, width, height)
        if st.piece_id == pid:
            return st
    raise AssertionError(f"no seed <= {max_seed} spawns piece_id {pid}")


def _replay(seed, width, height, ops):
    st = eng.new_game(seed, width, height)
    for op in ops:
        kind = op[0]
        if kind == "tick":
            st = eng.tick(st)
        elif kind == "move":
            r = eng.try_move(st, op[1])
            st = r if r is not None else st
        elif kind == "rotate":
            r = eng.try_rotate(st, op[1])
            st = r if r is not None else st
        elif kind == "soft":
            r = eng.soft_drop(st)
            st = r if r is not None else st
        elif kind == "hard":
            st = eng.hard_drop(st)
    return st


def _assert_pure(op, state):
    """op(state) must not mutate the input and must not share board rows."""
    before = _snap(state)
    result = op(state)
    assert _snap(state) == before, "input state was mutated"
    if result is None or result is state:
        return result
    for row in result.board:
        for in_row in state.board:
            assert row is not in_row, "returned board shares a row with input"
    return result


def _assert_rows_unaliased(board):
    ids = [id(r) for r in board]
    assert len(ids) == len(set(ids)), "board rows aliased (A-1 defect)"


def _gap_board(cols, rows, width=10, height=20):
    """Bottom `rows` rows full (1s) EXCEPT at the given columns."""
    board = [[0] * width for _ in range(height)]
    for br in range(height - rows, height):
        board[br] = [1] * width
        for c in cols:
            board[br][c] = 0
    return board


def _footprint_cols(st):
    return sorted({st.x + c for r in st.piece for c, v in enumerate(r) if v})


def _clear_with(st, cols, rows):
    """Hard-drop the state's own piece onto a gap board (natural play)."""
    return eng.hard_drop(dataclasses.replace(st, board=_gap_board(cols, rows), y=0))


def _vertical_I():
    st = _find_piece(1)
    assert len(st.piece) == 1 and len(st.piece[0]) == 4
    nxt = eng.try_rotate(st, 1)
    assert nxt is not None
    assert len(nxt.piece) == 4 and len(nxt.piece[0]) == 1
    return nxt


# ---- E1: pinned names and the None-contract --------------------------------------

def test_e1_public_names_exist():
    for name in ("new_game", "try_move", "try_rotate", "soft_drop",
                 "hard_drop", "tick", "is_game_over"):
        assert callable(getattr(eng, name)), name


def test_e1_blocked_move_and_soft_drop_return_none():
    st = eng.new_game(1, 10, 20)
    while True:
        nxt = eng.try_move(st, -1)
        if nxt is None:
            break
        st = nxt
    assert eng.try_move(st, -1) is None          # already at the left wall
    while True:
        nxt = eng.soft_drop(st)
        if nxt is None:
            break
        st = nxt
    assert eng.soft_drop(st) is None             # already at the floor
    # tick is gravity: at the floor it must lock, never return None
    locked = eng.tick(st)
    assert locked is not None
    assert eng.is_game_over(locked) is False


def test_e1_tick_always_returns_state():
    st = eng.new_game(5, 10, 20)
    for _ in range(30):
        st = eng.tick(st)
        assert st is not None


# ---- E2: state shape, frozen, purity, no row aliasing ----------------------------

def test_e2_state_fields_and_types():
    st = eng.new_game(1, 10, 20)
    for attr in ("board", "piece", "piece_id", "x", "y", "score",
                 "lines_cleared", "level", "game_over"):
        assert hasattr(st, attr), attr
    assert isinstance(st.board, list) and isinstance(st.board[0], list)
    assert len(st.board) == 20 and all(len(r) == 10 for r in st.board)
    assert all(v == 0 for r in st.board for v in r)
    assert st.piece_id in range(1, 8)
    assert st.piece is not None
    assert st.score == 0 and st.lines_cleared == 0 and st.level == 1
    assert st.game_over is False
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.score = 1


def test_e2_locked_board_holds_piece_ids():
    st = eng.new_game(1, 10, 20)
    locked_pid = st.piece_id
    locked = eng.hard_drop(st)
    values = {v for r in locked.board for v in r}
    assert locked_pid in values                      # the locked piece wrote its id
    assert all(0 <= v <= 7 for r in locked.board for v in r)


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_e2_purity_and_no_row_aliasing_all_ops(seed):
    st = eng.new_game(seed, 10, 20)
    ops = [
        lambda s: eng.try_move(s, 1),
        lambda s: eng.try_move(s, -1),
        lambda s: eng.try_rotate(s, 1),
        lambda s: eng.try_rotate(s, -1),
        lambda s: eng.soft_drop(s),
        lambda s: eng.hard_drop(s),
        lambda s: eng.tick(s),
    ]
    for op in ops:
        _assert_pure(op, st)


def test_e2_mutating_returned_board_does_not_affect_input():
    st = eng.new_game(2, 10, 20)
    moved = eng.try_move(st, 1)
    assert moved is not None
    moved.board[0][0] = 9
    assert all(v == 0 for r in st.board for v in r)   # input board untouched


def test_e2_branches_from_one_base_are_identical():
    seed = 9
    st0 = eng.new_game(seed, 10, 20)
    a = eng.hard_drop(st0)
    b = eng.hard_drop(st0)
    assert _snap(a) == _snap(b)
    fresh = _replay(seed, 10, 20, [("hard",)])
    assert _snap(b) == _snap(fresh)


# ---- E3: pieces, rotation, wall kicks, O invariance ------------------------------

def test_e3_all_seven_ids_reachable_with_standard_matrices():
    expected = {
        1: [[1, 1, 1, 1]],
        2: [[1, 1], [1, 1]],
        3: [[1, 1, 1], [0, 1, 0]],
        4: [[0, 1, 1], [1, 1, 0]],
        5: [[1, 1, 0], [0, 1, 1]],
        6: [[1, 0, 0], [1, 1, 1]],
        7: [[0, 0, 1], [1, 1, 1]],
    }
    for pid in range(1, 8):
        st = _find_piece(pid)
        assert [list(r) for r in st.piece] == expected[pid], pid
        # spawn: top, horizontally centered
        assert st.y == 0
        assert st.x == (10 - len(st.piece[0])) // 2


@pytest.mark.parametrize("pid", [1, 3, 4, 5, 6, 7])
def test_e3_rotation_cycle_four_orientations(pid):
    st = _find_piece(pid)
    cur = st
    for _ in range(4):
        nxt = eng.try_rotate(cur, 1)
        assert nxt is not None, f"rotation of id {pid} in open field failed"
        for r in range(len(nxt.piece)):
            for c in range(len(nxt.piece[0])):
                if nxt.piece[r][c]:
                    assert 0 <= nxt.x + c < 10 and 0 <= nxt.y + r < 20
        cur = nxt
    # four 90° steps return to the original shape and position
    assert [list(r) for r in cur.piece] == [list(r) for r in st.piece]
    assert (cur.x, cur.y) == (st.x, st.y)


def test_e3_rotate_cw_ccw_are_inverses():
    st = _find_piece(3)  # T
    back = eng.try_rotate(eng.try_rotate(st, 1), -1)
    assert back is not None
    assert [list(r) for r in back.piece] == [list(r) for r in st.piece]
    assert (back.x, back.y) == (st.x, st.y)


def test_e3_o_rotation_invariant_everywhere():
    st = _find_piece(2)  # O
    for dx in (-4, -3, -2, -1, 0, 1, 2, 3, 4):
        moved = eng.try_move(st, dx)
        if moved is None:
            continue
        rot = eng.try_rotate(moved, 1)
        assert rot is not None, "O rotation must always succeed"
        assert [list(r) for r in rot.piece] == [list(r) for r in moved.piece]
        assert (rot.x, rot.y) == (moved.x, moved.y)


def test_e3_wall_kick_uses_plus_two_at_left_wall():
    st = _find_piece(1)  # horizontal I, 1x4
    cur = eng.try_rotate(st, 1)  # vertical I, 4x1
    assert cur is not None
    while True:
        nxt = eng.try_move(cur, -1)
        if nxt is None:
            break
        cur = nxt
    minc = min(c for r in cur.piece for c, v in enumerate(r) if v)
    assert cur.x + minc == 0                      # exactly touching the wall
    # a cell at (y, 1) makes kicks 0 and +1 collide and -1 leave the board:
    # only the +2 offset can make the rotation valid
    board = [[0] * 10 for _ in range(20)]
    board[cur.y][1] = 1
    rotated = eng.try_rotate(dataclasses.replace(cur, board=board), 1)
    assert rotated is not None, "wall-kick +2 must make the rotation valid"
    assert rotated.x == cur.x + 2
    maxc = max(c for r in rotated.piece for c, v in enumerate(r) if v)
    assert rotated.x + maxc < 10


def test_e3_wall_kick_uses_minus_two_near_right_wall():
    st = _find_piece(1)
    cur = eng.try_rotate(st, 1)                   # vertical I
    while True:
        nxt = eng.try_move(cur, 1)
        if nxt is None:
            break
        cur = nxt
    maxc = max(c for r in cur.piece for c, v in enumerate(r) if v)
    assert cur.x + maxc == 9                      # exactly touching the wall
    # from the wall itself the rotation is impossible: the needed shift is -3,
    # outside the pinned kick set (0, +1, -1, +2, -2)
    assert eng.try_rotate(cur, 1) is None
    # one cell off the wall: kicks 0,+1,-1 all hit the wall; -2 lands exactly on it
    near = dataclasses.replace(cur, x=cur.x - 1)
    rotated = eng.try_rotate(near, 1)
    assert rotated is not None, "wall-kick -2 must make the rotation valid"
    assert rotated.x == near.x - 2
    maxc = max(c for r in rotated.piece for c, v in enumerate(r) if v)
    assert rotated.x + maxc == 9                  # lands flush against the wall


def test_e3_impossible_rotation_returns_none():
    st = _find_piece(1)
    cur = eng.try_rotate(st, 1)                   # vertical I, 4x1
    assert cur is not None
    board = [[0] * 10 for _ in range(20)]
    for r in range(20):                           # full wall at columns 6..9
        board[r][6:10] = [1] * 4
    blocked = dataclasses.replace(cur, board=board, x=5)
    assert eng.try_move(blocked, 1) is None       # wall exactly at column 6
    assert eng.try_rotate(blocked, 1) is None     # kicks 0,+1,-1,+2,-2 all fail
    assert eng.try_rotate(blocked, 0) is None     # invalid direction


# ---- E4: game over at spawn collision, then no-ops ------------------------------

def _game_over_state(max_seed=400):
    for seed in range(1, max_seed + 1):
        st = eng.new_game(seed, 2, 2)   # every piece except O collides at spawn
        if eng.is_game_over(st):
            return st
    raise AssertionError("no seed <= 400 spawns a colliding piece on a 2x2 board")


def test_e4_spawn_collision_sets_game_over():
    st = _game_over_state()
    assert st.game_over is True
    assert eng.is_game_over(st) is True


def test_e4_tall_stopper_row_blocks_the_spawn():
    # narrow board, tall stopper rows near the top: after the first lock the
    # next spawn collides -> game_over
    st = eng.new_game(1, 2, 4)
    locked = eng.hard_drop(st)
    stopped = dataclasses.replace(
        locked, board=[[1, 1], [1, 1], [0, 0], [0, 0]])
    after = eng.tick(stopped)
    assert eng.is_game_over(after) is True


def test_e4_all_operations_are_noops_after_game_over():
    st = _game_over_state()
    before = _snap(st)
    assert _snap(eng.try_move(st, 1)) == before
    assert _snap(eng.try_move(st, -1)) == before
    assert _snap(eng.try_rotate(st, 1)) == before
    assert _snap(eng.try_rotate(st, -1)) == before
    assert _snap(eng.soft_drop(st)) == before
    assert _snap(eng.hard_drop(st)) == before
    assert _snap(eng.tick(st)) == before
    assert eng.is_game_over(st) is True


# ---- E5: clearing, scoring, level, anti-aliasing --------------------------------

def test_e5_clear_1_scores_100():
    st = _find_piece(1)                            # horizontal I fills a 1-row gap
    locked = _clear_with(st, _footprint_cols(st), 1)
    assert locked.lines_cleared == 1
    assert locked.score == SCORE_TABLE[1]
    assert locked.level == 1


def test_e5_clear_2_scores_300_and_rows_unaliased():
    st = _find_piece(2)                            # O: 2x2 footprint
    locked = _clear_with(st, _footprint_cols(st), 2)
    assert locked.lines_cleared == 2
    assert locked.score == SCORE_TABLE[2]
    _assert_rows_unaliased(locked.board)


def test_e5_clear_3_scores_500():
    st = _vertical_I()                             # 1-col gap under 3 full rows
    locked = _clear_with(st, [st.x], 3)
    assert locked.lines_cleared == 3
    assert locked.score == SCORE_TABLE[3]


def test_e5_clear_4_scores_800_and_rows_unaliased():
    st = _vertical_I()
    locked = _clear_with(st, [st.x], 4)
    assert locked.lines_cleared == 4
    assert locked.score == SCORE_TABLE[4]
    _assert_rows_unaliased(locked.board)


def test_e5_level_progression_at_ten_lines():
    vi = _vertical_I()
    got = _clear_with(dataclasses.replace(vi, lines_cleared=7), [vi.x], 3)
    assert got.lines_cleared == 10 and got.level == 2
    assert got.score == SCORE_TABLE[3]
    got = _clear_with(dataclasses.replace(vi, lines_cleared=6), [vi.x], 3)
    assert got.lines_cleared == 9 and got.level == 1     # boundary: stays 1
    hi = _find_piece(1)
    got = _clear_with(dataclasses.replace(hi, lines_cleared=9),
                      _footprint_cols(hi), 1)
    assert got.lines_cleared == 10 and got.level == 2


def test_e5_partial_row_is_never_cleared():
    st = _find_piece(1)                            # horizontal I, 4 cells
    board = [[0] * 10 for _ in range(20)]
    board[19] = [1] * 6 + [0] * 4                  # 6 filled cells in the bottom row
    locked = eng.hard_drop(dataclasses.replace(st, board=board, y=0))
    assert locked.lines_cleared == 0
    assert locked.score == 0


def test_e5_rows_shift_down_after_a_clear():
    st = _find_piece(1)
    cols = _footprint_cols(st)
    locked = _clear_with(st, cols, 1)
    # the cleared row is gone; the board is empty again except the new spawn
    nonzero = {(r, c) for r in range(20) for c in range(10) if locked.board[r][c]}
    shape_cells = {(locked.y + i, locked.x + j)
                   for i in range(len(locked.piece))
                   for j in range(len(locked.piece[0])) if locked.piece[i][j]}
    assert nonzero <= shape_cells                  # only the freshly spawned piece


def test_e5_hard_drop_locks_at_the_floor_and_scores_like_a_tick():
    seed = 4
    by_hard = eng.hard_drop(eng.new_game(seed, 10, 20))
    st = eng.new_game(seed, 10, 20)
    while eng.soft_drop(st) is not None:
        st = eng.soft_drop(st)
    by_tick = eng.tick(st)
    assert _snap(by_hard) == _snap(by_tick)


# ---- E6: seeded determinism and validation ---------------------------------------

def test_e6_same_seed_identical_trajectory_20_ticks():
    ops = [("tick",)] * 20
    a = _snap(_replay(7, 10, 20, ops))
    b = _snap(_replay(7, 10, 20, ops))
    assert a == b
    # pieces AND positions must match, not just the final board
    sa = _replay(7, 10, 20, [])
    sb = _replay(7, 10, 20, [])
    assert (sa.piece_id, sa.x, sa.y) == (sb.piece_id, sb.x, sb.y)


def test_e6_same_seed_identical_under_mixed_ops():
    ops = [("move", 1), ("tick",), ("hard",), ("rotate", 1), ("hard",),
           ("move", -1), ("soft",), ("tick",), ("hard",), ("tick",)]
    assert _snap(_replay(7, 10, 20, ops)) == _snap(_replay(7, 10, 20, ops))


def test_e6_different_seeds_diverge():
    a = _replay(1, 10, 20, [("hard",)] * 8)
    b = _replay(2, 10, 20, [("hard",)] * 8)
    assert a.board != b.board or a.score != b.score or a.level != b.level


@pytest.mark.parametrize("bad", [(1, 1, 20), (1, 10, 19), (1, 10, 0),
                                (1, 0, 20), (1, 10, 1), (1, 1, 1)])
def test_e6_new_game_validation(bad):
    with pytest.raises(ValueError):
        eng.new_game(*bad)


def test_e6_valid_dimensions_are_accepted():
    st = eng.new_game(1, 2, 2)
    assert len(st.board) == 2 and all(len(r) == 2 for r in st.board)
    st = eng.new_game(1, 10, 2)
    assert len(st.board) == 2
