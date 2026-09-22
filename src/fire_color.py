"""fire_color — realistic MULTICOLORED burning flame for the terminal.

A real flame is not monochrome: it has a BLUE combustion base (fresh fuel
meeting air), a white-hot core, a yellow/orange body, red tips and faint
gray smoke above.  Rendered with 24-bit truecolor ANSI, no terminal
extensions.

Architecture (four separated concerns, all pure except the loop):

1. Simulation  -- ``new_state`` / ``step``: a 2D heat-field grid advanced by
   a SEEDED PRNG (``random.Random(seed)``; same seed -> identical frames).
   Row 0 is the fuel base (bottom of the screen).  Each tick: fuel is
   injected along a wide, gap-pocked base line; heat is carried upward with
   per-cell turbulence (random shear, licks, gaps), then multiplied by a
   strong per-row quadratic cooling ``1 - (y/H)**2`` and a hard center
   taper ``half_width(y) = w0 * (1 - y/H)**0.8`` (heat outside the taper
   envelope is killed outright) so the flame is a CONE -- wide at the base,
   narrowing to a point, with large blank areas around it.  Heat is
   normalized to [0, 1].  The state also carries a per-cell **base-zone
   flag** (the bottom rows where fresh fuel meets air -> blue) and a sparse
   deterministic **smoke** particle list that rises above the flame top
   and fades out.
2. Palette     -- ``palette(heat, is_base, salt)``: multi-stop hot-to-cool
   gradient white-hot (255,255,240) -> yellow (255,220,80) -> orange
   (255,140,0) -> red-orange (220,60,20) -> red (160,30,10) -> dark red
   (90,15,8); heat below BLANK (0.10) returns None (empty cell, no ANSI
   escape).  Base-zone cells render a BLUE gradient (80,120,255 ->
   120,180,255).  A small seeded per-cell jitter (salt) breaks banding.
3. Renderer    -- ``render(state)``: grid + smoke particles -> one ANSI
   frame string.  Half-block ``▀`` cells for vertical resolution; frame
   dimensions always match the grid; blank cells are plain spaces.
4. Loop        -- ``main()`` (IO only, ``__main__`` guard): hidden cursor,
   ~30 FPS, screen cleared each frame, flame centered in the terminal
   (``shutil.get_terminal_size()``, fallback 80x24).  On Ctrl-C: loop stops,
   cursor restored (``\\x1b[?25h``), ANSI reset (``\\x1b[0m``), exit 0.
   If stdin/stdout are not ttys (CI, pipes) it prints a short deterministic
   frame dump and exits 0 instead of animating.

Run:  python3 src/fire_color.py        Stop:  Ctrl-C
"""

import math
import random
import shutil
import sys
import time

# ---------------------------------------------------------------- palette --

BLANK = 0.10  # heat below this renders as a blank cell (None)

# hot -> cool gradient stops (heat, r, g, b)
_STOPS = (
    (1.00, 255, 255, 240),  # white-hot core
    (0.80, 255, 235, 120),
    (0.60, 255, 220, 80),   # yellow
    (0.45, 255, 160, 30),
    (0.30, 255, 140, 0),    # orange
    (0.22, 220, 60, 20),    # red-orange
    (0.16, 160, 30, 10),    # red
    (BLANK, 90, 15, 8),     # dark red edge
)
_JITTER = 11.0  # +/- per-channel seeded jitter (breaks color banding)


def _clamp255(v):
    v = int(round(v))
    if v < 0:
        return 0
    if v > 255:
        return 255
    return v


def palette(heat, is_base, salt=0.0):
    """(heat, is_base, salt) -> (r, g, b) or None (blank cell).

    heat in [0, 1]; below BLANK there is no cell at all (no ANSI escape).
    ``salt`` in [0, 1) is the deterministic per-cell jitter source.
    """
    if heat < BLANK:
        return None
    h = heat if heat <= 1.0 else 1.0
    if is_base:
        # blue combustion zone: cool blue -> bright blue as heat rises
        f = (h - BLANK) / (1.0 - BLANK)
        r = 80.0 + 40.0 * f
        g = 120.0 + 60.0 * f
        b = 255.0
    else:
        for (h1, r1, g1, b1), (h2, r2, g2, b2) in zip(_STOPS, _STOPS[1:]):
            if h2 <= h <= h1:
                f = (h - h2) / (h1 - h2)
                r = r2 + (r1 - r2) * f
                g = g2 + (g1 - g2) * f
                b = b2 + (b1 - b2) * f
                break
        else:  # pragma: no cover - h in [BLANK, 1] always hits a segment
            r, g, b = _STOPS[-1][1:]
    j = (salt - 0.5) * 2.0 * _JITTER
    return (_clamp255(r + j), _clamp255(g + j), _clamp255(b + j))


# ------------------------------------------------------------- simulation --

class FireState:
    """Mutable simulation state (a single object flows through step())."""

    __slots__ = ("width", "grid_height", "heat", "base", "smoke", "rng", "tick")


def new_state(width, height, seed=0):
    """Create an empty (zero-heat, no-smoke) state, seeded for determinism."""
    st = FireState()
    st.width = width
    st.grid_height = height
    st.heat = [[0.0] * width for _ in range(height)]
    st.base = [[False] * width for _ in range(height)]
    st.smoke = []
    st.rng = random.Random(seed)
    st.tick = 0
    return st


def _axis(y, t, width):
    """Flame centerline at row y, time t: slow global sway + per-row bend."""
    return (
        width / 2.0
        + 2.0 * math.sin(2.0 * math.pi * 0.021 * t + 0.35 * y)
        + 1.2 * math.sin(2.0 * math.pi * 0.0077 * t + 1.3)
    )


def step(st):
    """Advance the simulation by one tick; returns the same state object."""
    t = st.tick
    width = st.width
    height = st.grid_height
    H = height * 0.62  # effective flame height: quadratic cooling dies at H
    w0 = width * 0.45  # half-width of the fuel base
    flicker = 0.82 + 0.28 * st.rng.random()  # whole-flame intensity pulse
    old = st.heat
    new = [[0.0] * width for _ in range(height)]

    for y in range(height):
        ax = _axis(y, t, width)
        if y == 0:
            # wide fuel base with turbulence gaps: most cells hot, some dead
            half = w0
            for x in range(width):
                v = 0.0
                if abs(x - ax) <= half:
                    v = flicker * (0.78 + 0.22 * st.rng.random())
                    if st.rng.random() < 0.22:
                        v = 0.0  # licks/gaps: air breaks through the fuel
                    elif v > 1.0:
                        v = 1.0
                new[0][x] = v
        else:
            # per-row cooling (quadratic) + hard center taper (cone)
            cool = 1.0 - (y / H) ** 2
            if cool <= 0.0:
                continue  # rows above the flame top are dead air
            env_w = max(w0 * max(0.0, 1.0 - y / H) ** 0.8, 1e-9)
            for x in range(width):
                d = (x - ax) / env_w
                if abs(d) >= 1.0:
                    continue  # outside the taper: blank, keeps the cone
                r = st.rng.random()
                shear = -1 if r < 0.15 else (1 if r < 0.30 else 0)
                sx = x + shear
                if sx < 0:
                    sx = 0
                elif sx >= width:
                    sx = width - 1
                a = old[y - 1][sx]
                left = old[y - 1][sx - 1] if sx > 0 else a
                right = old[y - 1][sx + 1] if sx < width - 1 else a
                adv = a if a >= (left + right) * 0.5 else (left + right) * 0.5
                v = adv * (1.0 - d * d) * cool * (0.88 + 0.24 * st.rng.random())
                r2 = st.rng.random()
                if r2 < 0.06:
                    v *= 1.45  # upward lick
                elif r2 < 0.14:
                    v *= 0.45  # turbulent pocket
                if v > 1.0:
                    v = 1.0
                new[y][x] = v

    # base-zone flag: bottom rows of the flame body with live heat -> blue
    base = [[False] * width for _ in range(height)]
    for y in range(min(3, height)):
        row = new[y]
        brow = base[y]
        for x in range(width):
            if row[x] > BLANK:
                brow[x] = True

    # smoke: sparse deterministic particles rising above the flame top
    smoke = []
    for (py, px, life) in st.smoke:
        life -= 0.03 + 0.02 * st.rng.random()
        py += 0.5 + 0.5 * st.rng.random()
        px += (st.rng.random() - 0.5) * 1.2
        if life > 0.0 and py < height + 2:
            smoke.append((py, px, life))
    if len(smoke) < width - 4 and st.rng.random() < 0.6:
        top = max((yy for yy in range(height) if max(new[yy]) > 0.15),
                  default=int(H * 0.8))
        smoke.append((top + 0.3,
                      _axis(top, t, width) + (st.rng.random() - 0.5) * 3.0,
                      1.0))

    st.heat = new
    st.base = base
    st.smoke = smoke
    st.tick = t + 1
    return st


# -------------------------------------------------------------- renderer --

def render(st):
    """Grid + smoke particles -> one ANSI frame string (dims == grid)."""
    width = st.width
    height = st.grid_height
    lines = []
    for fr in range(height):
        g = height - 1 - fr  # frame row 0 = top of screen = last grid row
        cells = []
        for x in range(width):
            salt = ((x * 73 + g * 151 + 17) % 97) / 97.0
            c = palette(st.heat[g][x], st.base[g][x], salt)
            if c is None:
                cells.append(" ")
            else:
                cells.append("\x1b[38;2;%d;%d;%d m\u2580" % c)
        for (py, px, life) in st.smoke:
            gy = int(py)
            gx = int(round(px))
            if 0 <= gy < height and 0 <= gx < width and life > 0.05:
                # faint gray smoke, fading with its life
                c = (_clamp255(20 + 40 * life),
                     _clamp255(20 + 40 * life),
                     _clamp255(22 + 43 * life))
                cells[gx] = "\x1b[38;2;%d;%d;%d m\u2580" % c
        lines.append("".join(cells))
    return "\n".join(lines)


# ------------------------------------------------------------------- loop --

def main():
    """IO only: animate at ~30 FPS, or dump frames when not on a tty."""
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        st = new_state(44, 18, 1)
        for _ in range(5):
            st = step(st)
            sys.stdout.write(render(st) + "\n")
        return 0

    try:
        term = shutil.get_terminal_size()
        tw, th = term.columns, term.rows
    except OSError:
        tw, th = 80, 24
    gw = min(max(tw, 20), 48)
    gh = min(max(th, 10), 20)
    ox = max(0, (tw - gw) // 2)
    oy = max(0, (th - gh) // 2)
    st = new_state(gw, gh, int(time.time() * 1000) & 0x7FFFFFFF)

    sys.stdout.write("\x1b[?25l")  # hide cursor
    sys.stdout.flush()
    try:
        while True:
            st = step(st)
            sys.stdout.write("\x1b[2J\x1b[%d;%dH%s" % (oy + 1, ox + 1,
                                                       render(st)))
            sys.stdout.flush()
            time.sleep(1.0 / 30.0)  # ~30 FPS
    except KeyboardInterrupt:
        pass
    finally:
        sys.stdout.write("\x1b[0m\x1b[?25h")  # reset ANSI, restore cursor
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
