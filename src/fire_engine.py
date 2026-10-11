"""fire_engine — pure Doom Fire palette + propagation engine (TASK-STANOK-CC-240).

No terminal codes, no file/socket I/O: this module is pure math over a flat
buffer. Contract (stdlib only, `random`):

- PALETTE: exactly 37 RGB tuples, the classic Doom fire palette. Index 0 is
  the darkest, index 36 the brightest.

- FireField(width, height, rng=None): a fire matrix stored as a flat list
  indexed `buffer[y * width + x]`, y=0 is the top row and y=height-1 is the
  source row, seeded to 36. Every other cell starts at 0. `rng` is an
  injectable random.Random (defaults to the module-level `random`) so tests
  are deterministic.

- step(wind=0): one bottom-up propagation pass. For y from height-1 down to
  1, for each x:
    * src = buffer[y][x]; if src == 0 -> buffer[y-1][x] = 0.
    * else: rand = rng.randint(0, 3); dst = x - rand + 1 + wind; if
      0 <= dst < width: buffer[y-1][dst] = max(0, src - (rand & 1)).
      An out-of-bounds dst is skipped (no wrap). `wind` is clamped to
      [-3, 3]. The source row is only ever read, never written.

- color_at(value) -> PALETTE[value]; value is always 0..36 by construction.
"""

import random

# The classic Doom fire palette: 37 RGB tuples, dark -> bright.
PALETTE = [
    (0x07, 0x07, 0x07), (0x1F, 0x07, 0x07), (0x2F, 0x0F, 0x07), (0x47, 0x0F, 0x07),
    (0x57, 0x17, 0x07), (0x67, 0x1F, 0x07), (0x77, 0x1F, 0x07), (0x8F, 0x27, 0x07),
    (0x9F, 0x2F, 0x07), (0xAF, 0x3F, 0x07), (0xBF, 0x47, 0x07), (0xC7, 0x47, 0x07),
    (0xDF, 0x4F, 0x07), (0xDF, 0x57, 0x07), (0xDF, 0x57, 0x07), (0xD7, 0x5F, 0x07),
    (0xD7, 0x67, 0x0F), (0xCF, 0x6F, 0x0F), (0xCF, 0x77, 0x0F), (0xCF, 0x7F, 0x0F),
    (0xCF, 0x87, 0x17), (0xC7, 0x87, 0x17), (0xC7, 0x8F, 0x17), (0xC7, 0x97, 0x1F),
    (0xBF, 0x9F, 0x1F), (0xBF, 0x9F, 0x1F), (0xBF, 0xA7, 0x27), (0xBF, 0xA7, 0x27),
    (0xBF, 0xAF, 0x2F), (0xB7, 0xAF, 0x2F), (0xB7, 0xB7, 0x2F), (0xB7, 0xB7, 0x37),
    (0xCF, 0xCF, 0x6F), (0xDF, 0xDF, 0x9F), (0xEF, 0xEF, 0xC7), (0xFF, 0xFF, 0xFF),
    (0xFF, 0xFF, 0xFF),
]

# The brightest value a source row is seeded to (top of the palette).
SOURCE_VALUE = 36

# Wind is a small horizontal bias; it is clamped to this range.
_WIND_LIMIT = 3


class FireField:
    """A Doom fire matrix over a flat buffer, indexed `buffer[y * width + x]`.

    y=0 is the top row; y=height-1 is the source row, seeded to 36. Pass an
    explicit `random.Random` as `rng` for deterministic propagation.
    """

    def __init__(self, width, height, rng=None):
        self.width = width
        self.height = height
        self.rng = random if rng is None else rng
        self.buffer = [0] * (width * height)
        base = (height - 1) * width
        for x in range(width):
            self.buffer[base + x] = SOURCE_VALUE

    def step(self, wind=0):
        """Advance the fire one frame: a single bottom-up propagation pass.

        Each non-zero source pixel spreads upward to `dst = x - rand + 1 + wind`
        (rand in [0,3]) with value `max(0, src - (rand & 1))`; a zero source
        propagates zero; an out-of-bounds dst is skipped (no wrap). `wind` is
        clamped to [-3, 3]. The source row is read-only.
        """
        width, height, buf = self.width, self.height, self.buffer
        wind = max(-_WIND_LIMIT, min(_WIND_LIMIT, wind))
        for y in range(height - 1, 0, -1):
            src_row = y * width
            dst_row = (y - 1) * width
            for x in range(width):
                src = buf[src_row + x]
                if src == 0:
                    buf[dst_row + x] = 0
                else:
                    rand = self.rng.randint(0, 3)
                    dst = x - rand + 1 + wind
                    if 0 <= dst < width:
                        buf[dst_row + dst] = max(0, src - (rand & 1))


def color_at(value):
    """Return the palette color for a fire value (value is 0..36 by construction)."""
    return PALETTE[value]
