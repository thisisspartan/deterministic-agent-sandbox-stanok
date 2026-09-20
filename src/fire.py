"""Terminal fire — max-propagation (tropical) heat simulation.

Four layers:
  1. simulation  -- FireSimulation: pure state update, seeded PRNG
  2. palette     -- heat + zone -> RGB: pure
  3. renderer    -- grid -> ANSI truecolor frame string: pure
  4. loop        -- IO only (terminal, ~30 FPS, SIGINT); __main__ guard

Model: a h x w grid, y = 0 is the TOP. Fuel is injected in the bottom
rows (y >= h - BASE_ROWS). Each tick every cell takes the MAX of the
three cells one row below it (the row closer to the fuel) minus a small
seeded random decay. This makes a sharp, multi-tongued front rise with
a slow height gradient, so the whole flame column stays hot and the
full palette (white-hot -> yellow -> orange -> red) is exercised.
"""

import random
import shutil
import signal
import sys
import time

# --- tuning constants ------------------------------------------------------

DEFAULT_WIDTH = 64        # ~60-80: wide flame
DEFAULT_HEIGHT = 32       # ~30-40: tall flame
BASE_ROWS = 3             # fuel (combustion) rows at the bottom
MAX_DECAY = 0.12          # per-row max-propagation decay, uniform in [0, MAX_DECAY]
FUEL_MIN = 0.85           # base fuel floor (white-hot base)
FUEL_MAX = 1.0
FPS = 30
JITTER = 6                # seeded per-cell RGB jitter to break banding
SMOKE_COLOR = (60, 60, 65)
SMOKE_MAX = 120

# Fire heat stops, hot -> cool
_FIRE_STOPS = [
    (1.00, (255, 255, 240)),  # white-hot
    (0.75, (255, 220, 80)),   # yellow
    (0.50, (255, 140, 0)),    # orange
    (0.30, (220, 60, 20)),    # red-orange
    (0.15, (160, 30, 10)),    # red
    (0.05, (90, 15, 8)),      # dark red
]

# Blue-dominant combustion zone: cool -> hot (always b > r)
_BASE_COOL = (80, 120, 255)
_BASE_HOT = (120, 180, 255)


def _clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def _lerp(a, b, t):
    return a + (b - a) * t


# --- layer 1: simulation (pure) ---------------------------------------------


class FireSimulation:
    """Max-propagation fire on a height x width grid (y = 0 is the top)."""

    def __init__(self, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT,
                 base_rows=BASE_ROWS, seed=1):
        self.width = width
        self.height = height
        self.base_rows = base_rows
        self.seed = seed
        self.rng = random.Random(seed)
        self.heat = [[0.0] * width for _ in range(height)]
        self.smoke = []  # list of [x, y, life]
        self._fuel = [self.rng.uniform(FUEL_MIN, FUEL_MAX) for _ in range(width)]
        self._sway = 0

    @property
    def base_top(self):
        """Topmost row index of the fuel band."""
        return self.height - self.base_rows

    def column_top(self, x, threshold=0.3):
        """Topmost lit row of the flame in column x, or None."""
        for y in range(self.height):
            if self.heat[y][x] >= threshold:
                return y
        return None

    def tick(self):
        """Advance the simulation by one frame."""
        w, h = self.width, self.height
        old = self.heat
        new = [[0.0] * w for _ in range(h)]

        # Max propagation: each cell takes the max of the three cells one
        # row below it (out-of-range neighbors count as 0), minus seeded
        # random decay. Heat decays only slowly going up, so the flame
        # column stays hot all the way to the tip.
        for y in range(h - 1):
            below = old[y + 1]
            row = new[y]
            for x in range(w):
                m = below[x]
                if x > 0 and below[x - 1] > m:
                    m = below[x - 1]
                if x + 1 < w and below[x + 1] > m:
                    m = below[x + 1]
                v = m - self.rng.uniform(0.0, MAX_DECAY)
                row[x] = v if v > 0.0 else 0.0

        # Base injection: drive the fuel band hot with per-column variation;
        # the band center sways slowly (random walk) for a living flame.
        self._sway += self.rng.choice((-1, 0, 1))
        limit = max(1, w // 8)
        if self._sway > limit:
            self._sway = limit
        elif self._sway < -limit:
            self._sway = -limit
        center = w // 2 + self._sway
        span = max(1, (w - 1) / 2)
        for y in range(self.base_top, h):
            row = new[y]
            for x in range(w):
                d = abs(x - center) / span
                fuel = _clamp(self._fuel[x] * (1.0 - 0.12 * d * d), 0.0, 1.0)
                if fuel > row[x]:
                    row[x] = fuel

        # Smoke: spawn a particle above a random flame tongue, then drift
        # the existing particles up with a slight horizontal wander.
        tops = []
        for x in range(w):
            t = self.column_top(x)
            if t is not None and t >= 1:
                tops.append((x, t))
        if tops and self.rng.random() < 0.7:
            x, t = self.rng.choice(tops)
            self.smoke.append([x, t - 1, 8 + self.rng.randrange(12)])
        alive = []
        for p in self.smoke:
            p[1] -= 1  # rise
            p[0] += self.rng.choice((-1, 0, 0, 1))
            p[2] -= 1  # fade
            if 0 <= p[1] < h and 0 <= p[0] < w and p[2] > 0:
                alive.append(p)
        self.smoke = alive[:SMOKE_MAX]

        self.heat = new


# --- layer 2: palette (pure) -------------------------------------------------


def palette(heat, is_base=False, seed=0):
    """Map heat in [0, 1] (+ combustion-zone flag) to (r, g, b) or None.

    Fire gradient, hot -> cool: white-hot -> yellow -> orange -> red-orange
    -> red -> dark red.  Combustion-zone cells render a blue-dominant
    gradient by heat (always b > r).  A small SEEDED per-cell jitter
    (deterministic in `seed`) breaks banding.  All channels clamp to
    0..255.  Zero heat -> None (renders as a plain space).
    """
    if heat <= 0.0:
        return None
    heat = _clamp(heat, 0.0, 1.0)

    if is_base:
        r = _lerp(_BASE_COOL[0], _BASE_HOT[0], heat)
        g = _lerp(_BASE_COOL[1], _BASE_HOT[1], heat)
        b = float(_BASE_HOT[2])
    else:
        stops = _FIRE_STOPS
        if heat >= stops[0][0]:
            r, g, b = stops[0][1]
        elif heat <= stops[-1][0]:
            r, g, b = stops[-1][1]
        else:
            for (h1, c1), (h2, c2) in zip(stops, stops[1:]):
                if h2 <= heat <= h1:
                    t = (heat - h2) / (h1 - h2)
                    r = _lerp(c2[0], c1[0], t)
                    g = _lerp(c2[1], c1[1], t)
                    b = _lerp(c2[2], c1[2], t)
                    break

    jr = random.Random(seed).uniform(-JITTER, JITTER)
    jg = random.Random(seed + 1).uniform(-JITTER, JITTER)
    jb = random.Random(seed + 2).uniform(-JITTER, JITTER)
    return (int(_clamp(r + jr, 0.0, 255.0)),
            int(_clamp(g + jg, 0.0, 255.0)),
            int(_clamp(b + jb, 0.0, 255.0)))


# --- layer 3: renderer (pure) --------------------------------------------------


def render(heat, smoke, width, height, base_rows, seed=1):
    """Render the frame as `height` lines of `width` display cells each.

    Lit cells are solid full-block characters (the whole cell is filled),
    smoke cells are faint gray, zero-heat cells are plain spaces (no
    escape).  Color is emitted as 24-bit truecolor ANSI
    (\\x1b[38;2;R;G;B m), only when it changes.
    """
    smoke_set = {(p[0], p[1]) for p in smoke}
    lines = []
    for y in range(height):
        is_base = y >= height - base_rows
        prev = None
        out = []
        for x in range(width):
            hval = heat[y][x]
            if hval > 0.0:
                color = palette(hval, is_base, seed + y * width + x)
                char = "\u2588"  # full block: solid flame
            elif (x, y) in smoke_set:
                color = SMOKE_COLOR
                char = "\u2591"  # light shade: smoke
            else:
                color = None
                char = " "
            if color is not None and color != prev:
                out.append("\x1b[38;2;%d;%d;%d m" % color)
                prev = color
            out.append(char)
        lines.append("".join(out))
    return "\n".join(lines)


# --- layer 4: loop (IO only) -----------------------------------------------------


def main():
    """Animate the fire on a TTY at ~30 FPS; headless/pipe: no animation."""
    if not sys.stdout.isatty():
        return

    term_w, term_h = shutil.get_terminal_size((80, 24))
    width = _clamp(term_w - 8, 24, 72)
    height = _clamp(term_h - 4, 16, 36)
    sim = FireSimulation(int(width), int(height),
                         seed=int(time.monotonic() * 1000) % (2 ** 31))

    def _restore(*_):
        # SIGINT: restore cursor, reset ANSI, exit 0.
        sys.stdout.write("\x1b[?25h\x1b[0m\n")
        sys.stdout.flush()
        sys.exit(0)

    signal.signal(signal.SIGINT, _restore)

    frame_dt = 1.0 / FPS
    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()
    try:
        while True:
            t0 = time.monotonic()
            sim.tick()
            frame = render(sim.heat, sim.smoke, sim.width, sim.height,
                           sim.base_rows, seed=sim.seed)
            left = " " * (max(0, term_w - sim.width) // 2)
            top = "\n" * max(0, (term_h - sim.height) // 2)
            sys.stdout.write("\x1b[2J\x1b[H" + top
                             + "\n".join(left + line for line in frame.split("\n")))
            sys.stdout.flush()
            time.sleep(max(0.0, frame_dt - (time.monotonic() - t0)))
    finally:
        sys.stdout.write("\x1b[?25h\x1b[0m")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
