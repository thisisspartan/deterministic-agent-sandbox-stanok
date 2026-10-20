"""minesweeper_engine — pure deterministic functions of the console Minesweeper engine.

Contract M1..M7 (SPEC-MINESWEEPER-CONSOLE). stdlib-only; no time, I/O,
threading or global state. Every operation returns a NEW frozen GameState
(or None for an illegal move) and never mutates its input. Coordinates are
1-based: x = column 1..width, y = row 1..height.
"""

from __future__ import annotations

import dataclasses
import random
from collections import deque
from typing import FrozenSet, List, Optional, Set, Tuple

Cell = Tuple[int, int]

MAX_WIDTH = 64
MAX_HEIGHT = 32

_N4 = ((1, 0), (-1, 0), (0, 1), (0, -1))
_N8 = tuple((dx, dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1) if dx or dy)


@dataclasses.dataclass(frozen=True)
class GameState:
    seed: int
    width: int
    height: int
    mines_total: int
    mines: FrozenSet[Cell]
    adj: Tuple[Tuple[int, ...], ...]
    opened: FrozenSet[Cell]
    flagged: FrozenSet[Cell]
    status: str  # "playing" | "won" | "lost"
    first_done: bool


def _cells(width: int, height: int) -> List[Cell]:
    return [(x, y) for y in range(1, height + 1) for x in range(1, width + 1)]


def _adjacency(mines: FrozenSet[Cell], width: int, height: int) -> Tuple[Tuple[int, ...], ...]:
    return tuple(
        tuple(
            sum(1 for dx, dy in _N8 if (x + dx, y + dy) in mines)
            for x in range(1, width + 1)
        )
        for y in range(1, height + 1)
    )


def _in_field(state: GameState, x: int, y: int) -> bool:
    return 1 <= x <= state.width and 1 <= y <= state.height


def new_game(seed: int, width: int, height: int, mines_count: int) -> GameState:
    if width < 1 or width > MAX_WIDTH:
        raise ValueError(f"width out of range [1, {MAX_WIDTH}]: {width}")
    if height < 1 or height > MAX_HEIGHT:
        raise ValueError(f"height out of range [1, {MAX_HEIGHT}]: {height}")
    if mines_count < 0:
        raise ValueError(f"mines_count must be >= 0: {mines_count}")
    if mines_count > width * height - 1:
        raise ValueError(f"mines_count must be <= width*height-1 ({width * height - 1}): {mines_count}")
    rng = random.Random(seed)
    mines = frozenset(rng.sample(_cells(width, height), mines_count))
    return GameState(
        seed=seed,
        width=width,
        height=height,
        mines_total=mines_count,
        mines=mines,
        adj=_adjacency(mines, width, height),
        opened=frozenset(),
        flagged=frozenset(),
        status="playing",
        first_done=False,
    )


def _reveal(mines: FrozenSet[Cell], adj: Tuple[Tuple[int, ...], ...],
           state: GameState, start: Cell) -> Set[Cell]:
    """M6 opened set from opening the non-mine cell `start` (iterative BFS)."""
    x, y = start
    if adj[y - 1][x - 1] != 0:
        return {start}
    zeros: Set[Cell] = set()
    queue = deque([start])
    seen = {start}
    while queue:
        cx, cy = queue.popleft()
        zeros.add((cx, cy))
        for dx, dy in _N4:
            nx, ny = cx + dx, cy + dy
            if 1 <= nx <= state.width and 1 <= ny <= state.height:
                n = (nx, ny)
                if n not in seen and n not in mines and adj[ny - 1][nx - 1] == 0:
                    seen.add(n)
                    queue.append(n)
    opened = set(zeros)
    for zx, zy in zeros:  # numeric border: non-mine 8-neighbors of any zero
        for dx, dy in _N8:
            nx, ny = zx + dx, zy + dy
            if 1 <= nx <= state.width and 1 <= ny <= state.height:
                n = (nx, ny)
                if n not in mines:
                    opened.add(n)
    return opened


def open_cell(state: GameState, x: int, y: int) -> Optional[GameState]:
    if state.status != "playing" or not _in_field(state, x, y):
        return None
    cell = (x, y)
    if cell in state.flagged or cell in state.opened:
        return None
    mines = state.mines
    adj = state.adj
    if not state.first_done and cell in mines:
        # M5 safe first open: relocate the mine to the first row-major cell
        # that is neither a mine nor the clicked cell; recompute adjacency.
        remaining = mines - {cell}
        target = next(c for c in _cells(state.width, state.height)
                      if c not in remaining and c != cell)
        mines = remaining | {target}
        adj = _adjacency(mines, state.width, state.height)
    if cell in mines:
        return dataclasses.replace(state, mines=mines, adj=adj,
                                  status="lost", first_done=True)
    opened = state.opened | _reveal(mines, adj, state, cell)
    status = "playing"
    if all(c in opened for c in _cells(state.width, state.height) if c not in mines):
        status = "won"
    return dataclasses.replace(state, mines=mines, adj=adj, opened=frozenset(opened),
                              status=status, first_done=True)


def toggle_flag(state: GameState, x: int, y: int) -> Optional[GameState]:
    if state.status != "playing" or not _in_field(state, x, y):
        return None
    cell = (x, y)
    if cell in state.opened:
        return None
    flagged = state.flagged - {cell} if cell in state.flagged else state.flagged | {cell}
    return dataclasses.replace(state, flagged=frozenset(flagged))


def is_won(state: GameState) -> bool:
    return state.status == "won"


def is_lost(state: GameState) -> bool:
    return state.status == "lost"
