"""tetris_engine — a pure, deterministic Tetris engine (CC-282).

No I/O, no time, no global mutable state. Every operation takes a State
snapshot and returns a NEW State; the input is never mutated. The piece
sequence is derived from a single random.Random(seed) stream: the state
stores only (seed, rng_calls), so it is reproducible and serializable.

Contract documentation: docs/tetris_engine.md.
"""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional

DEFAULT_WIDTH = 10
DEFAULT_HEIGHT = 20
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}
KICKS = (0, 1, -1, 2, -2)  # wall-kick x-offsets, tried in this order


def _rotate_cw(matrix):
    rows, cols = len(matrix), len(matrix[0])
    return tuple(
        tuple(matrix[rows - 1 - c][r] for c in range(rows))
        for r in range(cols)
    )


def _rotation_states(base):
    states = [base]
    for _ in range(3):
        states.append(_rotate_cw(states[-1]))
    return tuple(states)


_BASE_SHAPES = {
    1: ((1, 1, 1, 1),),                      # I
    2: ((1, 1), (1, 1)),                     # O
    3: ((1, 1, 1), (0, 1, 0)),               # T
    4: ((0, 1, 1), (1, 1, 0)),               # S
    5: ((1, 1, 0), (0, 1, 1)),               # Z
    6: ((1, 0, 0), (1, 1, 1)),               # J
    7: ((0, 0, 1), (1, 1, 1)),               # L
}

PIECES = {pid: _rotation_states(base) for pid, base in _BASE_SHAPES.items()}


@dataclass(frozen=True)
class State:
    seed: int
    width: int
    height: int
    board: list          # list[list[int]]: 0 empty, 1..7 locked piece id
    piece_id: int
    piece: tuple         # current rotation matrix (tuple of tuples of 0/1)
    rot: int             # index into PIECES[piece_id]
    x: int               # board column of the matrix top-left cell
    y: int               # board row of the matrix top-left cell
    rng_calls: int       # number of pieces drawn from the seed stream so far
    score: int = 0
    lines_cleared: int = 0
    level: int = 1
    game_over: bool = False


def _piece_at(seed: int, n: int) -> int:
    """The n-th piece (0-based) of the single Random(seed) stream."""
    rng = random.Random(seed)
    value = 1
    for _ in range(n + 1):
        value = rng.randrange(1, 8)
    return value


def _collides(state: State, matrix, x: int, y: int) -> bool:
    for r, row in enumerate(matrix):
        for c, cell in enumerate(row):
            if not cell:
                continue
            bx, by = x + c, y + r
            if bx < 0 or bx >= state.width or by >= state.height:
                return True
            if by >= 0 and state.board[by][bx]:
                return True
    return False


def _spawn(state: State) -> State:
    """Activate the next piece from the seed stream at the top center."""
    pid = _piece_at(state.seed, state.rng_calls)
    matrix = PIECES[pid][0]
    x = (state.width - len(matrix[0])) // 2
    over = _collides(state, matrix, x, 0)
    return replace(
        state, piece_id=pid, piece=matrix, rot=0, x=x, y=0,
        rng_calls=state.rng_calls + 1, game_over=over,
    )


def _lock_and_clear(state: State) -> State:
    """Write the active piece into the board and clear full rows."""
    board = [row[:] for row in state.board]
    for r, row in enumerate(state.piece):
        for c, cell in enumerate(row):
            if cell:
                by, bx = state.y + r, state.x + c
                if 0 <= by < state.height and 0 <= bx < state.width:
                    board[by][bx] = state.piece_id
    remaining = [row for row in board if not all(row)]
    cleared = state.height - len(remaining)
    lines = state.lines_cleared + cleared
    return replace(
        state,
        board=[[0] * state.width] * cleared + remaining,
        score=state.score + SCORE_TABLE.get(cleared, 0),
        lines_cleared=lines,
        level=lines // 10 + 1,
    )


def _fall_or_lock(state: State) -> State:
    if not _collides(state, state.piece, state.x, state.y + 1):
        return replace(state, y=state.y + 1)
    return _spawn(_lock_and_clear(state))


def new_game(seed: int, width: int = DEFAULT_WIDTH, height: int = DEFAULT_HEIGHT) -> State:
    board = [[0] * width for _ in range(height)]
    state = State(
        seed=seed, width=width, height=height, board=board,
        piece_id=0, piece=(), rot=0, x=0, y=0, rng_calls=0,
    )
    return _spawn(state)


def try_move(state: State, dx: int) -> Optional[State]:
    if state.game_over:
        return state
    if _collides(state, state.piece, state.x + dx, state.y):
        return None
    return replace(state, x=state.x + dx)


def try_rotate(state: State, direction: int) -> Optional[State]:
    if state.game_over:
        return state
    rot = (state.rot + direction) % 4
    matrix = PIECES[state.piece_id][rot]
    for kick in KICKS:
        if not _collides(state, matrix, state.x + kick, state.y):
            return replace(state, piece=matrix, rot=rot, x=state.x + kick)
    return None


def soft_drop(state: State) -> State:
    if state.game_over:
        return state
    return _fall_or_lock(state)


def hard_drop(state: State) -> State:
    if state.game_over:
        return state
    y = state.y
    while not _collides(state, state.piece, state.x, y + 1):
        y += 1
    return _spawn(_lock_and_clear(replace(state, y=y)))


def tick(state: State) -> State:
    if state.game_over:
        return state
    return _fall_or_lock(state)


def is_game_over(state: State) -> bool:
    return state.game_over
