"""Pure heat-diffusion fire simulator (TASK-FIRE-02).

The simulator only manipulates its heat buffer — it has no dependency on
any terminal UI library or on writing to standard output; rendering is a
separate concern.

Coordinate system: ``buffer[y][x]`` with row 0 at the top and row
``height - 1`` at the bottom (the fuel line). Heat rises: each step, rows
``0..height - 2`` are recomputed from the row below.
"""

from __future__ import annotations

import random
from typing import List

# Probability that a cell of the ignited bottom row stays cold (a gap).
_GAP_PROBABILITY = 0.05


class FireSimulation:
    """Heat buffer of ``height`` rows x ``width`` columns, values 0..255.

    The buffer is initialized to zeros. ``ignite_bottom`` heats the bottom
    row; ``step`` propagates heat upward with a horizontal offset and
    per-cell decay.
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

    def step(self, wind: int = 0) -> None:
        """Advance the simulation by one frame.

        Rows ``0..height - 2`` are recomputed (top to bottom, so each row
        reads the not-yet-updated row below it): the new value of cell
        ``(x, y)`` is taken from ``(x, y + 1)``, shifted horizontally by
        ``dst_x = x - wind + choice(-1, 0, 1)`` (clamped to the buffer) and
        decayed by ``randint(decay_min, decay_max)`` (clamped at 0). The
        bottom row — the fuel line — is left untouched.
        """
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
