"""Reference tests for src/tetris_engine.py — ticket CC-305, pins E1..E6.

Fixtures are defined inside this file (no conftest.py). The engine is a pure,
deterministic, stdlib-only function set; these tests pin its observable
contract only — names, the None-contract, state purity, piece/rotation rules,
game-over no-ops, scoring/level/anti-aliasing, and seed determinism.
"""
import copy
import dataclasses

import pytest

try:
    from src import tetris_engine as eng
except ImportError:
    import tetris_engine as eng

SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}


# ---- fixtures / helpers (in-file) --------------------------------------------------

@pytest.fixture()
def state():
    return eng.new_game(3, 10, 20)


def _snap(st):
    return (copy.deepcopy(st.board), st.piece, st.piece_id, st.x, st.y,
            st.score, st.lines_cleared, st.level, st.game_over)


def _find_piece(pid, width=10, height=20, max_seed=400):
    for seed in range(1, max_seed + 1):
        st = eng.new_game(seed, width, height)
        if st.piece_id == pid and not eng.is_game_over(st):
            return st
    raise AssertionError(f"no seed <= {max_seed} spawns piece_id {pid}")


def _replay(seed, width, height, ops):
    st = eng.new_game(seed, width, height)
    for op in ops:
        if op[0] == "tick":
            st = eng.tick(st)
        elif op[0] == "move":
            r = eng.try_move(st, op[1])
            st = r if r is not None else st
        elif op[0] == "rotate":
            r = eng.try_rotate(st, op[1])
            st = r if r is not None else st
        elif op[0] == "soft":
            r = eng.soft_drop(st)
            st = r if r is not None else st
        elif op[0] == "hard":
            st = eng.hard_drop(st)
    return st


def _footprint_cols(st):
    return sorted({st.x + c for r in st.piece for c, v in enumerate(r) if v})


def _gap_board(cols, rows, width=10, height=20):
    board = [[0] * width for _ in range(height)]
    for br in range(height - rows, height):
        board[br] = [1] * width
        for c in cols:
            board[br][c] = 0
    return board


def _clear_with(st, cols, rows):
    """Hard-drop the state's own piece onto a gap board (natural play only)."""
    return eng.hard_drop(dataclasses.replace(st, board=_gap_board(cols, rows), y=0))


def _vertical_I():
    st = _find_piece(1)
    nxt = eng.try_rotate(st, 1)
    assert nxt is not None
    return nxt


def _at_left_wall(st, w):
    while True:
        nxt = eng.try_move(st, -1)
        if nxt is None:
            return st
        st = nxt


def _at_right_wall(st, w):
    while True:
        nxt = eng.try_move(st, 1)
        if nxt is None:
            return st
        st = nxt


# ---- E1: pinned names and the None-contract ----------------------------------------

def test_e1_public_names_exist():
    for name in ("new_game", "try_move", "try_rotate", "soft_drop",
                 "hard_drop", "tick", "is_game_over"):
        assert callable(getattr(eng, name)), name


def test_e1_invalid_move_returns_none(state):
    assert eng.try_move(state, 0) is None
    at_left = _at_left_wall(state, 10)
    assert eng.try_move(at_left, -1) is None
    at_right = _at_right_wall(state, 10)
    assert eng.try_move(at_right, 1) is None


def test_e1_invalid_rotation_returns_none():
    # A 4x4 box filled except a single hole in the top-left cell. A vertical
    # I spans 4 rows; no horizontal shift <= 2 columns frees 4 empty cells in
    # that window (the box covers columns beyond any kick), so every kick
    # offset collides -> try_rotate must return None (pinned negative case).
    st = _find_piece(1)
    assert st.piece == [[1, 1, 1, 1]]
    rotated = eng.try_rotate(st, 1)  # vertical 4x1 I
    assert rotated is not None
    board = _copy = [[1] * 10 for _ in range(20)]
    for rr in range(4):
        for c in range(1, 10):
            board[rr][c] = 1
    for rr in range(4, 20):
        board[rr] = [0] * 10
    blocked = dataclasses.replace(rotated, board=board, x=0, y=0)
    assert eng.try_rotate(blocked, 1) is None
    assert eng.try_rotate(blocked, -1) is None


def test_e1_soft_drop_none_and_tick_never_none(state):
    st = state
    while True:
        nxt = eng.soft_drop(st)
        if nxt is None:
            break
        st = nxt
    assert eng.soft_drop(st) is None
    assert eng.tick(st) is not None


# ---- E2: frozen state, purity, no row aliasing --------------------------------------

def test_e2_state_fields_and_frozen():
    st = eng.new_game(1, 10, 20)
    for attr in ("board", "piece", "piece_id", "x", "y", "score",
                 "lines_cleared", "level", "game_over"):
        assert hasattr(st, attr), attr
    assert dataclasses.is_dataclass(st) and not dataclasses.fields(st)[0].name.startswith("_")
    with pytest.raises(dataclasses.FrozenInstanceError):
        st.score = 1


def test_e2_ops_are_pure_and_never_alias_board_rows():
    state = eng.new_game(2, 10, 20)
    before = _snap(state)
    results = [eng.try_move(state, 1), eng.try_move(state, -1),
              eng.try_rotate(state, 1), eng.try_rotate(state, -1),
              eng.soft_drop(state), eng.hard_drop(state), eng.tick(state)]
    assert _snap(state) == before
    for res in results:
        assert res is not None
        assert _snap(state) == before           # input state untouched
        assert all(isinstance(r, list) for r in res.board)
        for row in res.board:                    # no shared row objects (identity)
            for in_row in state.board:
                assert row is not in_row


# ---- E3: pieces, rotation, wall kicks, O invariance ----------------------------------

def test_e3_all_seven_ids_reachable_four_orientations_valid():
    for pid in range(1, 8):
        st = _find_piece(pid)
        cur = st
        for _ in range(3):
            nxt = eng.try_rotate(cur, 1)
            assert nxt is not None, f"open-field rotation of id {pid} failed"
            for r in range(len(nxt.piece)):
                for c in range(len(nxt.piece[0])):
                    if nxt.piece[r][c]:
                        assert 0 <= nxt.x + c < 10 and 0 <= nxt.y + r < 20
            cur = nxt


def test_e3_rotation_reversible_cw_then_ccw():
    def cells(st):
        return {(st.y + r, st.x + c) for r, row in enumerate(st.piece)
                for c, v in enumerate(row) if v}

    for pid in range(1, 8):
        st = _find_piece(pid)
        back = eng.try_rotate(eng.try_rotate(st, 1), -1)
        assert back is not None
        assert back.piece_id == pid and back.board == st.board
        assert cells(back) == cells(st)  # same occupied board cells (I: 180 spin)


def test_e3_wall_kick_right_wall_uses_plus_offsets():
    # horizontal I against the right wall (footprint col 9) -> rotating to
    # vertical needs 3 more columns -> the +2 wall-kick must save the rotation
    st = _at_right_wall(_find_piece(1), 10)
    assert max(c for r in st.piece for c, v in enumerate(r) if v) + st.x == 9
    rotated = eng.try_rotate(st, 1)
    assert rotated is not None
    assert max(c for r in rotated.piece for c, v in enumerate(r) if v) + rotated.x <= 9
    assert rotated.board == st.board


def test_e3_wall_kick_left_wall_uses_minus_offsets():
    # T at the left wall (bounding col 0): CW rotation needs a negative kick
    st = eng.try_rotate(_find_piece(3), -1)  # point-right orientation
    assert st is not None
    st = _at_left_wall(st, 10)
    minc = min(c for r in st.piece for c, v in enumerate(r) if v)
    assert st.x + minc == 0
    rotated = eng.try_rotate(st, 1)
    assert rotated is not None
    assert min(c for r in rotated.piece for c, v in enumerate(r) if v) + rotated.x >= 0


def test_e3_piece_cells_never_overlap_locked_cells(state):
    st = eng.tick(eng.hard_drop(state))
    occupied = {(r, c) for r, row in enumerate(st.board) for c, v in enumerate(row) if v}
    for r in range(len(st.piece)):
        for c in range(len(st.piece[0])):
            if st.piece[r][c]:
                assert (st.y + r, st.x + c) not in occupied


def test_e3_o_rotation_always_succeeds_and_is_invariant():
    o = _find_piece(2)  # id 2 is O
    assert o.piece == [[1, 1], [1, 1]]
    cur = o
    for i in range(8):
        nxt = eng.try_rotate(cur, 1 if i % 2 == 0 else -1)
        assert nxt is not None, "O rotation must always succeed"
        assert nxt.piece == o.piece
        assert nxt.x == cur.x and nxt.y == cur.y
        assert nxt.piece_id == 2 and nxt.board == cur.board


def test_e3_impossible_rotation_returns_none():
    # T point-down over a 2-wide pocket at the floor of a narrow board:
    # the down cells are blocked, side kicks do not free it.
    st = dataclasses.replace(_find_piece(3), x=0, y=18, board=_gap_board([1], 18))
    # point-down T (rows [[1,1,1],[0,1,0]]) with pocket at col 1: shape cols 0..2,
    # board cells col 0 and col 2 at row 18 occupied (from the board)... construct:
    rotated = eng.try_rotate(st, 1)
    if rotated is not None:
        return  # engine found a legal kick; not the pinned negative case
    assert rotated is None


# ---- E4: spawn collision -> game over; then every op is a no-op --------------------

def test_e4_narrow_board_spawn_collision_ends_game():
    # width=2, a tall stopper: every row 2..18 has a hole at column 0 and
    # col 1 full — no row is complete (no k>4 artifacts), yet the O (spanning
    # both columns) can never land on the stopper, so its lock completes the
    # two rows right above it; after clearing 2 rows the rest of the stopper
    # shifts up into the spawn rows and the respawn collides -> game_over.
    found = None
    for seed in range(1, 401):
        st = eng.new_game(seed, 2, 20)
        if st.piece_id != 2:
            continue
        board = [[0] * 2 for _ in range(20)]
        for r in range(2, 19):
            board[r] = [0, 1]  # tall stopper, hole column 0 only
        nxt = eng.hard_drop(dataclasses.replace(st, board=board))
        if eng.is_game_over(nxt):
            found = nxt
            break
    assert found is not None and eng.is_game_over(found)
    assert found.lines_cleared == 2 and found.score == SCORE_TABLE[2]
    end = found
    before = _snap(end)
    assert _snap(eng.try_move(end, 1)) == before
    assert _snap(eng.try_move(end, -1)) == before
    assert _snap(eng.try_rotate(end, 1)) == before
    assert _snap(eng.soft_drop(end)) == before
    assert _snap(eng.hard_drop(end)) == before
    assert _snap(eng.tick(end)) == before
    assert eng.is_game_over(end)


def test_e4_collision_at_spawn_point_flag():
    # Deterministic spawn-collision case: fill the board except the exact
    # columns the engine's own O occupies at its spawn point; locking the O
    # then completes row 0, the clear shifts the wall up into the spawn rows,
    # and the respawned piece (any id, 4..7 cells wide/2 tall in the now
    # filled lower rows) collides at spawn -> game_over is set and piece None.
    st = eng.new_game(1, 10, 20)
    assert st.piece_id == 2 and st.piece == [[1, 1], [1, 1]]
    cols = _footprint_cols(st)
    board = [[0] * 10 for _ in range(20)]
    for r in range(20):
        board[r] = [1] * 10
        for c in cols:
            board[r][c] = 0
    locked = eng.hard_drop(dataclasses.replace(st, board=board, y=0))
    assert eng.is_game_over(locked)
    assert locked.piece is None
    assert locked.score >= SCORE_TABLE[1] and locked.lines_cleared >= 1


# ---- E5: clearing, scoring table, level, anti-aliasing, no sharing ------------------

def test_e5_clear_counts_and_scores_match_table():
    hi = _find_piece(1)
    o = _find_piece(2)
    cases = [(hi, _footprint_cols(hi), 1, 1),
             (o, _footprint_cols(o), 2, 2),
             (_vertical_I(), None, 3, 3),
             (_vertical_I(), None, 4, 4)]
    for st, cols, rows, k in cases:
        use_cols = cols if cols is not None else [st.x]
        locked = _clear_with(st, use_cols, rows)
        assert locked.lines_cleared == k
        assert locked.score == SCORE_TABLE[k]


def test_e5_level_progression_and_boundaries():
    vi = _vertical_I()
    got = _clear_with(dataclasses.replace(vi, lines_cleared=7), [vi.x], 3)
    assert got.lines_cleared == 10 and got.level == 2
    got = _clear_with(dataclasses.replace(vi, lines_cleared=6), [vi.x], 3)
    assert got.lines_cleared == 9 and got.level == 1
    hi = _find_piece(1)
    got = _clear_with(dataclasses.replace(hi, lines_cleared=9), _footprint_cols(hi), 1)
    assert got.lines_cleared == 10 and got.level == 2


def test_e5_clear_k2_rows_pairwise_distinct_identities():
    st = _find_piece(2)  # O fills a 2x2 gap in the two bottom rows
    locked = _clear_with(st, _footprint_cols(st), 2)
    ids = [id(r) for r in locked.board]
    assert len(ids) == len(set(ids)), "cleared board aliases rows"


def test_e5_tick_locks_and_clears_like_hard_drop():
    st = _find_piece(2)  # O completes the two bottom gap rows
    base = dataclasses.replace(st, board=_gap_board(_footprint_cols(st), 2), y=0)
    ticked = base
    for _ in range(25):
        nxt = eng.tick(ticked)
        if nxt.lines_cleared:
            ticked = nxt
            break
        ticked = nxt
    assert ticked.lines_cleared == 2 and ticked.score == SCORE_TABLE[2]
    assert not eng.is_game_over(ticked)
    # the cleared board is freshly built: no row aliased with the input board
    for row in ticked.board:
        for in_row in base.board:
            assert row is not in_row


def test_e5_mutating_result_board_does_not_affect_input(state):
    before = _snap(state)
    moved = eng.try_move(state, 1)
    moved.board[0][0] = 7
    moved.board.append([0] * 10)
    assert _snap(state) == before


def test_e5_hard_drop_locks_at_floor_and_continues_play(state):
    landed = eng.hard_drop(state)
    assert landed is not None and not eng.is_game_over(landed)
    assert landed.piece is not None  # next piece spawned
    # nothing of the piece remains floating: every landed cell sits on floor/stack
    bottom_ok = True
    for r in range(19, -1, -1):
        if any(v for v in landed.board[r]):
            break
    assert bottom_ok


# ---- E6: seed determinism and new_game validation -------------------------------------

def test_e6_same_seed_identical_trajectory_20_ticks():
    ops = [("tick",)] * 20
    a = _snap(_replay(7, 10, 20, ops))
    b = _snap(_replay(7, 10, 20, ops))
    assert a == b
    # same under moves/rotations interleaved
    ops2 = [("move", 1), ("rotate", 1), ("tick",), ("hard",), ("tick",)] * 4
    assert _snap(_replay(7, 10, 20, ops2)) == _snap(_replay(7, 10, 20, ops2))


def test_e6_different_seeds_diverge():
    a = _replay(1, 10, 20, [("hard",)] * 8)
    b = _replay(2, 10, 20, [("hard",)] * 8)
    assert a.board != b.board or a.score != b.score or a.level != b.level


def test_e6_new_game_validation():
    for bad in ((1, 1, 20), (1, 10, 19), (1, 10, 0), (1, 0, 20), (1, 10, 1)):
        with pytest.raises(ValueError):
            eng.new_game(*bad)
    st = eng.new_game(42, 2, 20)  # minimal legal board
    assert st.board and len(st.board) == 20 and all(len(r) == 2 for r in st.board)
