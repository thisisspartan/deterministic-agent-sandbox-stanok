"""fire_sim — stage 1 of the console-fire pipeline: pure, seeded numerics.

Simulation + palette only: no rendering, no CLI, no IO, no module-level RNG,
no global state, no time. All randomness flows through an explicit
random.Random passed by the caller (or created inside simulate from `seed`),
so the same seed + same dimensions always produce identical fields, and the
same heat + same rng state always produce identical RGB.

The contract is documented in docs/fire_sim.md and pinned by
tests/fire_sim_test.py. The renderer and CLI are later tickets built on top
of these names.
"""

import random

DEFAULT_SEED = 1
IGNITION_LOW = 0.85      # base-row values are re-ignited into [IGNITION_LOW, 1.0]
COOL_LOW = 0.02          # per-step cooling factor bounds
COOL_HIGH = 0.18
EMPTY_THRESHOLD = 0.05   # heat below this is an empty cell

# Internal: upward bleed drawn from the cell directly below. It is kept well
# below the mean cooling factor so heat decays geometrically with height
# (steady state per row: h_next ~= bleed/cool * h_below, ratio < 1).
_BLEED_LOW = 0.02
_BLEED_HIGH = 0.08

# Palette stops: heat -> (r, g, b), dark red -> orange -> yellow -> near-white.
_STOPS = (
    (0.0, (60, 8, 0)),
    (0.35, (200, 70, 0)),
    (0.65, (255, 190, 30)),
    (1.0, (255, 245, 220)),
)
_JITTER = 12.0  # max per-channel color jitter drawn from rng


def new_field(width: int, height: int) -> list[list[float]]:
    """A cold field: height rows x width columns, all values in [0, 1].

    Row 0 is the top, the last row is the combustion zone (ignited by the
    first advance). Raises ValueError if width < 1 or height < 1.
    """
    if width < 1 or height < 1:
        raise ValueError(
            f"width and height must be >= 1 (got width={width}, height={height})"
        )
    return [[0.0] * width for _ in range(height)]


def advance(field: list[list[float]], rng: random.Random) -> list[list[float]]:
    """One simulation step. Pure: `field` is never mutated; a new field of
    the same shape is returned.

    Bottom row: re-ignited each step into [IGNITION_LOW, 1.0].
    Other cells: current value reduced by a cooling factor drawn from
    [COOL_LOW, COOL_HIGH], plus a small upward bleed from the cell directly
    below (read from the OLD field). Every value is clamped to [0, 1].
    Draws rng values in a fixed row-major order, so the step is a pure
    function of (field, rng state).
    """
    height = len(field)
    width = len(field[0]) if height else 0
    out: list[list[float]] = []
    for r in range(height):
        row = field[r]
        new_row: list[float] = []
        for c in range(width):
            if r == height - 1:
                new_row.append(rng.uniform(IGNITION_LOW, 1.0))
            else:
                cool = rng.uniform(COOL_LOW, COOL_HIGH)
                bleed = rng.uniform(_BLEED_LOW, _BLEED_HIGH)
                value = row[c] * (1.0 - cool) + bleed * field[r + 1][c]
                new_row.append(min(1.0, max(0.0, value)))
        out.append(new_row)
    return out


def simulate(seed: int, width: int, height: int, n: int) -> list[list[list[float]]]:
    """n successive fields starting from new_field(width, height).

    All randomness comes from a single random.Random(seed); field[i] is the
    field after i + 1 advances. Raises ValueError if n < 1 (or if the
    dimensions are invalid, via new_field).
    """
    if n < 1:
        raise ValueError(f"n must be >= 1 (got {n})")
    rng = random.Random(seed)
    field = new_field(width, height)
    fields: list[list[list[float]]] = []
    for _ in range(n):
        field = advance(field, rng)
        fields.append(field)
    return fields


def heat_to_rgb(heat: float, rng: random.Random) -> tuple[int, int, int] | None:
    """Map heat to a 24-bit RGB, or None for an empty cell.

    heat outside [0, 1] -> ValueError.
    heat < EMPTY_THRESHOLD -> None.
    Otherwise: linear interpolation between the _STOPS gradient (dark red ->
    orange -> yellow -> near-white as heat approaches 1.0) plus a small
    per-channel jitter drawn from rng; each channel clamped to 0..255.
    """
    if heat < 0.0 or heat > 1.0:
        raise ValueError(f"heat must be in [0, 1] (got {heat})")
    if heat < EMPTY_THRESHOLD:
        return None

    for (h0, c0), (h1, c1) in zip(_STOPS, _STOPS[1:]):
        if heat <= h1:
            t = (heat - h0) / (h1 - h0)
            base = tuple(c0[i] + (c1[i] - c0[i]) * t for i in range(3))
            break

    return tuple(
        max(0, min(255, int(base[i] + rng.uniform(-_JITTER, _JITTER))))
        for i in range(3)
    )
