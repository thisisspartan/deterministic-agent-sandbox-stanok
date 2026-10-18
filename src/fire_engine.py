"""fire_engine — a pure, deterministic flame simulator (CC-287).

DOOM-style fire: the bottom row is fresh fuel every tick; heat diffuses
upward from the four cells below each cell. No I/O, no time, no network,
no files — stdlib `random` only. One random.Random(seed) per engine,
consumed in a fixed traversal order, so the simulation is fully
deterministic.

Contract documentation: docs/fire_engine.md.
"""
from __future__ import annotations

import random

_FUEL_MIN = 180
_FUEL_MAX = 255
_MAX_HEAT = 255


class FireEngine:
    """Deterministic flame simulation on a height x width heat grid.

    Cells hold int heat 0..255; the initial state is all zeros.
    step() advances one tick; `grid` returns a fresh deep snapshot that
    shares no rows or cells with the engine state or other snapshots.
    """

    def __init__(self, seed: int, width: int, height: int) -> None:
        if width < 2 or height < 2:
            raise ValueError("width and height must be >= 2")
        self._width = width
        self._height = height
        self._rng = random.Random(seed)
        self._grid = [[0] * width for _ in range(height)]

    @property
    def grid(self) -> list:
        """A fresh deep copy of the state: new rows, new cells."""
        return [row[:] for row in self._grid]

    def step(self) -> None:
        """Advance the simulation by one tick.

        Traversal order is part of the determinism contract: bottom row
        left-to-right, then rows bottom-to-top (y = height-2 .. 0),
        cells left-to-right. Rows below already hold this tick's values
        when a row is computed (in-place DOOM-fire order). The rng call
        for cooling happens for every cell, even when the value clamps.
        """
        rng = self._rng
        grid = self._grid
        w, h = self._width, self._height

        # Bottom row: fresh fuel, no cooling.
        bottom = grid[h - 1]
        for x in range(w):
            bottom[x] = rng.randint(_FUEL_MIN, _FUEL_MAX)

        # Remaining rows: average of the four sources below, minus cooling.
        for y in range(h - 2, -1, -1):
            row = grid[y]
            below = grid[y + 1]
            below2 = grid[y + 2] if y + 2 < h else None
            for x in range(w):
                center = below[x]
                left = below[x - 1] if x > 0 else center
                right = below[x + 1] if x + 1 < w else center
                down2 = below2[x] if below2 is not None else center
                value = (center + left + right + down2) // 4 - rng.randint(0, 3)
                if value < 0:
                    value = 0
                elif value > _MAX_HEAT:
                    value = _MAX_HEAT
                row[x] = value
