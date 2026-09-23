"""Deterministic multicolor terminal fire (CC-109).

Four separated concerns:
  1. Simulation  -- FireSim: a pure, deterministic 2D heat field in [0, 1]
                    plus a sparse smoke-particle list (seeded PRNG).
  2. Palette     -- palette(heat, is_base) -> (r, g, b) | None and
                    jittered_rgb(rgb, x, y) for banding-free truecolor.
  3. Renderer    -- render(sim): grid + particles -> one ANSI frame string
                    (half-block `U+2580` characters, 24-bit truecolor).
  4. Loop        -- main(): IO only, started under `if __name__ == "__main__"`.

Stdlib only. No IO happens at import time.

CLI:  python3 src/fire.py [--seed N] [--width W] [--height H] [--fps N]
                           [--frames N] [--frame N]
No TTY (or --frames / --frame) -> render frames to stdout and exit 0.
"""

import argparse
import random
import sys

# ---------------------------------------------------------------------------
# Palette (pure)
# ---------------------------------------------------------------------------

BLANK_THRESHOLD = 0.05  # heat below this renders as an empty cell (<= 0.10)

# Multi-stop hot -> cool gradient (white-hot -> yellow -> orange ->
# red-orange -> red -> dark red).  heat is clamped into [0, 1].
_STOPS = (
    (0.00, (60, 10, 5)),
    (0.12, (90, 15, 8)),
    (0.25, (160, 30, 10)),
    (0.40, (220, 60, 20)),
    (0.55, (255, 140, 0)),
    (0.75, (255, 220, 80)),
    (1.00, (255, 255, 240)),
)

SMOKE_RGB = (60, 60, 65)


def _lerp(a, b, t):
    return round(a + (b - a) * t)


def palette(heat, is_base):
    """(heat, is_base) -> (r, g, b) | None. Pure.

    heat below BLANK_THRESHOLD -> None (empty cell).  Base-zone cells
    (the blue combustion zone) render a blue-dominant gradient by heat.
    """
    if heat < BLANK_THRESHOLD:
        return None
    heat = min(1.0, max(0.0, heat))
    if is_base:
        # Blue combustion gradient: always b > r.
        t = (heat - BLANK_THRESHOLD) / (1.0 - BLANK_THRESHOLD)
        r = _lerp(15, 75, t)
        g = _lerp(25, 125, t)
        b = _lerp(110, 255, t)
        return (r, g, b)
    # Piecewise-linear gradient between the hot -> cool stops.
    for (h0, c0), (h1, c1) in zip(_STOPS, _STOPS[1:]):
        if h0 <= heat <= h1:
            if h1 == h0:
                t = 0.0
            else:
                t = (heat - h0) / (h1 - h0)
            return (_lerp(c0[0], c1[0], t),
                    _lerp(c0[1], c1[1], t),
                    _lerp(c0[2], c1[2], t))
    return _STOPS[-1][1]


def jittered_rgb(rgb, x, y):
    """Deterministic per-cell jitter (in [-4, +3]) that breaks color banding:
    adjacent cells with identical heat are never pixel-identical. Pure."""
    out = []
    for c in range(3):
        j = ((x * (3 + c) + y * (5 + 2 * c)) % 7) - 3
        out.append(min(255, max(0, rgb[c] + j)))
    return tuple(out)


# ---------------------------------------------------------------------------
# Simulation (pure, deterministic)
# ---------------------------------------------------------------------------

BASE_ROWS = 2          # bottom rows: the blue combustion zone
_COOL = 0.94           # upward propagation + cooling per tick
_DECAY = 0.006         # absolute cooling per tick
_LIFT = 0.7           # vertical carry: how much heat from directly below
_SPREAD = 0.15         # lateral spread: heat from below-left / below-right
_SMOKE_MAX = 12
_SMOKE_LIFE_DECAY = 0.06


class SmokeParticle:
    """One sparse smoke particle: (x, y) grid cell, life in (0, 1]."""
    __slots__ = ("x", "y", "life")

    def __init__(self, x, y, life=1.0):
        self.x = x
        self.y = y
        self.life = life

    def __repr__(self):
        return f"SmokeParticle(x={self.x}, y={self.y}, life={self.life:.3f})"


class FireSim:
    """Deterministic 2D heat-field fire.

    heat[y][x] is a float in [0, 1]; y = 0 is the TOP row, y = h-1 the bottom
    (base) row.  base[y][x] marks the blue combustion zone (bottom rows).
    All randomness comes from a single seeded PRNG, so two sims with the same
    seed produce identical frame sequences.
    """

    def __init__(self, width, height, seed=0, inject=True):
        self.w = width
        self.h = height
        self.rng = random.Random(seed)
        self.heat = [[0.0] * width for _ in range(height)]
        self.base = [[y >= height - BASE_ROWS for _ in range(width)]
                     for y in range(height)]
        self.inject = inject
        self.smoke = []
        self.tick_count = 0

    # -- internals ----------------------------------------------------------

    def _flame_top(self, threshold=0.40):
        for y in range(self.h):
            if max(self.heat[y]) > threshold:
                return y
        return self.h // 2

    def _update_smoke(self):
        # Existing particles rise, drift sideways and fade out.
        kept = []
        for p in self.smoke:
            p.y -= 1
            drift = self.rng.randint(-1, 1)
            p.x = min(self.w - 1, max(0, p.x + drift))
            p.life -= _SMOKE_LIFE_DECAY
            if p.y >= 0 and p.life > 0.0:
                kept.append(p)
        self.smoke = kept
        # Spawn a sparse particle just above the current flame top.
        if len(self.smoke) < _SMOKE_MAX and self.rng.random() < 0.5:
            ytop = self._flame_top()
            y = min(self.h - 1, max(0, ytop - self.rng.randint(1, 3)))
            spread = max(1, self.w // 5)
            x = min(self.w - 1, max(0, self.w // 2 + self.rng.randint(-spread, spread)))
            self.smoke.append(SmokeParticle(x, y, 1.0))

    # -- public API -----------------------------------------------------------

    def tick(self):
        """Advance the simulation by one frame (deterministic)."""
        w, h = self.w, self.h
        old = self.heat
        # Global per-frame flicker: the whole flame breathes.
        flick = self.rng.uniform(0.92, 1.08)
        new = [[0.0] * w for _ in range(h)]
        # Heat rises: every cell above the base row is fed by the row below.
        for y in range(h - 1):
            below = old[y + 1]
            for x in range(w):
                xm = below[x - 1] if x > 0 else below[x]
                xp = below[x + 1] if x < w - 1 else below[x]
                v = _LIFT * below[x] + _SPREAD * (xm + xp)
                v = v * _COOL * flick - _DECAY
                # Turbulence: per-cell multiplicative perturbation (sway,
                # licking, tongues) -- only cells that carry heat are perturbed.
                if v > 0.0:
                    v *= self.rng.uniform(0.85, 1.15)
                new[y][x] = min(1.0, max(0.0, v))
        # Base row: fresh combustion (per-cell noise -> multiple tongues).
        for x in range(w):
            if self.inject:
                v = flick * self.rng.uniform(0.6, 1.0)
            else:
                v = old[h - 1][x] * _COOL - _DECAY
            new[h - 1][x] = min(1.0, max(0.0, v))
        self.heat = new
        self.tick_count += 1
        self._update_smoke()


# ---------------------------------------------------------------------------
# Renderer (pure)
# ---------------------------------------------------------------------------

_HALF = "\u2580"  # ▀


def render(sim):
    """Grid + smoke particles -> one ANSI frame string (pure)."""
    smoke_cells = {}
    for p in sim.smoke:
        # Faint gray, fading with particle life (~60, 60, 65 at full life).
        g = max(1, int(65 * p.life))
        smoke_cells[(p.x, p.y)] = (g, g, g + 5)
    lines = []
    for y in range(sim.h):
        row = []
        for x in range(sim.w):
            rgb = smoke_cells.get((x, y))
            if rgb is None:
                rgb = palette(sim.heat[y][x], sim.base[y][x])
            if rgb is None:
                row.append(" ")
            else:
                r, g, b = jittered_rgb(rgb, x, y)
                row.append(f"\x1b[38;2;{r};{g};{b}m\x1b[0m{_HALF}")
        lines.append("".join(row))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Loop (IO only)
# ---------------------------------------------------------------------------

def _run_loop(sim, args):
    import shutil
    import signal
    import time

    try:
        tw, th = shutil.get_terminal_size()
    except OSError:
        tw, th = 80, 24

    stopped = {"flag": False}

    def _on_sigint(_sig, _frame):
        stopped["flag"] = True

    old_handler = signal.signal(signal.SIGINT, _on_sigint)
    w, h = sim.w, sim.h
    pad_l = max(0, (tw - w) // 2)
    pad_t = max(0, (th - h) // 2)
    interval = 1.0 / max(1, args.fps)
    try:
        sys.stdout.write("\x1b[?25l")  # hide cursor
        sys.stdout.flush()
        while not stopped["flag"]:
            t0 = time.monotonic()
            sim.tick()
            frame_lines = render(sim).split("\n")
            grid = []
            for y in range(th):
                if pad_t <= y < pad_t + h:
                    line = " " * pad_l + frame_lines[y - pad_t]
                else:
                    line = " " * tw
                if len(line) < tw:
                    line += " " * (tw - len(line))
                grid.append(line[:tw])
            sys.stdout.write("\x1b[H" + "\n".join(grid))
            sys.stdout.flush()
            time.sleep(max(0.0, interval - (time.monotonic() - t0)))
    finally:
        sys.stdout.write("\x1b[?25h\x1b[0m")  # restore cursor, reset ANSI
        sys.stdout.flush()
        signal.signal(signal.SIGINT, old_handler)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="Deterministic multicolor terminal fire")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--height", type=int, default=20)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--frames", type=int, default=0,
                    help="render N frames then exit 0")
    ap.add_argument("--frame", type=int, default=-1,
                    help="render exactly frame N then exit 0")
    args = ap.parse_args(argv)

    sim = FireSim(args.width, args.height, seed=args.seed)

    if args.frame >= 0:
        for _ in range(args.frame):
            sim.tick()
        print(render(sim))
        return 0

    # Headless-safe: no TTY, or an explicit frame count -> render and exit.
    if not sys.stdout.isatty() or args.frames > 0:
        n = args.frames if args.frames > 0 else 1
        for i in range(n):
            if i > 0:
                sim.tick()
            print(render(sim))
        sys.stdout.flush()
        return 0

    return _run_loop(sim, args)


if __name__ == "__main__":
    sys.exit(main())
