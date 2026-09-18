"""Multicolored terminal fire — heat-field simulation, truecolor palette,
half-block ANSI renderer.

Run:  python3 src/fire_color.py        (Ctrl-C stops cleanly, exit 0)

Architecture (four separated concerns):
- Simulation: new_state() / step() — pure, seeded PRNG, deterministic.
- Palette:    palette(heat, is_base) -> (r, g, b) | None.
- Renderer:   render(state) -> one ANSI frame string (half-block "▀").
- Loop:       main() under the __main__ guard (IO only).
"""
import math
import os
import random
import shutil
import sys
import time

# Palette stops, hot -> cool. Below the last stop (heat < 0.10) the cell
# has cooled out and renders as empty space.
_STOPS = (
    (1.00, (255, 255, 240)),  # white-hot core
    (0.72, (255, 220, 80)),   # yellow
    (0.52, (255, 140, 0)),    # orange
    (0.38, (220, 60, 20)),    # red-orange
    (0.24, (160, 30, 10)),    # red
    (0.10, (90, 15, 8)),      # dark red
)
_BASE_HOT = (120, 180, 255)
_BASE_COOL = (80, 120, 255)
_SMOKE = (60, 60, 65)


def _clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else hi if v > hi else v


# --------------------------------------------------------------------------
# Simulation (pure)
# --------------------------------------------------------------------------

def new_state(seed=42, width=40, height=24):
    """Create a deterministic simulation state (pre-warmed to steady burn).

    Grid rows: 0 is the TOP of the flame, height-1 is the bottom (base).
    """
    if height % 2:
        height += 1
    rng = random.Random(seed)
    # Static per-cell color jitter (seeded) to break color banding.
    jit = []
    for _ in range(height):
        row = []
        for _ in range(width):
            row.append((
                int((rng.random() - 0.5) * 10),
                int((rng.random() - 0.5) * 10),
                int((rng.random() - 0.5) * 10),
            ))
        jit.append(row)
    state = {
        "seed": seed,
        "width": width,
        "height": height,
        "frame": 0,
        "rng": rng,
        "heat": [[0.0] * width for _ in range(height)],
        "base": [[False] * width for _ in range(height)],
        "turb": [0.0] * width,
        "particles": [],
        "jit": jit,
    }
    # Pre-warm so the first rendered frame is already fully burning.
    for _ in range(30):
        state = step(state)
    return state


def step(state):
    """Advance one tick; returns a NEW state (pure)."""
    w, h = state["width"], state["height"]
    rng = state["rng"]
    frame = state["frame"] + 1

    # Random-walk turbulence field drives multiple licking tongues.
    turb = []
    for t in state["turb"]:
        t += (rng.random() - 0.5) * 0.25
        turb.append(_clamp(t, -1.0, 1.0))

    # Global flicker: intensity noise per frame.
    flicker = 0.85 + 0.30 * rng.random()

    old = state["heat"]
    heat = [row[:] for row in old]
    # Heat diffuses upward: each row samples the row below, swaying with
    # height and time (turbulence), plus per-cell perturbation and cooling.
    for y in range(h - 1):
        bias = math.sin(frame * 0.21 + y * 0.35) * 1.5 + (rng.random() - 0.5)
        shift = int(round(bias))
        row_below = old[y + 1]
        row_new = heat[y]
        for x in range(w):
            src = x + shift
            if src < 0:
                src = 0
            elif src >= w:
                src = w - 1
            up = row_below[src]
            # Slight lateral spread from the neighbors below.
            if src > 0 and row_below[src - 1] * 0.85 > up:
                up = row_below[src - 1] * 0.85
            if src < w - 1 and row_below[src + 1] * 0.85 > up:
                up = row_below[src + 1] * 0.85
            if up <= 0.03:
                row_new[x] = 0.0
                continue
            val = up * (0.965 + 0.02 * rng.random()) - 0.012
            val += (rng.random() - 0.5) * 0.10
            row_new[x] = _clamp(val)

    # Fresh fuel at the base: wide profile tapering to the edges, modulated
    # by the turbulence walk (multiple tongues) and the frame flicker.
    cx = (w - 1) / 2.0
    half = w * 0.35
    bottom = heat[h - 1]
    for x in range(w):
        d = abs(x - cx) / half
        prof = max(0.0, 1.0 - d * d)
        bottom[x] = _clamp(prof * flicker + turb[x] * 0.15)

    # Combustion zone: the bottom rows of the flame body (fresh fuel meets
    # air) — this is what is blue in a real flame.
    base = [[False] * w for _ in range(h)]
    for y in (h - 2, h - 1):
        rowb = base[y]
        rowh = heat[y]
        for x in range(w):
            if rowh[x] > 0.35:
                rowb[x] = True

    # Smoke particles: sparse, deterministic; rise above the flame top
    # and fade out.
    particles = []
    for p in state["particles"]:
        life = p["life"] - 0.045
        if life <= 0:
            continue
        py = p["y"] - (0.25 + 0.10 * rng.random())
        px = p["x"] + (rng.random() - 0.5) * 0.3
        if py > -1.5 and -1.0 <= px < w + 1:
            particles.append({"x": px, "y": py, "life": life})
    top = None
    for y in range(h):
        if any(v > 0.25 for v in heat[y]):
            top = y
            break
    if top is not None and len(particles) < 48:
        particles.append({
            "x": cx + (rng.random() - 0.5) * w * 0.4,
            "y": top - 0.5,
            "life": 1.0,
        })

    return {
        "seed": state["seed"],
        "width": w,
        "height": h,
        "frame": frame,
        "rng": rng,
        "heat": heat,
        "base": base,
        "turb": turb,
        "particles": particles,
        "jit": state["jit"],
    }


# --------------------------------------------------------------------------
# Palette (pure)
# --------------------------------------------------------------------------

def palette(heat, is_base=False):
    """(heat, is_base) -> (r, g, b) | None. Zero heat -> None (empty cell)."""
    if heat is None or heat <= 0.0:
        return None
    heat = _clamp(heat)
    if is_base:
        # Blue combustion base: gradient by heat.
        t = heat
        r = int(_BASE_HOT[0] + (_BASE_COOL[0] - _BASE_HOT[0]) * t)
        g = int(_BASE_HOT[1] + (_BASE_COOL[1] - _BASE_HOT[1]) * t)
        b = int(_BASE_HOT[2] + (_BASE_COOL[2] - _BASE_HOT[2]) * t)
        return (r, g, b)
    if heat >= _STOPS[0][0]:
        return _STOPS[0][1]
    for (h0, c0), (h1, c1) in zip(_STOPS, _STOPS[1:]):
        if heat >= h1:
            f = (heat - h1) / (h0 - h1)
            return (
                int(c0[0] + (c1[0] - c0[0]) * f),
                int(c0[1] + (c1[1] - c0[1]) * f),
                int(c0[2] + (c1[2] - c0[2]) * f),
            )
    return None


# --------------------------------------------------------------------------
# Renderer (pure)
# --------------------------------------------------------------------------

def render(state):
    """grid + particles -> one ANSI frame string.

    Uses half-block "▀" characters for vertical resolution: the grid has
    2 rows per character row, so the frame is width x (height // 2).
    """
    w, h = state["width"], state["height"]
    rows = h // 2
    heat = state["heat"]
    base = state["base"]
    jit = state.get("jit")

    # Smoke cell map: (row, col) -> fade life (max life wins).
    smoke = {}
    for p in state.get("particles", ()):
        life = p["life"]
        ry = int(round(p["y"]))
        cx = int(round(p["x"]))
        if 0 <= ry < rows and 0 <= cx < w and life > 0:
            if smoke.get((ry, cx), 0) < life:
                smoke[(ry, cx)] = life

    lines = []
    for ry in range(rows):
        chars = []
        prev = None
        for x in range(w):
            y0, y1 = ry * 2, ry * 2 + 1
            v0, v1 = heat[y0][x], heat[y1][x]
            if v1 >= v0:
                yy, v = y1, v1
            else:
                yy, v = y0, v0
            c = palette(v, base[yy][x])
            j = jit[yy][x] if jit is not None else (0, 0, 0)
            if c is None:
                life = smoke.get((ry, x))
                if life is not None:
                    f = _SMOKE
                    c = (
                        max(0, min(255, int(f[0] * life))),
                        max(0, min(255, int(f[1] * life))),
                        max(0, min(255, int(f[2] * life))),
                    )
            if c is None:
                if prev is not None:
                    chars.append("\x1b[0m")
                    prev = None
                chars.append(" ")
            else:
                r = max(0, min(255, c[0] + j[0]))
                g = max(0, min(255, c[1] + j[1]))
                b = max(0, min(255, c[2] + j[2]))
                key = (r, g, b)
                if key != prev:
                    chars.append("\x1b[38;2;%d;%d;%dm" % key)
                    prev = key
                chars.append("▀")
        if prev is not None:
            chars.append("\x1b[0m")
        lines.append("".join(chars))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Loop (IO only)
# --------------------------------------------------------------------------

def main():
    try:
        cols, lines = shutil.get_terminal_size()
    except Exception:
        cols, lines = 80, 24
    rows = max(4, min(12, lines // 2 - 2))
    w = 2 * max(8, min(28, cols // 4))
    state = new_state(seed=1337, width=w, height=rows * 2)
    interactive = sys.stdout.isatty()
    out = sys.stdout
    n = 0
    try:
        out.write("\x1b[?25l")
        out.flush()
        while interactive or n < 90:
            state = step(state)
            out.write("\x1b[2J\x1b[H")
            top = max(0, (lines - rows) // 2)
            left = max(0, (cols - w) // 2)
            for _ in range(top):
                out.write(" " * min(cols, 80) + "\r\n")
            for line in render(state).split("\n"):
                out.write(" " * left + line[:cols] + "\r\n")
            out.flush()
            if interactive:
                time.sleep(1.0 / 30.0)
            n += 1
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        # Drop any buffered frame data (a full/closed pipe must not block
        # the shutdown), then emit the restore unbuffered on fd 1 so the
        # interpreter-shutdown flush cannot re-raise against it.
        try:
            out.detach()
        except Exception:
            pass
        try:
            os.write(1, b"\x1b[?25h\x1b[0m")
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
