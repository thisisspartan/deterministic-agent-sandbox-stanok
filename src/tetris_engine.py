"""tetris_engine — a pure, deterministic Tetris rules simulator (CC-290).

No I/O, no time, no network; stdlib only (random). Every public function is
pure: it never mutates the input State or its board/piece, and every
returned State carries freshly copied board/piece rows — no row or matrix
object is shared with the input. The contract is pinned in
docs/tetris_engine.md.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, replace
from typing import Optional

# Piece ids 1..7 with their starting orientations (pinned by the contract).
PIECES: dict[int, list[list[int]]] = {
    1: [[1, 1, 1, 1]],           # I
    2: [[1, 1], [1, 1]],         # O
    3: [[1, 1, 1], [0, 1, 0]],   # T
    4: [[0, 1, 1], [1, 1, 0]],   # S
    5: [[1, 1, 0], [0, 1, 1]],   # Z
    6: [[1, 0, 0], [1, 1, 1]],   # J
    7: [[0, 0, 1], [1, 1, 1]],   # L
}

# Score for clearing k rows at once (pinned).
SCORE_TABLE = {1: 100, 2: 300, 3: 500, 4: 800}

# Wall-kick x offsets tried by try_rotate, in order (pinned).
WALL_KICKS = (0, 1, -1, 2, -2)


@dataclass(frozen=True)
class State:
    """Immutable game value. The constructor field order below is the pinned
    CLI seam: board, piece, piece_id, x, y, score, lines_cleared, level,
    game_over.

    board: list[list[int]] of height `height`, width `width`; 0 empty,
    1..7 a locked piece id. piece: the active piece matrix (0/1) or None
    (piece_id 0). x, y: top-left corner of piece on board.

    rng_state carries the getstate() of the game's single random.Random
    (one Random(seed) per game, one randrange(1, 8) per spawn). It is an
    internal continuation field with a default so tests may construct State
    directly; None means "fresh Random(0)" (only reachable for
    hand-constructed States — new_game always carries the seeded rng).
    """

    board: list
    piece: Optional[list]
    piece_id: int
    x: int
    y: int
    score: int = 0
    lines_cleared: int = 0
    level: int = 1
    game_over: bool = False
    rng_state: Optional[tuple] = None


# ---------------------------------------------------------------------------
# internal helpers
# ---------------------------------------------------------------------------

def _copy_board(board: list) -> list:
    return [row[:] for row in board]


def _copy_piece(piece: Optional[list]) -> Optional[list]:
    return None if piece is None else [row[:] for row in piece]


def _derive(state: State, **changes) -> State:
    """Return a new State whose board/piece are fresh copies unless the
    caller already supplies freshly built ones."""
    if "board" not in changes:
        changes["board"] = _copy_board(state.board)
    if "piece" not in changes:
        changes["piece"] = _copy_piece(state.piece)
    return replace(state, **changes)


def _collides(board: list, piece: list, x: int, y: int) -> bool:
    height = len(board)
    width = len(board[0])
    for py, prow in enumerate(piece):
        for px, cell in enumerate(prow):
            if not cell:
                continue
            bx, by = x + px, y + py
            if bx < 0 or bx >= width or by < 0 or by >= height:
                return True
            if board[by][bx]:
                return True
    return False


def _rotate_matrix(matrix: list, direction: int) -> list:
    rows, cols = len(matrix), len(matrix[0])
    if direction == 1:  # clockwise
        return [[matrix[rows - 1 - c][r] for c in range(rows)] for r in range(cols)]
    return [[matrix[c][cols - 1 - r] for c in range(rows)] for r in range(cols)]


def _spawn(state: State) -> State:
    """Draw the next piece from the game's carried rng and place it at the
    spawn position; a colliding spawn ends the game."""
    rng = random.Random()
    rng.setstate(state.rng_state if state.rng_state is not None else random.Random(0).getstate())
    piece_id = rng.randrange(1, 8)
    piece = _copy_piece(PIECES[piece_id])
    x = (len(state.board[0]) - len(piece[0])) // 2
    y = 0
    over = _collides(state.board, piece, x, y)
    return _derive(
        state,
        piece=None if over else piece,
        piece_id=0 if over else piece_id,
        x=x,
        y=y,
        game_over=over,
        rng_state=rng.getstate(),
    )


def _lock(state: State) -> State:
    """Write the piece into the board, clear full rows, update score/level,
    then spawn the next piece (or end the game)."""
    board = _copy_board(state.board)
    width = len(board[0])
    for py, prow in enumerate(state.piece):
        for px, cell in enumerate(prow):
            if cell:
                board[state.y + py][state.x + px] = state.piece_id
    kept = [row for row in board if any(cell == 0 for cell in row)]
    cleared = len(board) - len(kept)
    if cleared:
        kept = [[0] * width for _ in range(cleared)] + kept
    lines_cleared = state.lines_cleared + cleared
    score = state.score + (SCORE_TABLE[cleared] if cleared else 0)
    level = lines_cleared // 10 + 1
    return _spawn(
        _derive(
            state,
            board=kept,
            piece=None,
            piece_id=0,
            score=score,
            lines_cleared=lines_cleared,
            level=level,
        )
    )


# ---------------------------------------------------------------------------
# public API (names pinned by the contract)
# ---------------------------------------------------------------------------

def new_game(seed: int, width: int, height: int) -> State:
    if width < 2:
        raise ValueError(f"width must be >= 2, got {width}")
    if height < 2:
        raise ValueError(f"height must be >= 2, got {height}")
    if height % 2 != 0:
        raise ValueError(f"height must be even, got {height}")
    board = [[0] * width for _ in range(height)]
    state = State(
        board,
        None,
        0,
        0,
        0,
        rng_state=random.Random(seed).getstate(),
    )
    return _spawn(state)


def try_move(state: State, dx: int) -> Optional[State]:
    if state.game_over or state.piece is None or dx not in (-1, 1):
        return None
    x = state.x + dx
    if _collides(state.board, state.piece, x, state.y):
        return None
    return _derive(state, x=x)


def try_rotate(state: State, direction: int) -> Optional[State]:
    if state.game_over or state.piece is None or direction not in (1, -1):
        return None
    rotated = _rotate_matrix(state.piece, direction)
    for kick in WALL_KICKS:
        x = state.x + kick
        if not _collides(state.board, rotated, x, state.y):
            return _derive(state, piece=rotated, x=x)
    return None


def soft_drop(state: State) -> Optional[State]:
    if state.game_over:
        return state
    if state.piece is None:
        return None
    y = state.y + 1
    if _collides(state.board, state.piece, state.x, y):
        return None
    return _derive(state, y=y)


def hard_drop(state: State) -> Optional[State]:
    if state.game_over:
        return None
    if state.piece is None:
        return _spawn(state)
    y = state.y
    while not _collides(state.board, state.piece, state.x, y + 1):
        y += 1
    return _lock(_derive(state, y=y))


def tick(state: State) -> State:
    if state.game_over:
        return state
    if state.piece is None:
        return _spawn(state)
    y = state.y + 1
    if not _collides(state.board, state.piece, state.x, y):
        return _derive(state, y=y)
    return _lock(state)


def is_game_over(state: State) -> bool:
    return state.game_over
