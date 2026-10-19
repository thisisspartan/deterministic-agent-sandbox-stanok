"""Calibrated contract oracle for src/tetris_engine.py (SPEC-TETRIS-CONSOLE E1..E6).

Independence policy: literals (SCORE_TABLE, dims, field names, None-contract)
are transcribed from the SPEC/ticket CC-302; shapes are obtained from the
engine's OWN spawned states (seed-scan by pinned piece_id), never from lab
shape constants — so the oracle couples only to the pinned API, not to an
internal representation. Host lab: /tmp/oracle-lab-tetris; mutants EM1..EM6
(see specs/STATUS.md). GREEN on reference, RED on each targeted mutant.
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
        elif kind == "hard":
            st = eng.hard_drop(st)
    return st


# ---- E1: names and None-contract -------------------------------------------------

def test_public_names_exist():
    for name in ("new_game", "try_move", "try_rotate", "soft_drop",
                 "hard_drop", "tick", "is_game_over"):
        assert callable(getattr(eng, name)), name


def test_blocked_ops_return_none():
    st = eng.new_game(1, 10, 20)
    # walk left into the wall on an empty board, then one more left must be None
    while True:
        nxt = eng.try_move(st, -1)
        if nxt is None:
            break
        st = nxt
    # soft_drop to the floor, then one more must be None
    while True:
        nxt = eng.soft_drop(st)
        if nxt is None:
            break
        st = nxt
    assert eng.soft_drop(st) is None
    # tick (gravity) at the floor must still return a state, never None
    assert eng.tick(st) is not None


# ---- E2: state shape, frozen, purity, no-aliasing --------------------------------

def test_state_fields_and_types():
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
    assert st.game_over is False or st.game_over == False
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.score = 1


def test_op_does_not_mutate_input_and_no_row_aliasing():
    st = eng.new_game(2, 10, 20)
    before = _snap(st)
    moved = eng.try_move(st, 1)
    assert moved is not None
    assert _snap(st) == before                      # input untouched
    for row in moved.board:
        for in_row in st.board:
            assert row is not in_row                 # no shared rows
    rot = eng.try_rotate(st, 1)
    if rot is not None:
        for row in rot.board:
            for in_row in st.board:
                assert row is not in_row


def test_branch_independence_same_base():
    """Two diverging operations from ONE base state must each equal a fresh
    replay of the same command sequence (no hidden shared rng / board leak)."""
    seed = 9
    st0 = eng.new_game(seed, 10, 20)
    stA = eng.hard_drop(st0)
    stB = eng.hard_drop(st0)
    assert _snap(stA) == _snap(stB)
    fresh = _replay(seed, 10, 20, [("hard",)])
    assert _snap(stB) == _snap(fresh)


# ---- E3: pieces, rotation invariants ---------------------------------------------

def test_all_seven_ids_reachable_and_rotation_bounds_valid():
    for pid in range(1, 8):
        st = _find_piece(pid)
        seen = [st]
        cur = st
        for _ in range(3):
            nxt = eng.try_rotate(cur, 1)
            assert nxt is not None, f"rotation of id {pid} in open field failed"
            # invariant: every shape cell lies inside the board
            w, h = 10, 20
            shape = nxt.piece
            for r in range(len(shape)):
                for c in range(len(shape[0])):
                    if shape[r][c]:
                        assert 0 <= nxt.x + c < w and 0 <= nxt.y + r < h
            cur = nxt
            seen.append(cur)
        # returning to identity after 4 CW rotations: same shape footprint
        four = eng.try_rotate(cur, 1)
        if four is not None:
            assert len(four.piece) == len(st.piece) or pid == 1  # I footprint may rotate


def test_wall_blocking_is_exact_and_wall_rotation_stays_valid():
    st = eng.new_game(3, 10, 20)
    while True:
        nxt = eng.try_move(st, -1)
        if nxt is None:
            break
        st = nxt
    minc = min(c for r in st.piece for c, v in enumerate(r) if v)
    assert st.x + minc == 0            # blocked only by the wall, exactly touching
    rotated = eng.try_rotate(st, 1)
    assert rotated is not None         # open board: rotation must find a valid offset
    for r in range(len(rotated.piece)):
        for c in range(len(rotated.piece[0])):
            if rotated.piece[r][c]:
                assert 0 <= rotated.x + c < 10


# ---- E4: game over ---------------------------------------------------------------

def _game_over_state(max_seed=400):
    """Seed-scan for a state the engine itself reports as game-over on a 2x2
    board (every piece except O collides at spawn)."""
    for seed in range(1, max_seed + 1):
        st = eng.new_game(seed, 2, 2)
        guard = 0
        while not eng.is_game_over(st) and guard < 50:
            nxt = eng.hard_drop(st)
            st = nxt if nxt is not None else st
            st = eng.tick(st)
            guard += 1
        if eng.is_game_over(st):
            return st
    raise AssertionError("no seed reached game over")


def test_game_over_then_noops():
    # E4 pins: after game_over every op is a no-op returning the unchanged state.
    st = _game_over_state()
    assert eng.is_game_over(st)
    before = _snap(st)
    assert _snap(eng.try_move(st, 1)) == before
    assert _snap(eng.try_move(st, -1)) == before
    assert _snap(eng.try_rotate(st, 1)) == before
    assert _snap(eng.soft_drop(st)) == before
    assert _snap(eng.hard_drop(st)) == before
    assert _snap(eng.tick(st)) == before
    assert eng.is_game_over(st)


# ---- E5: clearing, scoring, level, anti-aliasing ---------------------------------
# Board construction: bottom `rows` rows are full (1s) EXCEPT at the columns the
# engine's own piece covers; gravity then completes exactly those rows.
# k=1: horizontal I; k=2: O; k=3: vertical I over a 3-row gap (the 4th I cell
# lands on an empty row above the gap, so exactly 3 rows complete); k=4: the
# same with a 4-row gap. All clears are produced by natural play, no engine
# internals are assumed.

def _gap_board(cols, rows, width=10, height=20):
    board = [[0] * width for _ in range(height)]
    for br in range(height - rows, height):
        board[br] = [1] * width
        for c in cols:
            board[br][c] = 0
    return board


def _footprint_cols(st):
    return sorted({st.x + c for r in st.piece for c, v in enumerate(r) if v})


def _clear_with(st, cols, rows):
    """Hard-drop the state's own piece onto a gap board; returns the locked state."""
    return eng.hard_drop(dataclasses.replace(st, board=_gap_board(cols, rows), y=0))


def _vertical_I():
    st = _find_piece(1)
    assert len(st.piece) == 1 and len(st.piece[0]) == 4
    nxt = eng.try_rotate(st, 1)
    assert nxt is not None, "I must rotate in an open field"
    assert len(nxt.piece) == 4 and len(nxt.piece[0]) == 1
    return nxt


def _assert_rows_unaliased(board):
    ids = [id(r) for r in board]
    assert len(ids) == len(set(ids)), "cleared rows aliased (A-1 defect)"


def test_clear_1_score_100():
    st = _find_piece(1)                  # horizontal I fills a 4-cell gap in one row
    locked = _clear_with(st, _footprint_cols(st), 1)
    assert locked.lines_cleared == 1
    assert locked.score == SCORE_TABLE[1]


def test_clear_2_score_300_and_anti_aliasing():
    st = _find_piece(2)                  # O: 2x2 footprint -> 2 rows, 2 cols
    locked = _clear_with(st, _footprint_cols(st), 2)
    assert locked.lines_cleared == 2
    assert locked.score == SCORE_TABLE[2]
    _assert_rows_unaliased(locked.board)


def test_clear_3_score_500():
    st = _vertical_I()                   # 1-col gap under 3 full rows; 4th cell misses
    locked = _clear_with(st, [st.x], 3)
    assert locked.lines_cleared == 3
    assert locked.score == SCORE_TABLE[3]


def test_clear_4_score_800_and_anti_aliasing():
    st = _vertical_I()
    locked = _clear_with(st, [st.x], 4)
    assert locked.lines_cleared == 4
    assert locked.score == SCORE_TABLE[4]
    _assert_rows_unaliased(locked.board)


def test_level_progression_and_boundaries():
    vi = _vertical_I()
    # lines 7 -> clear 3 -> 10 -> level 2
    got = _clear_with(dataclasses.replace(vi, lines_cleared=7), [vi.x], 3)
    assert got.lines_cleared == 10 and got.level == 2
    assert got.score == SCORE_TABLE[3]
    # negative boundary: lines 6 -> clear 3 -> 9 -> level stays 1
    got = _clear_with(dataclasses.replace(vi, lines_cleared=6), [vi.x], 3)
    assert got.lines_cleared == 9 and got.level == 1
    # lines 9 -> clear 1 -> 10 -> level 2 (different k, same boundary)
    hi = _find_piece(1)
    got = _clear_with(dataclasses.replace(hi, lines_cleared=9), _footprint_cols(hi), 1)
    assert got.lines_cleared == 10 and got.level == 2


# ---- E6: seeded determinism and validation ---------------------------------------

def test_same_seed_identical_trajectory():
    ops = [("move", 1), ("tick",), ("hard",), ("tick",), ("tick",),
           ("move", -1), ("hard",), ("tick",), ("hard",)]
    a = _snap(_replay(7, 10, 20, ops))
    b = _snap(_replay(7, 10, 20, ops))
    assert a == b


def test_different_seeds_diverge():
    a = _replay(1, 10, 20, [("hard",)] * 8)
    b = _replay(2, 10, 20, [("hard",)] * 8)
    assert a.board != b.board or a.score != b.score or a.level != b.level


def test_new_game_validation():
    for bad in ((1, 1, 20), (1, 10, 19), (1, 10, 0), (1, 0, 20), (1, 10, 1)):
        seed = bad[0]
        w = bad[1]
        h = bad[2]
        with pytest.raises(ValueError):
            eng.new_game(seed, w, h)
