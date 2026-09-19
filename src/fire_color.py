#!/usr/bin/env python3
"""Maximally realistic multicolored terminal fire (24-bit truecolor ANSI).

Four separated concerns:
  1. Fire         -- pure simulation: 2D heat field + base-zone flags +
                     deterministic smoke particles; seeded PRNG.
  2. palette      -- pure mapping (heat, is_base, jitter) -> (r, g, b) | None.
  3. render_frame -- pure grid + particles -> one ANSI frame string
                     (half-block ``U+2580`` for vertical resolution).
  4. main()       -- IO loop only; runs exclusively under the __main__ guard.

Color model (a real flame is multicolored):
  - blue combustion base (fresh fuel meets air at the bottom rows),
  - white-hot core, yellow/orange body, red-orange/red tips,
  - faint gray smoke rising above the flame.

Stdlib only. Deterministic: same seed -> identical frames.
"""

from __future__ import annotations

import random
import shutil

ESC = "\x1b"
FPS = 30

# Hot -> cool gradient stops: (heat, (r, g, b)).
_STOPS = [
    (1.00, (255, 255, 240)),  # white-hot core
    (0.80, (255, 220, 80)),   # yellow
    (0.60, (255, 140, 0)),    # orange
    (0.45, (220, 60, 20)),    # red-orange
    (0.30, (160, 30, 10)),    # red tips
    (0.15, (90, 15, 8)),      # dark red
    (0.00, (12, 4, 2)),       # near-black ember
]

_BASE_HOT = (120, 180, 255)   # light blue, hottest base
_BASE_COLD = (80, 120, 255)   # deep blue, coolest base

_SMOKE = (60, 60, 65)         # faint gray


def _lerp(c1, c2, t):
    return tuple(int(round(a + (b - a) * t)) for a, b in zip(c1, c2))


def palette(heat, is_base=False, jitter=(0, 0, 0)):
    """Map heat in [0, 1] (+ combustion-base-zone flag) to (r, g, b) or None.

    Zero heat returns None (empty cell). ``jitter`` is a per-cell 3-tuple of
    small integer offsets used to break color banding; output is clamped
    to 0..255.
    """
    if heat <= 0.0:
        return None
    if is_base:
        c = _lerp(_BASE_COLD, _BASE_HOT, heat)
    elif heat >= _STOPS[0][0]:
        c = _STOPS[0][1]
    else:
        c = _STOPS[-1][1]
        for (h1, c1), (h2, c2) in zip(_STOPS, _STOPS[1:]):
            if heat >= h2:
                c = _lerp(c2, c1, (heat - h2) / (h1 - h2) if h1 > h2 else 0.0)
                break
    return tuple(max(0, min(255, ch + j)) for ch, j in zip(c, jitter))


class Fire:
    """Pure, deterministic simulation of a burning flame.

    ``heat[y][x]``: normalized heat in [0, 1]; y = 0 is the TOP of the
    field, y = height-1 the fuel line. ``base[y][x]``: combustion-zone
    flag (the bottom rows). ``smoke``: list of particles
    ``{"x", "y", "life"}`` rising above the flame and fading out.
    """

    def __init__(self, width=80, height=32, seed=42):
        if height % 2:
            height -= 1  # half-block rows must pair cleanly
        self.width = width
        self.height = height
        self.seed = seed
        self.rng = random.Random(seed)
        self.heat = [[0.0] * width for _ in range(height)]
        self.base = [[False] * width for _ in range(height)]
        self.smoke = []
        self._turb = [[0.5] * width for _ in range(height)]  # value-noise walk
        self._gate = [0.85] * width                          # per-column fuel gate

    def _flame_top(self, threshold=0.6):
        """Index of the highest (smallest y) row carrying significant heat."""
        for y in range(self.height):
            if any(v > threshold for v in self.heat[y]):
                return y
        return self.height - 1

    def tick(self):
        """Advance the simulation one step (deterministic for a given seed)."""
        w, h, rng = self.width, self.height, self.rng
        old = self.heat

        # Global flicker: whole-frame intensity noise.
        flicker = 0.90 + 0.16 * rng.random()

        # Advection upward: each row samples the row below (with a small
        # turbulence-driven lateral shift so tongues sway and lick),
        # smoothed over 3 neighbors, cooled.
        new = [[0.0] * w for _ in range(h)]
        for y in range(h - 1):
            src = old[y + 1]
            dst = new[y]
            for x in range(w):
                t = self._turb[y][x]
                if t > 0.68:
                    xs = x + 1
                elif t < 0.32:
                    xs = x - 1
                else:
                    xs = x
                if 0 <= xs < w:
                    l = src[xs - 1] if xs > 0 else 0.0
                    r = src[xs + 1] if xs < w - 1 else 0.0
                    v = (src[xs] + l + r) / 3.0 * 0.92
                else:
                    v = 0.0
                v += (t - 0.5) * 0.05  # per-cell turbulence perturbation
                dst[x] = max(0.0, min(1.0, v))

        # Fuel injection at the base (wide, per-column gated -> multiple
        # tongues tapering upward as the field cools).
        for x in range(w):
            inj = min(1.0, flicker * self._gate[x])
            new[h - 1][x] = max(new[h - 1][x], inj)
            new[h - 2][x] = max(new[h - 2][x], inj * 0.88)
        self.heat = new

        # Combustion-zone flags: the bottom rows where fuel meets air.
        for y in (h - 1, h - 2):
            brow, hrow = self.base[y], self.heat[y]
            for x in range(w):
                brow[x] = hrow[x] > 0.25

        # Turbulence: bounded per-cell random walk (value-noise).
        for y in range(h):
            row = self._turb[y]
            for x in range(w):
                v = row[x] + rng.uniform(-0.06, 0.06)
                if v < 0.0:
                    v = 0.0
                elif v > 1.0:
                    v = 1.0
                row[x] = v

        # Fuel gate: bounded walk; floor keeps the base wide.
        for x in range(w):
            v = self._gate[x] + rng.uniform(-0.08, 0.08)
            if v < 0.55:
                v = 0.55
            elif v > 1.0:
                v = 1.0
            self._gate[x] = v

        self._update_smoke()

    def _update_smoke(self):
        """Sparse deterministic smoke: spawn above the flame top, rise, fade."""
        rng = self.rng
        top = self._flame_top(0.55)
        if top > 0 and rng.random() < 0.6:
            xs = [x for x in range(self.width) if self.heat[top][x] > 0.35]
            if xs:
                self.smoke.append({"x": rng.choice(xs), "y": top - 1, "life": 7.0})
        for p in self.smoke:
            p["y"] -= 1
            p["x"] += rng.choice((-1, 0, 1))
            p["life"] -= 0.8
        self.smoke = [
            p for p in self.smoke
            if p["life"] > 0.0 and 0 <= p["x"] < self.width and p["y"] >= 0
        ]


def render_frame(sim, smoke_color=_SMOKE):
    """Grid + smoke particles -> one ANSI frame string.

    Half-block (``U+2580``) characters give 2x vertical resolution: character
    row i covers heat cells 2i (top) and 2i+1 (bottom). Frame is
    ``sim.height // 2`` lines of ``sim.width`` display cells each. Zero heat
    renders as a plain space, no escape.
    """
    w, h, seed = sim.width, sim.height, sim.seed
    lines = []
    for iy in range(h // 2):
        top, bot = sim.heat[2 * iy], sim.heat[2 * iy + 1]
        btop, bbot = sim.base[2 * iy], sim.base[2 * iy + 1]
        row = []
        y = 2 * iy
        for x in range(w):
            th, bh = top[x], bot[x]
            if th <= 0.0 and bh <= 0.0:
                row.append(" ")
                continue
            # Seeded per-cell jitter (one value per channel) breaks banding.
            jit = tuple((seed * 131 + x * 37 + y * 17 + ch * 7) % 9 - 4 for ch in range(3))
            if bh > 0.0:
                c = palette(bh, bbot[x], jit)
            else:
                c = palette(th, btop[x], jit)
            glyph = "\u2588" if th > 0.0 else "\u2580"
            row.append(
                "%s[38;2;%d;%d;%dm%s%s[0m" % (ESC, c[0], c[1], c[2], glyph, ESC)
            )
        lines.append(row)
    for p in sim.smoke:
        py, px = p["y"], p["x"]
        if 0 <= py < h and 0 <= px < w:
            r, g, b = smoke_color
            lines[py // 2][px] = "%s[38;2;%d;%d;%dm %s[0m" % (ESC, r, g, b, ESC)
    return "\n".join("".join(row) for row in lines)


def main():
    """IO-only animation loop: hide cursor, ~30 FPS, clear+center each frame.

    SIGINT: stop the loop, reset ANSI, restore the cursor, exit 0.
    """
    import signal
    import sys
    import time

    try:
        ts = shutil.get_terminal_size(fallback=(80, 24))
    except OSError:
        ts = (80, 24)
    cols = max(24, ts.columns)
    rows = max(10, ts.lines)
    width = max(24, (cols - 2) // 2 * 2)
    height = max(12, (rows - 2) // 2 * 2)
    sim = Fire(width=width, height=height, seed=20260918)

    if not sys.stdout.isatty():
        # Headless (piped/redirected): emit a single warmed frame and exit 0;
        # the animation loop only starts on a real terminal.
        for _ in range(40):
            sim.tick()
        try:
            sys.stdout.write(render_frame(sim) + "\n")
            sys.stdout.flush()
        except (BrokenPipeError, OSError):
            pass
        return 0

    state = {"stop": False}

    def _on_sigint(signum, frame):
        state["stop"] = True

    signal.signal(signal.SIGINT, _on_sigint)

    out = sys.stdout
    out.write("%s[?25l" % ESC)  # hide cursor
    out.flush()
    try:
        while not state["stop"]:
            frame = render_frame(sim)
            sim.tick()
            lines = frame.split("\n")
            ox = max(0, (cols - width) // 2)
            oy = max(0, (rows - len(lines)) // 2)
            out.write("%s[2J%s[H" % (ESC, ESC))  # clear screen, home
            if oy:
                out.write("\n" * oy)
            pad = " " * ox
            out.write("\n".join(pad + ln for ln in lines))
            out.flush()
            deadline = time.monotonic() + 1.0 / FPS
            while not state["stop"] and time.monotonic() < deadline:
                time.sleep(0.002)
    finally:
        out.write("%s[0m%s[?25h\n" % (ESC, ESC))  # reset ANSI, restore cursor
        out.flush()
    return 0


if __name__ == "__main__":
    main()
