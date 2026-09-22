"""fire_color — realistic multicolored terminal fire.

Four separated concerns:
  1. Simulation  — new_state() / step(): a 2D heat field with base injection,
                   upward diffusion, cooling, turbulence (seeded PRNG),
                   a combustion base-zone flag, and sparse smoke particles.
  2. Palette     — palette(heat, is_base, salt): multi-stop hot->cool RGB
                   gradient with a blue combustion gradient and seeded
                   per-cell jitter.
  3. Renderer    — render(state): grid + smoke particles -> one ANSI frame
                   (24-bit truecolor, half-block `U+2580` characters).
  4. Loop        — main(): the only IO. Interactive (both stdin/stdout are
                   ttys) runs the animated loop; otherwise a short headless
                   frame dump so smoke/preview runs exit cleanly.

Deterministic: same seed -> identical frames. Stdlib only.
"""

import os
import random
import shutil
import signal
import sys
import time

SMOKE_ROWS = 6      # reserved rows above the heat grid for smoke
BASE_ROWS = 2       # bottom rows that form the blue combustion zone
HALF_BLOCK = "\u2580"  # ▀ : vertical resolution via the upper half cell

# Heat (hot -> cool) multi-stop gradient: (heat, (r, g, b))
_STOPS = (
    (1.00, (255, 255, 240)),  # white-hot core
    (0.80, (255, 220, 80)),   # yellow
    (0.60, (255, 140, 0)),    # orange
    (0.45, (220, 60, 20)),    # red-orange
    (0.30, (160, 30, 10)),    # red
    (0.15, (90, 15, 8)),      # dark red
    (0.00, (25, 8, 5)),       # embers at zero heat (exact 0.0 -> None)
)
_BASE_LO = (80, 120, 255)   # blue combustion, low heat
_BASE_HI = (120, 180, 255)  # blue combustion, high heat
_SMOKE = (60, 60, 65)       # faint gray smoke


class State:
    """Simulation state: heat grid (row 0 = bottom), base flags, smoke."""

    def __init__(self, width, height, seed):
        self.width = width
        self.height = height          # heat-field rows (flame body)
        self.smoke_rows = SMOKE_ROWS
        self.seed = seed
        self.rng = random.Random(seed)
        self.heat = [[0.0] * width for _ in range(height)]
        self.base = [[False] * width for _ in range(height)]
        self.smoke = []               # list of [y, x, life]; y may exceed height

    @property
    def grid_height(self):
        return self.height + self.smoke_rows


def new_state(width, height, seed):
    """Create a fresh (empty) simulation state for the given seed."""
    return State(width, height, seed)


def _interp(t, lo, hi):
    return tuple(int(round(lo[i] + (hi[i] - lo[i]) * t)) for i in range(3))


def palette(heat, is_base, salt=0.5):
    """(heat, is_base, salt) -> (r, g, b) | None.

    heat must be in [0, 1]; salt in [0, 1) seeds a small per-cell jitter
    that breaks color banding. Zero heat -> None (empty cell).
    """
    if heat <= 0.0:
        return None
    heat = min(1.0, heat)
    if is_base:
        t = min(1.0, max(0.0, (heat - 0.15) / 0.85))
        c = _interp(t, _BASE_LO, _BASE_HI)
    else:
        for (h_hi, c_hi), (h_lo, c_lo) in zip(_STOPS, _STOPS[1:]):
            if heat >= h_lo:
                t = (heat - h_lo) / (h_hi - h_lo)
                c = _interp(t, c_lo, c_hi)
                break
        else:
            c = _STOPS[-1][1]
    jitter = (salt - 0.5) * 14.0
    return tuple(max(0, min(255, int(round(ch + jitter)))) for ch in c)


def _salt(row, col, seed):
    """Deterministic per-cell salt in [0, 1) from coordinates + seed."""
    h = (row * 374761393 + col * 668265263 + seed * 69069 + 1013904223) & 0xFFFFFF
    return h / 2 ** 24


def step(st):
    """Advance the simulation one tick (in place; returns the state)."""
    rng = st.rng
    W, H = st.width, st.height
    old = st.heat
    new = [[0.0] * W for _ in range(H)]
    center = (W - 1) / 2.0

    # Per-frame global flicker.
    gain = rng.uniform(0.85, 1.10)

    # 1) Fuel injection at the base: wide, tapering toward the edges.
    for x in range(W):
        d = abs(x - center) / center
        if d <= 1.0:
            v = (1.0 - d * d) * 1.15 * gain + rng.uniform(-0.08, 0.12)
            new[0][x] = min(1.0, max(0.0, v))

    # 2) Upward advection: diffusion, per-row decay, center taper and
    #    turbulence (random horizontal mixing + licks/gaps).
    for y in range(1, H):
        decay = 1.0 - (0.045 + 0.03 * y / H)
        taper = 0.55 * (y / H) ** 1.6
        for x in range(W):
            a, b = rng.random(), rng.random()
            w0 = 0.55 + a * 0.45
            wl = b * 0.35
            wr = (1.0 - b) * 0.35
            mid = old[y - 1][x]
            lo = old[y - 1][x - 1] if x > 0 else 0.0
            hi = old[y - 1][x + 1] if x < W - 1 else 0.0
            v = (mid * w0 + lo * wl + hi * wr) / (w0 + wl + wr)
            v *= decay
            d = abs(x - center) / center
            v *= max(0.0, 1.0 - taper * d * d)
            r = rng.random()
            if r < 0.05:
                v += rng.uniform(0.15, 0.40)   # upward lick
            elif r < 0.09:
                v *= 0.35                      # cooling gap
            new[y][x] = min(1.0, max(0.0, v * gain))

    # 3) Combustion base zone: bottom rows with live heat (blue in a real
    #    flame — where fresh fuel meets air).
    base = [[False] * W for _ in range(H)]
    for y in range(min(BASE_ROWS, H)):
        for x in range(W):
            if new[y][x] > 0.15:
                base[y][x] = True

    # 4) Smoke: sparse deterministic particles that rise above the flame
    #    top and fade out.
    top = -1
    for y in range(H - 1, -1, -1):
        if max(new[y]) > 0.15:
            top = y
            break
    smoke = []
    for py, px, pl in st.smoke:
        pl -= 0.12
        if pl <= 0.0:
            continue
        py += 1
        if rng.random() < 0.25:
            px -= 1
        elif rng.random() < 0.25:
            px += 1
        px = max(0, min(W - 1, px))
        if py >= st.grid_height:
            continue
        smoke.append([py, px, pl])
    if rng.random() < 0.6:
        sx = int(center + rng.uniform(-W * 0.12, W * 0.12))
        smoke.append([max(1, top + 2), max(0, min(W - 1, sx)), 1.0])

    st.heat, st.base, st.smoke = new, base, smoke
    return st


def render(st):
    """State -> one ANSI frame string (24-bit truecolor, ▀ half-blocks)."""
    W, H = st.width, st.grid_height
    sm = {}
    for py, px, _pl in st.smoke:
        if st.height <= py < H:
            sm.setdefault(py, set()).add(px)
    lines = []
    for f in range(H):            # frame row 0 = top
        y = H - 1 - f             # grid row 0 = bottom
        parts = []
        last = None
        if y < st.height:
            heat_row, base_row = st.heat[y], st.base[y]
            for x in range(W):
                c = palette(heat_row[x], base_row[x], _salt(y, x, st.seed))
                if c is None:
                    if last is not None:
                        parts.append("\x1b[0m")
                        last = None
                    parts.append(" ")
                else:
                    if c != last:
                        parts.append("\x1b[38;2;%d;%d;%d m" % c)
                        last = c
                    parts.append(HALF_BLOCK)
        else:
            cells = sm.get(y)
            for x in range(W):
                if cells and x in cells:
                    c = _SMOKE
                    if c != last:
                        parts.append("\x1b[38;2;%d;%d;%d m" % c)
                        last = c
                    parts.append(HALF_BLOCK)
                else:
                    if last is not None:
                        parts.append("\x1b[0m")
                        last = None
                    parts.append(" ")
        if last is not None:
            parts.append("\x1b[0m")
        lines.append("".join(parts))
    return "\n".join(lines)


def _run_interactive():
    try:
        tw, th = shutil.get_terminal_size()
    except OSError:
        tw, th = 80, 24
    W = max(20, min(46, tw - 2))
    total_h = max(10, min(20, th - 2))
    H = total_h - SMOKE_ROWS
    st = new_state(W, H, seed=int(time.time() * 1000) % 100000)
    out = sys.stdout
    out.write("\x1b[2J\x1b[?25l")  # clear screen, hide cursor
    out.flush()
    stop = [False]

    def flag_stop(_signum, _frame):  # no IO here: the handler may fire mid-write
        stop[0] = True

    signal.signal(signal.SIGINT, flag_stop)
    signal.signal(signal.SIGTERM, flag_stop)
    left = (tw - W) // 2
    top_pad = [" "] * max(0, (th - total_h) // 2)
    try:
        while not stop[0]:
            step(st)
            frame = render(st)
            out.write("\x1b[H" + "\n".join(top_pad + frame.split("\n")) + "\x1b[0m")
            out.flush()
            time.sleep(1.0 / 30.0)
    except (KeyboardInterrupt, RuntimeError):  # safety nets; cleanup below
        pass
    out.write("\x1b[?25h\x1b[0m")  # restore cursor, reset ANSI
    out.flush()
    sys.exit(0)


def _run_headless():
    """Non-tty mode: dump 30 frames and exit cleanly (smoke/preview)."""
    st = new_state(40, 18, seed=42)
    out = sys.stdout
    try:
        for _ in range(30):
            step(st)
            out.write(render(st) + "\n")
            out.flush()
            time.sleep(1.0 / 30.0)
    except BrokenPipeError:  # consumer (e.g. `head -c N`) stopped reading
        try:
            os.dup2(os.open(os.devnull, os.O_WRONLY), out.fileno())
        except OSError:
            pass
        sys.exit(0)


def main():
    if sys.stdin.isatty() and sys.stdout.isatty():
        _run_interactive()
    else:
        _run_headless()


if __name__ == "__main__":
    main()
