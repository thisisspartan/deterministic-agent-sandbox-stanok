"""Console fire — deterministic multicolor terminal fire animation (CC-108).

Four separated concerns:

1. ``FireSim``  — pure, deterministic 2D heat-field simulation. Floats in
   ``[0, 1]``; per tick: inject heat at the base row(s), diffuse upward,
   cool (decay), perturb with turbulence. Seeded PRNG (``random.Random``).
   Keeps a per-cell base-zone flag (blue combustion zone, bottom rows) and
   a sparse deterministic list of smoke particles (x, y, life) that rise
   above the flame top and fade out. No IO.
2. ``palette``  — pure ``(heat, is_base[, jitter]) -> (r, g, b) | None``.
   Multi-stop gradient hot->cool; base-zone cells use a blue gradient;
   zero heat -> ``None`` (empty cell). 24-bit truecolor ANSI output.
3. ``render``   — pure ``FireSim -> str``. Grid + smoke particles -> one
   ANSI frame of half-block (``▀``) characters. Frame dimensions match the
   grid; zero heat -> plain space.
4. Main loop    — IO only, runs ONLY under ``if __name__ == "__main__":``.
   ~30 FPS, clear screen per frame, flame centered in the terminal
   (``shutil.get_terminal_size()``, fallback 80x24). On SIGINT: stop,
   restore the cursor (``\x1b[?25h``), reset ANSI (``\x1b[0m``), exit 0.

Headless-safe main guard:
* real TTY on stdout        -> animation loop;
* no TTY (e.g. stdin </dev/null) -> render ONE frame to stdout, exit 0;
* ``--seed N --width W --height H --fps N --frames N --frame N`` make the
  animation deterministically testable headlessly. Frame N (0-based, the
  frame a viewer would see Nth) is the simulation state after N+1 ticks.

Stdlib only. Importing this module has no IO side effects.
"""

from __future__ import annotations

import argparse
import random
import shutil
import sys
import time
from dataclasses import dataclass

# --- simulation tuning ---------------------------------------------------------
RISE = 0.62          # fraction of below-cell heat carried upward per tick
SPREAD = 0.12        # lateral spread coefficient
COOL = 0.985         # global cooling (decay) per tick
TURBULENCE = 0.05    # max random heat perturbation per cell/tick
BASE_ROWS = 2        # bottom rows forming the blue combustion zone
SMOKE_MAX = 12       # sparse smoke-particle cap
SMOKE_SPAWN = 0.35   # per-tick probability of spawning a smoke particle
SMOKE_RISE = 1       # rows a smoke particle rises per tick
SMOKE_FADE = 0.15    # life lost per tick
SMOKE_THR = 0.35     # heat threshold defining "top of the flame"

DEFAULT_WIDTH = 40
DEFAULT_HEIGHT = 16
DEFAULT_FPS = 30
DEFAULT_SEED = 0

# --- palette constants ----------------------------------------------------------
# hot -> cool multi-stop gradient (descending heat thresholds)
_STOPS = (
    (1.00, (255, 255, 240)),  # white-hot
    (0.85, (255, 220, 80)),   # yellow
    (0.65, (255, 140, 0)),    # orange
    (0.45, (220, 60, 20)),    # red-orange
    (0.28, (160, 30, 10)),    # red
    (0.12, (90, 15, 8)),      # dark red
    (0.00, (0, 0, 0)),        # fade to black at near-zero heat
)
_BASE_LO = (25, 45, 110)     # blue combustion zone, low heat
_BASE_HI = (120, 180, 255)   # blue combustion zone, high heat
_SMOKE = (60, 60, 65)        # faint gray

HALF_BLOCK = "▀"
ANSI_TRUE = "\x1b[38;2;{};{};{}m"
RESET = "\x1b[0m"


# ================================================================================
# 2. Palette (pure)
# ================================================================================

def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _hot_color(h: float) -> tuple:
    """Piecewise-linear multi-stop gradient from white-hot to dark red."""
    for i in range(len(_STOPS) - 1):
        t_hi, c_hi = _STOPS[i]
        t_lo, c_lo = _STOPS[i + 1]
        if t_lo <= h <= t_hi:
            if t_hi == t_lo:
                return c_hi
            t = (h - t_lo) / (t_hi - t_lo)
            return tuple(int(round(_lerp(c_lo[k], c_hi[k], t))) for k in range(3))
    return _STOPS[-1][1]


def palette(heat: float, is_base: bool, jitter: float = 0.0) -> tuple | None:
    """Pure: ``(heat, is_base[, jitter]) -> (r, g, b) | None``.

    ``heat`` in ``[0, 1]``; ``jitter`` in ``[-1, 1]`` (small, breaks color
    banding). Zero heat -> ``None`` (empty cell). Base-zone cells render a
    blue gradient by heat; everything else uses the hot->cool gradient.
    Every returned component is an int in ``0..255``.
    """
    if heat <= 0.0:
        return None
    h = min(1.0, max(0.0, heat))
    if is_base:
        rgb = tuple(int(round(_lerp(_BASE_LO[k], _BASE_HI[k], h))) for k in range(3))
    else:
        rgb = _hot_color(h)
    return tuple(int(min(255, max(0, round(c + jitter * 8.0)))) for c in rgb)


def _fade(rgb: tuple, life: float) -> tuple:
    """Smoke color scaled by remaining particle life."""
    t = min(1.0, max(0.0, life))
    return tuple(int(round(c * t)) for c in rgb)


# ================================================================================
# 1. Simulation (pure, deterministic)
# ================================================================================

@dataclass
class SmokeParticle:
    """One sparse smoke particle: integer grid position + remaining life."""
    x: int
    y: int
    life: float


class FireSim:
    """Deterministic 2D heat-field fire. Pure: no IO, no globals mutated.

    ``heat`` is a list of rows of floats in ``[0, 1]``; row 0 is the TOP of
    the flame (row ``h-1`` is the base). ``base`` is a per-cell bool marking
    the bottom rows of the flame body (blue combustion zone). ``smoke`` is
    a sparse list of :class:`SmokeParticle`.
    """

    def __init__(self, width: int, height: int, seed: int = 0):
        if width < 2 or height < 2:
            raise ValueError("width and height must be >= 2")
        self.w = int(width)
        self.h = int(height)
        self.seed = int(seed)
        self.rng = random.Random(self.seed)
        self.heat = [[0.0] * self.w for _ in range(self.h)]
        self.base = [[False] * self.w for _ in range(self.h)]
        self.smoke: list[SmokeParticle] = []
        self.frame_no = 0
        self.base_span = (self.w // 4, self.w - self.w // 4)

    @staticmethod
    def _clamp01(v: float) -> float:
        return 0.0 if v < 0.0 else 1.0 if v > 1.0 else v

    def tick(self) -> list:
        """Advance the simulation by one frame; return the new heat field."""
        old = self.heat
        new = [[0.0] * self.w for _ in range(self.h)]
        w, h = self.w, self.h
        # Diffuse upward + lateral spread + turbulence + cooling.
        # Turbulence only perturbs cells that already carry heat, so cold
        # cells stay exactly 0.0 (and a cell's heat never exceeds [0, 1]).
        for y in range(h - 1, -1, -1):
            row_old = old[y]
            row_new = new[y]
            row_below = old[y + 1] if y + 1 < h else None
            for x in range(w):
                below = row_below[x] if row_below is not None else 0.0
                left = row_old[x - 1] if x > 0 else 0.0
                right = row_old[x + 1] if x < w - 1 else 0.0
                v = below * RISE + (left + right) * SPREAD
                if v > 0.0:
                    v += self.rng.uniform(-TURBULENCE, TURBULENCE)
                row_new[x] = self._clamp01(v * COOL)
        # Inject heat at the base row(s).
        base_lo, base_hi = self.base_span
        base_row = new[h - 1]
        for x in range(base_lo, base_hi):
            v = self.rng.uniform(0.8, 1.0)
            if v > base_row[x]:
                base_row[x] = v
        self.heat = new
        self._update_base()
        self._update_smoke()
        self.frame_no += 1
        return self.heat

    def _update_base(self) -> None:
        """Flag the bottom rows of the flame body (blue combustion zone)."""
        base = [[False] * self.w for _ in range(self.h)]
        base_lo, base_hi = self.base_span
        for y in range(self.h - BASE_ROWS, self.h):
            row_heat = self.heat[y]
            for x in range(base_lo, base_hi):
                if row_heat[x] > 0.0:
                    base[y][x] = True
        self.base = base

    def _flame_top(self) -> int | None:
        """Smallest row index (from the top) whose heat exceeds the
        smoke threshold, or ``None`` when no flame has risen yet."""
        for y in range(self.h):
            row = self.heat[y]
            for x in range(self.w):
                if row[x] > SMOKE_THR:
                    return y
        return None

    def _update_smoke(self) -> None:
        """Rise existing particles, fade them, drop dead ones; maybe spawn
        a new particle just above the flame top (sparse, deterministic)."""
        smoke = []
        for p in self.smoke:
            p.y -= SMOKE_RISE
            p.life -= SMOKE_FADE
            if p.life > 0.0 and p.y >= 0:
                smoke.append(p)
        if len(smoke) < SMOKE_MAX and self.rng.random() < SMOKE_SPAWN:
            top = self._flame_top()
            y = (top - 1) if (top is not None and top > 0) else self.h - 2
            if y >= 0:
                x = self.rng.randrange(self.base_span[0], self.base_span[1])
                smoke.append(
                    SmokeParticle(x=x, y=y, life=self.rng.uniform(0.5, 1.0))
                )
        self.smoke = smoke


# ================================================================================
# 3. Renderer (pure)
# ================================================================================

def _cell_jitter(seed: int, x: int, y: int) -> float:
    """Small SEEDED per-cell jitter in ``[-1, 1]`` to break color banding.
    Pure function of (seed, x, y) — deterministic across runs."""
    return random.Random(seed * 1000003 + x * 131 + y * 31).uniform(-1.0, 1.0)


def render(sim: FireSim) -> str:
    """Pure: ``FireSim ->`` one ANSI frame string of ``▀`` half-blocks.

    Frame dimensions match the grid: ``len(frame.split("\\n")) == sim.h``
    and every line contains exactly ``sim.w`` visible characters.
    Zero heat -> plain space. Truecolor is emitted as
    ``\\x1b[38;2;R;G;B m``; each line is reset with ``\\x1b[0m``.
    """
    smoke_map: dict = {}
    for p in sim.smoke:
        key = (p.x, p.y)
        if p.life > smoke_map.get(key, 0.0):
            smoke_map[key] = p.life
    lines = []
    for y in range(sim.h):
        row_heat = sim.heat[y]
        row_base = sim.base[y]
        chars = []
        for x in range(sim.w):
            rgb = palette(row_heat[x], row_base[x], _cell_jitter(sim.seed, x, y))
            if rgb is None:
                life = smoke_map.get((x, y))
                if life is not None:
                    rgb = _fade(_SMOKE, life)
            if rgb is None:
                chars.append(" ")
            else:
                chars.append(ANSI_TRUE.format(*rgb) + HALF_BLOCK)
        lines.append("".join(chars) + RESET)
    return "\n".join(lines)


def frame_at(sim: FireSim, n: int) -> str:
    """Render frame N (0-based display index) by advancing N+1 ticks."""
    for _ in range(n + 1):
        sim.tick()
    return render(sim)


# ================================================================================
# 4. Loop (IO only) + headless-safe main guard
# ================================================================================

def _center(frame: str, sim_w: int, sim_h: int, term_w: int, term_h: int) -> str:
    """Pad a frame string so the flame is centered in the terminal."""
    lines = frame.split("\n")
    out_lines = [" " * term_w for _ in range(max(0, (term_h - len(lines)) // 2))]
    pad = max(0, (term_w - sim_w) // 2)
    out_lines.extend(" " * pad + line for line in lines)
    return "\n".join(out_lines)


def _run_loop(sim: FireSim, fps: int) -> int:
    """Interactive animation loop (IO only). Stops cleanly on SIGINT."""
    try:
        size = shutil.get_terminal_size()
        term_w, term_h = size.columns, size.lines
    except (OSError, ValueError):
        term_w, term_h = 80, 24
    out = sys.stdout
    out.write("\x1b[?25l")  # hide cursor
    out.flush()
    try:
        while True:
            sim.tick()
            frame = render(sim)
            out.write("\x1b[2J\x1b[H")  # clear screen, home
            out.write(_center(frame, sim.w, sim.h, term_w, term_h))
            out.write("\n")
            out.flush()
            time.sleep(1.0 / max(1, fps))
    except KeyboardInterrupt:
        out.write("\x1b[?25h")  # restore cursor
        out.write(RESET)        # reset ANSI
        out.flush()
        return 0
    return 0


def parse_args(argv: list | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="deterministic terminal fire")
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED,
                    help="PRNG seed (default %(default)s)")
    ap.add_argument("--width", type=int, default=DEFAULT_WIDTH,
                    help="flame grid width in cells (default %(default)s)")
    ap.add_argument("--height", type=int, default=DEFAULT_HEIGHT,
                    help="flame grid height in cells (default %(default)s)")
    ap.add_argument("--fps", type=int, default=DEFAULT_FPS,
                    help="frames per second in TTY mode (default %(default)s)")
    ap.add_argument("--frames", type=int, default=None,
                    help="render N frames (0-based, Nth = after N+1 ticks) "
                         "to stdout, then exit 0")
    ap.add_argument("--frame", type=int, default=None,
                    help="render exactly frame N to stdout, then exit 0")
    return ap.parse_args(argv)


def main(argv: list | None = None) -> int:
    args = parse_args(argv)
    sim = FireSim(args.width, args.height, args.seed)
    if args.frame is not None:
        sys.stdout.write(frame_at(sim, args.frame) + "\n")
        return 0
    if args.frames is not None:
        for n in range(args.frames):
            sys.stdout.write(frame_at(sim, n) + "\n")
        return 0
    if sys.stdout.isatty():
        return _run_loop(sim, args.fps)
    # Headless: exactly one frame, no loop.
    sim.tick()
    sys.stdout.write(render(sim) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
