"""doomfire core model — the classic DOOM fire effect, pure math, no I/O.

A heat field is a ``list[list[int]]``: rows top->bottom, ``field[-1]`` is
the bottom (source) row, every cell an int in ``[0, 255]``.

All randomness flows through the passed ``rng`` object (any object with
``randint``/``choice``; ``random.Random`` in practice). The RNG call order
is part of the contract — rows top->bottom, columns left->right, ``off``
before ``decay``, ``seed_bottom`` last — so a run is reproducible for a
given ``rng``.

This module imports only ``random`` and performs no I/O.
"""

import random


def create_field(width: int, height: int) -> list[list[int]]:
    """Create an all-zero heat field of the given size.

    Raises ValueError if width < 1 or height < 1.
    """
    if width < 1 or height < 1:
        raise ValueError(
            f"field dimensions must be >= 1 (got width={width}, height={height})"
        )
    return [[0] * width for _ in range(height)]


def seed_bottom(field, rng) -> None:
    """Mutate the bottom (source) row in place: each cell = rng.randint(128, 255)."""
    bottom = field[-1]
    for x in range(len(bottom)):
        bottom[x] = rng.randint(128, 255)


def step(field, rng) -> list[list[int]]:
    """Advance the field by one frame; returns a NEW field (input untouched).

    For each row y in 0..height-2 top->bottom, for each x left->right:
        off   = rng.choice([-1, 0, 1])
        decay = rng.randint(1, 3)
        new[y][x] = max(0, field[y+1][clamp(x + off, 0, width-1)] - decay)
    Then the bottom row of the new field is reseeded.
    """
    height = len(field)
    width = len(field[0])
    new = [row[:] for row in field]
    for y in range(height - 1):
        src_row = field[y + 1]
        new_row = new[y]
        for x in range(width):
            off = rng.choice([-1, 0, 1])
            decay = rng.randint(1, 3)
            src_x = x + off
            if src_x < 0:
                src_x = 0
            elif src_x > width - 1:
                src_x = width - 1
            new_row[x] = max(0, src_row[src_x] - decay)
    seed_bottom(new, rng)
    return new


def simulate(width: int, height: int, steps: int, seed: int) -> list[list[int]]:
    """Convenience driver: seeded Random, create_field, seed_bottom, steps x step.

    steps >= 0; steps == 0 returns the seeded field.
    """
    rng = random.Random(seed)
    field = create_field(width, height)
    seed_bottom(field, rng)
    for _ in range(steps):
        field = step(field, rng)
    return field
