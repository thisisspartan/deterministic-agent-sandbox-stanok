"""Multicolored animated terminal fire.

Four separated concerns:
  * simulation — pure tick(): 2D heat field (injection, upward diffusion,
    cooling, turbulence), base-zone flags, rising smoke particles;
  * palette    — pure palette(heat, is_base) -> (r, g, b) | None with a
    multi-stop hot->cool gradient, a blue combustion-base gradient and a
    seeded per-cell jitter to break color banding;
  * renderer   — pure render_frame(): grid + particles -> one ANSI frame
    using half-block (U+2580) cells;
  * loop       — IO only, runs ONLY under `if __name__ == "__main__"`.

Run:  python3 src/fire.py      Stop: Ctrl-C (cursor restored, ANSI reset, exit 0)
"""
import os
import random
import shutil
import signal
import sys
import time

BLOCK = "\u2580"  # half-block: doubles vertical resolution
ZERO = None

_PALETTE_STOPS = (  # (heat, r, g, b) — hottest first
    (1.00, 255, 255, 240),  # white-hot core
    (0.65, 255, 220, 80),   # yellow
    (0.45, 255, 140, 0),    # orange
    (0.25, 220, 60, 20),    # red-orange
    (0.15, 160, 30, 10),    # red tips
    (0.05, 90, 15, 8),      # dark red
    (0.00, 0, 0, 0),        # -> None (empty cell)
)
_BASE_STOPS = ((1.0, 120, 180, 255), (0.0, 80, 120, 255))  # blue combustion base
_SMOKE_RGB = (60, 60, 65)                                  # faint gray smoke

BASE_ROWS = 2   # combustion zone height (bottom rows)
BASE_MIN_HEAT = 0.25


def _interp(stops, t):
    """Linear interpolation over (t, r, g, b) stops, ordered hot->cool."""
    t = min(1.0, max(0.0, t))
    for (t1, r1, g1, b1), (t2, r2, g2, b2) in zip(stops, stops[1:]):
        if t1 >= t >= t2:
            if t1 == t2:
                f = 0.0
            else:
                f = (t1 - t) / (t1 - t2)
            return (
                int(round(r1 + (r2 - r1) * f)),
                int(round(g1 + (g2 - g1) * f)),
                int(round(b1 + (b2 - b1) * f)),
            )
    return stops[-1][1:]


def _jitter(x, y, seed):
    """Deterministic per-cell color jitter in [-2, 2], independent of frames."""
    h = (x * 374761393 + y * 668265263 + seed * 974634561) & 0xFFFFFFFF
    h = ((h ^ (h >> 13)) * 1274126177) & 0xFFFFFFFF
    return ((h & 7) - 3)


def palette(heat, is_base):
    """(heat in [0,1], is_base) -> (r, g, b) with jitter, or None when cold."""
    heat = min(1.0, max(0.0, float(heat)))
    if heat <= 0.0:
        return None
    if is_base:
        rgb = _interp(_BASE_STOPS, heat)
    else:
        rgb = _interp(_PALETTE_STOPS, heat)
    return tuple(max(0, min(255, ch)) for ch in rgb)


def _step_state(grid, base, particles, rng, base_x0, base_x1):
    """One deterministic simulation tick. Returns (grid, base, particles,
    base_x0, base_x1) — the new state; inputs are untouched."""
    h = len(grid)
    w = len(grid[0])
    old = grid

    # global flicker: frame-level intensity noise
    flicker = min(1.15, max(0.82, 1.0 + rng.uniform(-0.18, 0.18)))

    # fuel sways horizontally: random walk of the injection band
    step = rng.choice((-1, 1))
    base_x0 = min(max(1, base_x0 + step), w // 2 - 3)
    base_x1 = min(w - 2, base_x1 + rng.choice((-1, 1)))
    base_w = base_x1 - base_x0 + 1

    # turbulence: per-column horizontal shift (value-noise style)
    turb = [rng.choice((-1, 0, 0, 0, 1)) for _ in range(w)]
    # occasional "lick": a patch of columns gets boosted sideways
    if rng.random() < 0.30:
        cx = rng.randrange(w)
        boost = rng.choice((-1, 1)) * rng.choice((1, 2))
        for i in range(w):
            d = abs(i - cx)
            if d < 5:
                turb[i] = max(-2, min(2, turb[i] + (boost * (5 - d) // 5)))

    # inject fuel at the base, per-column strength varies (multiple tongues)
    inj = [rng.uniform(0.65, 1.0) * flicker for _ in range(w)]

    # NOTE: y = 0 is the TOP of the grid; heat rises toward smaller y,
    # fuel is injected in the bottom rows (y >= h - BASE_ROWS).
    new = [[0.0] * w for _ in range(h)]
    for y in range(h):
        for x in range(w):
            v = old[y][x]
            # turbulence: pull a fraction of this cell's heat from sideways
            t = turb[x]
            if t and 0 <= x + t < w and old[y][x + t] > v:
                v = v + (old[y][x + t] - v) * 0.25
            # diffusion upward (heat rises from the row below) with lateral spread
            down = old[y + 1][x] if y + 1 < h else 0.0
            l = old[y][x - 1] if x > 0 else 0.0
            r = old[y][x + 1] if x + 1 < w else 0.0
            v = v * 0.68 + 0.17 * down + 0.075 * (l + r)
            # fresh fuel meets air at the combustion base
            if h - BASE_ROWS <= y < h and base_x0 <= x < base_x1:
                v = max(v, min(1.0, inj[x - base_x0]))
            # cooling
            v *= 0.90
            new[y][x] = min(1.0, max(0.0, v))

    # combustion zone: the bottom rows where fuel actually burns
    new_base = [[False] * w for _ in range(h)]
    for y in range(h - BASE_ROWS, h):
        for x in range(w):
            if new[y][x] >= BASE_MIN_HEAT:
                new_base[y][x] = True

    # smoke: sparse deterministic particles, rise + fade above the flame top
    parts = []
    for p in particles:
        ny = p["y"] - 1
        no = p["o"] - 0.016
        if ny >= 0 and no > 0.04:
            parts.append({
                "x": min(w - 1, max(0, p["x"] + rng.choice((-1, 0, 0, 1)))),
                "y": ny,
                "o": no,
            })
    heat_ys = [y for y in range(h) if any(v > 0.0 for v in new[y])]
    if heat_ys:
        top = min(heat_ys)
        spawn = len(particles) == 0 or rng.random() < 0.55
        if spawn and top > 2:
            parts.append({
                "x": min(w - 1, max(0, rng.randrange(base_x0, base_x1 + 1))),
                "y": min(h - 1, top - 1),
                "o": 1.0,
            })

    return new, new_base, parts, flicker, base_x0, base_x1


def render_frame(grid, base, particles, flicker, seed=0):
    """grid (h x w heat) + base flags + smoke particles -> one ANSI frame.

    Frame dimensions match the grid: w characters per line, h lines.
    Zero heat -> plain space, no escape sequence. A small deterministic
    seeded per-cell jitter breaks color banding.
    """
    h = len(grid)
    w = len(grid[0])
    rows = []
    for y in range(h):
        cells = []
        for x in range(w):
            v = grid[y][x]
            col = palette(v * flicker, base[y][x]) if v > 0 else None
            if col is not None:
                j = _jitter(x, y, seed)
                col = tuple(max(0, min(255, ch + j // 3)) for ch in col)
                cells.append("\x1b[38;2;%d;%d;%d m%s" % (col[0], col[1], col[2], BLOCK))
            else:
                cells.append(" ")
        rows.append(cells)
    for p in particles:
        if 0 <= p["y"] < h and 0 <= p["x"] < w:
            rows[p["y"]][p["x"]] = "\x1b[38;2;%d;%d;%d m%s" % (_SMOKE_RGB + (BLOCK,))
    return "\n".join("".join(cells) for cells in rows)


class Fire:
    """Seeded deterministic fire: .step() advances, .frame() renders."""

    def __init__(self, width=40, height=30, seed=7):
        self.w = width
        self.h = height
        self.seed = seed
        self.rng = random.Random(seed)
        self.grid = [[0.0] * width for _ in range(height)]
        self.base = [[False] * width for _ in range(height)]
        self.particles = []
        self.flicker = 1.0
        self.base_x0 = width // 4
        self.base_x1 = width // 2 + width // 8
        self.step_count = 0

    def step(self):
        self.grid, self.base, self.particles, self.flicker, \
            self.base_x0, self.base_x1 = _step_state(
                self.grid, self.base, self.particles,
                self.rng, self.base_x0, self.base_x1)
        self.step_count += 1

    def frame(self):
        return render_frame(self.grid, self.base, self.particles, self.flicker)


def _run():
    if not sys.stdout.isatty():
        # headless (pipe / CI smoke): load is enough, no animation
        return
    size = shutil.get_terminal_size((80, 24))
    fd = sys.stdout.fileno()

    def emit(s):
        # os.write: no Python-level buffering, safe from a signal handler
        os.write(fd, s.encode("utf-8"))

    def _sigint(signum, frame):
        emit("\x1b[?25h\x1b[0m\n")  # restore cursor, reset ANSI state
        sys.exit(0)

    signal.signal(signal.SIGINT, _sigint)

    f = Fire(width=40, height=24, seed=int(time.time() * 1000) & 0x7FFFFFFF)
    x_off = max(0, (size.columns - f.w) // 2)
    y_off = max(0, (size.lines - f.h) // 2)

    emit("\x1b[?25l")  # hide cursor
    for line in f.frame().split("\n"):
        emit(" " * x_off + line + "\n")

    fps = 30
    dt = 1.0 / fps
    while True:
        time.sleep(dt)
        f.step()
        buf = ["\x1b[H"]  # clear screen / home cursor
        for y, line in enumerate(f.frame().split("\n")):
            row = y_off + y
            if 0 <= row < size.lines:
                buf.append("\x1b[%d;%dH%s\n" % (row + 1, x_off + 1, line))
        emit("".join(buf))


if __name__ == "__main__":
    _run()
