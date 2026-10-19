"""tetris_engine — pure, deterministic tetris engine functions (CC-302).

stdlib only (random, dataclasses); no time, no I/O, no global mutable state.
Every operation is a pure call on an immutable GameState: it never mutates
its input and the returned board shares no row (identity) with the input.
One piece sequence per game, drawn from a single random.Random(seed) whose
state travels inside the state (rng_state) — equal seeds give identical
trajectories. See docs/tetris_engine.md.
"""

from __future__ import annotations

import dataclasses
import random

SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}

# Canonical spawn shapes, ids 1..7 = I,O,T,S,Z,J,L (minimal bounding boxes).
SHAPES = {
    1: ((1, 1, 1, 1),),
    2: ((1, 1), (1, 1)),
    3: ((1, 1, 1), (0, 1, 0)),
    4: ((0, 1, 1), (1, 1, 0)),
    5: ((1, 1, 0), (0, 1, 1)),
    6: ((1, 0, 0), (1, 1, 1)),
    7: ((0, 0, 1), (1, 1, 1)),
}

# Wall-kick horizontal offsets, tried in order; the first valid one wins.
KICKS = (0, 1, -1, 2, -2)


@dataclasses.dataclass(frozen=True)
class GameState:
    board: list          # list[list[int]], H x W: 0 empty, else piece id 1..7
    piece: object        # matrix (list[list[int]]) | None
    piece_id: int
    x: int
    y: int
    score: int
    lines_cleared: int
    level: int
    game_over: bool
    rng_state: tuple     # internal: state of the game's single random.Random


def _copy_board(board):
    return [list(row) for row in board]


def _collides(board, piece, x, y):
    """True if any shape cell is outside the board or on an occupied cell."""
    height = len(board)
    width = len(board[0])
    for r in range(len(piece)):
        row = piece[r]
        for c in range(len(row)):
            if not row[c]:
                continue
            bx, by = x + c, y + r
            if bx < 0 or bx >= width or by < 0 or by >= height:
                return True
            if board[by][bx]:
                return True
    return False


def _rotate_matrix(matrix, direction):
    """90° rotation of the shape matrix: direction 1 = CW, -1 = CCW."""
    rows = len(matrix)
    cols = len(matrix[0])
    out = [[0] * rows for _ in range(cols)]
    for r in range(rows):
        for c in range(cols):
            if direction == 1:
                out[c][rows - 1 - r] = matrix[r][c]
            else:
                out[cols - 1 - c][r] = matrix[r][c]
    return out


def _draw(rng_state):
    """Draw the next piece id from the game's Random state; return (pid, new_state)."""
    rng = random.Random()
    rng.setstate(rng_state)
    pid = rng.randrange(1, 8)
    return pid, rng.getstate()


def _spawn(board, rng_state):
    """Spawn the next piece at the top center. Returns (state fields..., game_over)."""
    pid, rng_state = _draw(rng_state)
    shape = [list(row) for row in SHAPES[pid]]
    width = len(board[0])
    x = (width - len(shape[0])) // 2
    y = 0
    game_over = _collides(board, shape, x, y)
    return shape, pid, x, y, rng_state, game_over


def _lock_and_clear(state):
    """Lock the active piece, clear full rows, score, level up, spawn the next."""
    board = _copy_board(state.board)
    for r in range(len(state.piece)):
        for c in range(len(state.piece[r])):
            if state.piece[r][c]:
                board[state.y + r][state.x + c] = state.piece_id

    full = {i for i, row in enumerate(board) if all(row)}
    k = len(full)
    if k:
        # Fresh empty rows on top, kept rows are already private copies:
        # every row of the result is a distinct object (anti-aliasing).
        board = [[0] * len(board[0]) for _ in range(k)] + [
            row for i, row in enumerate(board) if i not in full
        ]

    score = state.score + SCORE_TABLE.get(k, 0)
    lines_cleared = state.lines_cleared + k
    level = lines_cleared // 10 + 1
    shape, pid, x, y, rng_state, game_over = _spawn(board, state.rng_state)
    return GameState(
        board=board, piece=shape, piece_id=pid, x=x, y=y,
        score=score, lines_cleared=lines_cleared, level=level,
        game_over=game_over, rng_state=rng_state,
    )


def new_game(seed, width, height):
    """A fresh game: empty board, first piece spawned from random.Random(seed)."""
    if width < 2 or height < 2 or height % 2:
        raise ValueError(
            f"width must be >= 2 and height must be even and >= 2, "
            f"got width={width} height={height}"
        )
    board = [[0] * width for _ in range(height)]
    shape, pid, x, y, rng_state, game_over = _spawn(
        board, random.Random(seed).getstate()
    )
    return GameState(
        board=board, piece=shape, piece_id=pid, x=x, y=y,
        score=0, lines_cleared=0, level=1,
        game_over=game_over, rng_state=rng_state,
    )


def try_move(state, dx):
    """Shift the active piece horizontally by dx; None if blocked."""
    if state.game_over:
        return state
    x = state.x + dx
    if _collides(state.board, state.piece, x, state.y):
        return None
    return dataclasses.replace(
        state, board=_copy_board(state.board), x=x
    )


def try_rotate(state, direction):
    """Rotate 90° (1 = CW, -1 = CCW) with wall-kicks; None if no offset fits."""
    if state.game_over:
        return state
    if direction not in (1, -1):
        return None
    shape = _rotate_matrix(state.piece, direction)
    for kick in KICKS:
        x = state.x + kick
        if not _collides(state.board, shape, x, state.y):
            return dataclasses.replace(
                state, board=_copy_board(state.board), piece=shape, x=x
            )
    return None


def soft_drop(state):
    """Move the active piece one row down; None if it cannot move."""
    if state.game_over:
        return state
    y = state.y + 1
    if _collides(state.board, state.piece, state.x, y):
        return None
    return dataclasses.replace(
        state, board=_copy_board(state.board), y=y
    )


def hard_drop(state):
    """Instant lock at the bottom of the fall; scoring as a normal lock."""
    if state.game_over:
        return state
    y = state.y
    while not _collides(state.board, state.piece, state.x, y + 1):
        y += 1
    return _lock_and_clear(dataclasses.replace(state, y=y))


def tick(state):
    """Gravity: one row down, or lock + clear + spawn when it cannot move."""
    if state.game_over:
        return state
    if _collides(state.board, state.piece, state.x, state.y + 1):
        return _lock_and_clear(state)
    return dataclasses.replace(
        state, board=_copy_board(state.board), y=state.y + 1
    )


def is_game_over(state):
    return bool(state.game_over)
