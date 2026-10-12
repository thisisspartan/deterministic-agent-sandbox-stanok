"""Pure Doom fire engine (TASK-STANOK-CC-248): palette + fire matrix + step.

No terminal codes, no I/O — pure math. The buffer is a flat list indexed
buffer[y * width + x], y=0 top, y=height-1 is the source row (seeded to 36).
"""

import random

# The classic Doom fire palette: 37 RGB tuples, index == fire intensity.
PALETTE = [
    (0x07, 0x07, 0x07), (0x1F, 0x07, 0x07), (0x2F, 0x0F, 0x07),
    (0x47, 0x0F, 0x07), (0x57, 0x17, 0x07), (0x67, 0x1F, 0x07),
    (0x77, 0x1F, 0x07), (0x8F, 0x27, 0x07), (0x9F, 0x2F, 0x07),
    (0xAF, 0x3F, 0x07), (0xBF, 0x47, 0x07), (0xC7, 0x47, 0x07),
    (0xDF, 0x4F, 0x07), (0xDF, 0x57, 0x07), (0xDF, 0x57, 0x07),
    (0xD7, 0x5F, 0x07), (0xD7, 0x67, 0x0F), (0xCF, 0x6F, 0x0F),
    (0xCF, 0x77, 0x0F), (0xCF, 0x7F, 0x0F), (0xCF, 0x87, 0x17),
    (0xC7, 0x87, 0x17), (0xC7, 0x8F, 0x17), (0xC7, 0x97, 0x1F),
    (0xBF, 0x9F, 0x1F), (0xBF, 0x9F, 0x1F), (0xBF, 0xA7, 0x27),
    (0xBF, 0xA7, 0x27), (0xBF, 0xAF, 0x2F), (0xB7, 0xAF, 0x2F),
    (0xB7, 0xB7, 0x2F), (0xB7, 0xB7, 0x37), (0xCF, 0xCF, 0x6F),
    (0xDF, 0xDF, 0x9F), (0xEF, 0xEF, 0xC7), (0xFF, 0xFF, 0xFF),
    (0xFF, 0xFF, 0xFF),
]

MAX_INTENSITY = 36
WIND_LIMIT = 3


class FireField:
    """Fire matrix with the exact Doom propagation step (single bottom-up pass).

    rng is an injectable random.Random (default: the module random) so tests
    are deterministic.
    """

    def __init__(self, width, height, rng=None):
        self.width = width
        self.height = height
        self.rng = random if rng is None else rng
        self.buffer = [0] * (width * height)
        base = (height - 1) * width
        for i in range(base, base + width):
            self.buffer[i] = MAX_INTENSITY

    def step(self, wind=0):
        wind = max(-WIND_LIMIT, min(WIND_LIMIT, wind))
        w, buf, rng = self.width, self.buffer, self.rng
        for y in range(self.height - 1, 0, -1):
            row = y * w
            above = row - w
            for x in range(w):
                src = buf[row + x]
                if src == 0:
                    buf[above + x] = 0
                    continue
                rand = rng.randint(0, 3)
                dst = x - rand + 1 + wind
                if 0 <= dst < w:
                    buf[above + dst] = max(0, src - (rand & 1))
                # out-of-bounds dst: skip, no wrap

    def color_at(self, value):
        return PALETTE[value]
