"""Pure heat-diffusion fire simulator (TASK-FIRE-02, TASK-FIRE-03).

The simulator only manipulates its heat buffer — it has no dependency on
any terminal UI library or on writing to standard output; rendering is a
separate concern.

Coordinate system: ``buffer[y][x]`` with row 0 at the top and row
``height - 1`` at the bottom (the fuel line). Heat rises: each step, rows
``0..height - 2`` are recomputed from the row below.

TASK-FIRE-03 adds a smoothly drifting target wind (``update_wind``) and a
system of floating embers (``spawn_sparks``): rare very-hot particles that
rise 2 rows per tick — faster than the main flame — creating the effect of
embers shooting out of the fire.
"""

from __future__ import annotations

import math
import random
from typing import List, Optional, Tuple

# Probability that a cell of the ignited bottom row stays cold (a gap).
_GAP_PROBABILITY = 0.05

# A cell this hot or hotter is a floating ember (spark).
_EMBER_MIN_HEAT = 250
_EMBER_MAX_HEAT = 255

# Rows an ember rises per tick (the main flame rises 1 row per tick).
_EMBER_RISE = 2

# Amplitude of the target wind: -2 (left) .. +2 (right).
_WIND_AMPLITUDE = 2.0


class FireSimulation:
    """Heat buffer of ``height`` rows x ``width`` columns, values 0..255.

    The buffer is initialized to zeros. ``ignite_bottom`` heats the bottom
    row; ``step`` propagates heat upward with a horizontal offset and
    per-cell decay. ``update_wind`` drifts the target wind within
    ``[-2, 2]``; ``spawn_sparks`` injects floating embers that rise faster
    than the main flame.
    """

    def __init__(
        self,
        width: int,
        height: int,
        decay_min: int = 1,
        decay_max: int = 4,
    ) -> None:
        if width < 1 or height < 1:
            raise ValueError("width and height must be >= 1")
        if not (0 <= decay_min <= decay_max <= 255):
            raise ValueError("require 0 <= decay_min <= decay_max <= 255")
        self.width = width
        self.height = height
        self.decay_min = decay_min
        self.decay_max = decay_max
        self.buffer: List[List[int]] = [[0] * width for _ in range(height)]
        # TASK-FIRE-03: wind state and floating embers.
        self.target_wind: float = 0.0
        self._wind_phase: float = 0.0
        self._embers: List[Tuple[int, int, int]] = []  # (x, y, heat)

    def update_wind(self) -> None:
        """Drift the target wind smoothly within ``[-2, 2]``.

        The wind follows a sine wave whose phase advances by a small random
        amount on every call, so the value changes smoothly (no jumps) and
        always stays inside ``[-2, 2]``: negative blows left, positive
        blows right.
        """
        self._wind_phase += random.uniform(0.05, 0.2)
        self.target_wind = _WIND_AMPLITUDE * math.sin(self._wind_phase)

    def spawn_sparks(self, count: int = 3) -> None:
        """Spawn ``count`` floating embers (heat 250-255).

        Each ember is placed in a random column of the 2nd or 3rd row from
        the bottom (rows ``height - 2`` and ``height - 3``) and recorded in
        the internal ember list so that ``step`` can float it upward faster
        than the main flame. On grids shorter than 3 rows there is no room
        for sparks and the call is a no-op.
        """
        candidate_rows = [
            row
            for row in (self.height - 2, self.height - 3)
            if 0 <= row < self.height - 1
        ]
        if not candidate_rows:
            return
        for _ in range(count):
            y = random.choice(candidate_rows)
            x = random.randrange(self.width)
            heat = random.randint(_EMBER_MIN_HEAT, _EMBER_MAX_HEAT)
            self.buffer[y][x] = heat
            self._embers.append((x, y, heat))

    def ignite_bottom(
        self, intensity_min: int = 200, intensity_max: int = 255
    ) -> None:
        """Heat the bottom row with random high temperatures.

        Each cell gets a random value in ``[intensity_min, intensity_max]``;
        with a small probability a cell is skipped and stays cold (a rare
        gap in the fuel line).
        """
        bottom = self.buffer[-1]
        for x in range(self.width):
            if random.random() < _GAP_PROBABILITY:
                bottom[x] = 0
            else:
                bottom[x] = random.randint(intensity_min, intensity_max)

    def step(self, wind: Optional[float] = None) -> None:
        """Advance the simulation by one frame.

        Rows ``0..height - 2`` are recomputed (top to bottom, so each row
        reads the not-yet-updated row below it): the new value of cell
        ``(x, y)`` is taken from ``(x, y + 1)``, shifted horizontally by
        ``dst_x = x - wind + choice(-1, 0, 1)`` (clamped to the buffer) and
        decayed by ``randint(decay_min, decay_max)`` (clamped at 0). The
        bottom row — the fuel line — is left untouched.

        TASK-FIRE-03: when ``wind`` is omitted, the current ``target_wind``
        (rounded to an integer) is used. After the main propagation, the
        floating embers rise ``_EMBER_RISE`` rows (2 per tick — faster than
        the flame's 1 row), so rare hot particles shoot up above the flame.
        """
        if wind is None:
            wind = self.target_wind
        wind = int(round(wind))
        for y in range(self.height - 1):
            src_row = self.buffer[y + 1]
            dst_row = self.buffer[y]
            for x in range(self.width):
                dst_x = x - wind + random.choice((-1, 0, 1))
                if dst_x < 0:
                    dst_x = 0
                elif dst_x >= self.width:
                    dst_x = self.width - 1
                heat = src_row[x] - random.randint(self.decay_min, self.decay_max)
                dst_row[dst_x] = heat if heat > 0 else 0
        # TASK-FIRE-03: float the embers upward, 2 rows per tick.
        if self._embers:
            floated: List[Tuple[int, int, int]] = []
            for x, y, heat in self._embers:
                new_y = y - _EMBER_RISE
                if new_y < 0:
                    new_y = 0
                if heat > self.buffer[new_y][x]:
                    self.buffer[new_y][x] = heat
                floated.append((x, new_y, heat))
            self._embers = floated
