"""tetris_engine — pure, deterministic tetris engine (SPEC-TETRIS-CONSOLE E1..E6).

stdlib-only (random, dataclasses); no time, I/O, threads or global state.
Every operation takes a state and returns a NEW state (or None for an
impossible move/rotation/soft-drop); the input state is never mutated and a
returned board shares no row object with the input board.

State: frozen dataclass.
Board coordinates: board[y][x], y=0 top row, x=0 left column; W=width, H=height.
Piece: matrix of 0/1; its cell (r,c) occupies board cell (y+r, x+c).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional

# ---- piece set: 7 tetrominoes, ids 1..7 (E3) --------------------------------------
# Standard matrices; I spawns horizontal, O 2x2, T point-down at spawn.
SHAPES = {
    1: [[1, 1, 1, 1]],          # I
    2: [[1, 1],                 # O
        [1, 1]],
    3: [[1, 1, 1],              # T (point-down)
        [0, 1, 0]],
    4: [[0, 1, 1],              # S
        [1, 1, 0]],
    5: [[1, 1, 0],              # Z
        [0, 1, 1]],
    6: [[1, 0, 0],              # J
        [1, 1, 1]],
    7: [[0, 0, 1],              # L
        [1, 1, 1]],
}
KICKS = (0, 1, -1, 2, -2)      # wall-kick horizontal offsets, first valid wins
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}


# ---- state (E2) -------------------------------------------------------------------

@dataclass(frozen=True)
class GameState:
    board: list          # list[list[int]], H x W; 0 empty or locked id 1..7
    piece: Optional[list]  # current shape matrix (orientation), None on game over
    piece_id: int
    x: int
    y: int
    score: int
    lines_cleared: int
    level: int
    game_over: bool
    rng_state: Optional[bytes]  # internal: sequence cursor of Random(seed)


# ---- helpers (pure) ---------------------------------------------------------------

def _next_piece(rng_state):
    rng = random.Random()
    rng.setstate(rng_state)
    pid = rng.randint(1, 7)
    return pid, rng.getstate()


def _shape_for(pid, board):
    """Piece matrix for id pid. I adapts to the board: on a board narrower
    than 4 it spawns vertically so the piece fits at spawn (board-legal
    invariant)."""
    shape = [list(row) for row in SHAPES[pid]]
    if pid == 1 and len(shape[0]) > len(board[0]):
        shape = [[shape[0][c]] for c in range(len(shape[0]))]
    return shape


def _collides(board, shape, x, y):
    h, w = len(board), len(board[0])
    for r in range(len(shape)):
        for c in range(len(shape[0])):
            if not shape[r][c]:
                continue
            by, bx = y + r, x + c
            if bx < 0 or bx >= w or by >= h:
                return True
            if by >= 0 and board[by][bx]:
                return True
    return False


def _copy_board(board):
    return [list(row) for row in board]


def _empty_board(w, h):
    return [[0] * w for _ in range(h)]


def _rotate_matrix(shape, direction):
    """90-degree rotation of an R x C matrix -> C x R, exact geometry:
    CW maps cell (r,c) -> (c, R-1-r); CCW maps (r,c) -> (C-1-c, r).
    (cw . ccw = identity for any dimensions; 4x the same direction = identity.)"""
    r_n, c_n = len(shape), len(shape[0])
    if direction == 1:
        return [[shape[rr][c] for rr in range(r_n - 1, -1, -1)]
                for c in range(c_n)]
    return [[shape[j][c_n - 1 - i] for j in range(r_n)] for i in range(c_n)]


def _footprint_cols(piece, x):
    return {x + c for row in piece for c, v in enumerate(row) if v}


def _moved(st, **changes):
    """Always return a NEW state whose board is a deep copy — even for pure
    translations — so a returned board never shares a row object with the
    input board (E2 deep-independence)."""
    return replace(st, board=_copy_board(st.board), **changes)


def _game_over_state(st):
    return _moved(st, game_over=True, piece=None, rng_state=None)


def _spawn(st, piece_id, rng_state):
    """Spawn piece_id centered at the top; a colliding spawn ends the game (E4)."""
    shape = _shape_for(piece_id, st.board)
    x = (len(st.board[0]) - len(shape[0])) // 2
    y = 0
    if _collides(st.board, shape, x, y):
        return _game_over_state(st)
    return _moved(st, piece=shape, piece_id=piece_id, x=x, y=y, game_over=False,
                  rng_state=rng_state)


def _land_and_clear(st, piece, x, y):
    """Lock the piece at (x, y), clear full rows, score/level, spawn next (E5)."""
    board = _copy_board(st.board)
    for r in range(len(piece)):
        for c in range(len(piece[0])):
            if piece[r][c] and 0 <= y + r < len(board) and 0 <= x + c < len(board[0]):
                board[y + r][x + c] = st.piece_id
    full = [br for br in range(len(board)) if all(board[br])]
    k = len(full)
    score, lines = st.score, st.lines_cleared
    if k:
        full_set = set(full)
        board = [row for br, row in enumerate(board) if br not in full_set]
        # fresh row objects, pairwise distinct (E5 anti-aliasing); width taken
        # from the input board so an all-clear (board emptied) still works
        board.extend(_empty_board(len(st.board[0]), k))
        score += SCORE_TABLE.get(k, SCORE_TABLE[4] * k // 4)
        lines += k
    level = lines // 10 + 1
    piece_id, rng_state = _next_piece(st.rng_state)
    return _spawn(replace(st, board=board, piece=None, x=0, y=0, score=score,
                          lines_cleared=lines, level=level, game_over=False,
                          piece_id=piece_id, rng_state=None),
                  piece_id, rng_state)


def _drop_target(st):
    """Largest dy >= 1 such that the piece still fits dy rows lower; None if it
    does not fall at all (floor/stack directly below)."""
    dy = 1
    while not _collides(st.board, st.piece, st.x, st.y + dy):
        dy += 1
    dy -= 1
    return dy if dy >= 1 else None


def _valid_ops(st):
    return st.piece is not None and not _collides(st.board, st.piece, st.x, st.y)


def _over(st):
    """E4: once the game is over every operation is a no-op returning the
    unchanged state."""
    return st.game_over


# ---- public API (E1) ---------------------------------------------------------------

def new_game(seed, width, height) -> GameState:
    """Fresh game: board H x W, first piece spawned. Invalid dims -> ValueError (E6).
    One sequence of pieces per game drawn from a single Random(seed)."""
    if width < 2 or height < 2 or height % 2:
        raise ValueError(f"invalid board dimensions: width={width} height={height}")
    rng = random.Random(seed)
    piece_id = rng.randint(1, 7)
    rng_state = rng.getstate()
    board = _empty_board(width, height)
    shape = _shape_for(piece_id, board)
    x = (width - len(shape[0])) // 2
    st = GameState(board=board, piece=shape, piece_id=piece_id, x=x, y=0,
                   score=0, lines_cleared=0, level=1, game_over=False,
                   rng_state=rng_state)
    if _collides(board, shape, x, 0):
        return _game_over_state(st)
    return st


def is_game_over(state) -> bool:
    return bool(state.game_over)


def try_move(state, dx):
    """Shift the active piece horizontally by dx; None if invalid (wall/stack)."""
    if _over(state):
        return state
    if dx == 0 or not _valid_ops(state):
        return None
    if _collides(state.board, state.piece, state.x + dx, state.y):
        return None
    return _moved(state, x=state.x + dx)


def try_rotate(state, direction):
    """Rotate 90 degrees (1 = clockwise, -1 = counter-clockwise). O always
    succeeds unchanged; other pieces try wall-kicks (0,+1,-1,+2,-2), the first
    valid wins; None if none fit."""
    if _over(state):
        return state
    if not _valid_ops(state):
        return None
    if state.piece_id == 2:  # O: invariant shape and position (E3)
        return _moved(state)
    rotated = _rotate_matrix(state.piece, 1 if direction == 1 else -1)
    for offset in KICKS:
        x = state.x + offset
        if not _collides(state.board, rotated, x, state.y):
            return _moved(state, piece=rotated, x=x)
    return None


def soft_drop(state):
    """One row down; None if the piece cannot fall (it stays and must lock/tick)."""
    if _over(state):
        return state
    if not _valid_ops(state):
        return None
    dy = _drop_target(state)
    if dy is None:
        return None
    return _moved(state, y=state.y + dy)


def hard_drop(state):
    """Instant drop to the bottom of the fall range and lock there (E5)."""
    if _over(state):
        return state
    if not _valid_ops(state):
        return None
    dy = _drop_target(state)
    y = state.y + (dy if dy is not None else 0)
    return _land_and_clear(state, state.piece, state.x, y)


def tick(state) -> GameState:
    """Gravity tick: always returns a state. One row down if the piece falls;
    otherwise lock + clear + spawn the next piece (E5)."""
    if _over(state) or not _valid_ops(state):
        return state
    dy = _drop_target(state)
    if dy is not None:
        return _moved(state, y=state.y + dy)
    return _land_and_clear(state, state.piece, state.x, state.y)
