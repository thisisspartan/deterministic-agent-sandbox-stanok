"""Deterministic multicolor terminal fire (CC-110).

Four separated concerns:

1. Simulation  -- ``FireSim``: a pure, deterministic 2D heat-field grid of
   floats in [0, 1]. Per tick: turbulence-offset upward diffusion from the
   row below (with per-cell cold pockets that carve internal gaps --
   the flame body licks, it is not a solid cone), decay, base-row heat
   injection (edge ignitions below the blank threshold are dropped, so
   the flame never touches the terminal edges), and a sparse
   smoke-particle list rising above the flame top. One seeded
   ``random.Random`` drives every draw, so a fixed seed reproduces every
   frame byte-for-byte.
2. Palette     -- pure ``(heat, is_base) -> (r, g, b) | None``: a
   multi-stop hot->cold gradient (white-hot -> yellow -> orange ->
   red-orange -> red -> dark red), a blue combustion gradient for base
   zone cells, ``None`` below the blank threshold.
3. Renderer    -- pure ``render(sim, color_mode="truecolor") -> str``:
   one ANSI frame of half-block (``\\u2580``) cells; frame dimensions
   match the grid; zero heat renders as plain spaces; smoke renders
   faint gray. ``color_mode`` picks the escape style: ``"truecolor"``
   (24-bit, the default, byte-identical to the original output),
   ``"256"`` (``\\x1b[38;5;Nm`` via :func:`rgb_to_256`), ``"16"``
   (basic SGR ``\\x1b[3Xm`` for N in 0..7 and ``\\x1b[9Xm`` for N in 8..15
   via :func:`rgb_to_16` -- the last-resort fallback for terminals that
   drop extended 256-color escapes) or
   ``"none"`` (no ANSI escapes).
4. Loop        -- IO only, under ``if __name__ == "__main__"``: ~30 FPS
   animation on a TTY (centered in the terminal), a single headless frame
   when stdout is not a TTY, deterministic ``--frame N`` / ``--frames N``
   CLI modes, and a clean SIGINT shutdown.

Stdlib only. No side effects on import.
"""

import argparse
import os
import random
import shutil
import sys
import time

# --------------------------------------------------------------------------
# Palette (pure)
# --------------------------------------------------------------------------

#: Heat below this renders as a blank (empty) cell (ticket allows <= 0.10).
BLANK_THRESHOLD = 0.10

#: Multi-stop gradient, hottest -> coldest. heat >= stop renders that color.
FLAME_STOPS = (
    (0.01, (70, 10, 6)),      # ember
    (0.10, (90, 15, 8)),      # dark red
    (0.20, (160, 30, 10)),    # red
    (0.35, (220, 60, 20)),    # red-orange
    (0.50, (255, 140, 0)),    # orange
    (0.70, (255, 220, 80)),   # yellow
    (1.00, (255, 255, 240)),  # white-hot
)

#: Blue combustion-zone gradient (bottom rows).
BASE_STOPS = (
    (0.00, (25, 45, 90)),
    (0.50, (80, 130, 220)),
    (1.00, (150, 200, 255)),
)

#: Faint smoke gray.
SMOKE_RGB = (60, 60, 65)


def _lerp(stops, heat):
    """Piecewise-linear interpolation across ``(heat, rgb)`` stops."""
    if heat <= stops[0][0]:
        return stops[0][1]
    for (h0, c0), (h1, c1) in zip(stops, stops[1:]):
        if heat <= h1:
            t = (heat - h0) / (h1 - h0)
            return tuple(int(round(a + t * (b - a))) for a, b in zip(c0, c1))
    return stops[-1][1]


def palette(heat, is_base, blank=0.01):
    """Map ``(heat, is_base)`` to an ``(r, g, b)`` int tuple, or ``None``
    for a blank cell (zero heat; non-base heat below the blank threshold).

    ``blank`` is the cold-blank threshold for non-base heat: heat below it
    renders as an empty cell. The renderer passes :data:`BLANK_THRESHOLD`
    (<= 0.10) so near-dead heat never fills the grid; the legacy default
    ``0.01`` keeps the two-argument behavior unchanged.
    """
    if heat <= 0.0:
        return None
    if is_base:
        return _lerp(BASE_STOPS, heat)
    if heat < blank:
        return None
    return _lerp(FLAME_STOPS, heat)


def _cell_jitter(x, y, channel):
    """Bounded per-cell jitter magnitude in [-8, 8], deterministic in the
    cell coordinates and channel index (no PRNG state, no wall clock)."""
    v = 1000003 * x + 3000007 * y + 1234567 * channel + 7
    v ^= v >> 13
    v = (v * 1274126177) & 0xFFFFFFFF
    return (v % 17) - 8


def jittered_rgb(rgb, x, y):
    """Seed-stable per-cell color jitter that breaks banding: each channel
    moves at most 8 and stays within [0, 255]; adjacent cells with equal
    heat never render identically."""
    return tuple(
        max(0, min(255, c + _cell_jitter(x, y, ch)))
        for ch, c in enumerate(rgb)
    )


# --------------------------------------------------------------------------
# 256-color / 16-color quantization and terminal capability detection
# (CC-113, CC-116)
# --------------------------------------------------------------------------

#: Standard xterm 16-color ANSI palette (indices 0..15).
ANSI16_RGB = (
    (0, 0, 0), (196, 0, 0), (0, 196, 0), (196, 196, 0),
    (0, 0, 204), (196, 0, 196), (0, 196, 196), (229, 229, 229),
    (0, 0, 0), (196, 0, 0), (0, 196, 0), (196, 196, 0),
    (0, 0, 204), (196, 0, 196), (0, 196, 196), (229, 229, 229),
)

#: 6x6x6 cube channel values (indices 16..231).
_CUBE_VALUES = (0, 95, 135, 175, 215, 255)

#: The full standard 256-color palette as ``(r, g, b)`` tuples indexed by
#: escape index 0..255: 16 base colors, 6x6x6 cube, 24-step gray ramp.
_PALETTE256 = list(ANSI16_RGB)
for _r in _CUBE_VALUES:
    for _g in _CUBE_VALUES:
        for _b in _CUBE_VALUES:
            _PALETTE256.append((_r, _g, _b))
for _i in range(24):
    _v = 255 if _i == 23 else 8 + 10 * _i
    _PALETTE256.append((_v, _v, _v))


def rgb_to_256(rgb):
    """Nearest color in the standard 256-color palette (16 base colors,
    6x6x6 cube, 24-step grayscale ramp), returned as an int index in
    0..255. Deterministic; on an exact distance tie the cube color wins,
    so black maps to 16 and white to 231."""
    r, g, b = rgb
    best_i, best_key = 0, None
    for i, (pr, pg, pb) in enumerate(_PALETTE256):
        d = (pr - r) * (pr - r) + (pg - g) * (pg - g) + (pb - b) * (pb - b)
        key = (d, 0 if 16 <= i <= 231 else 1, i)
        if best_key is None or key < best_key:
            best_key, best_i = key, i
    return best_i


def rgb_to_16(rgb):
    """Nearest of the 16 basic ANSI colors (standard 0..15 palette:
    black, red, green, yellow, blue, magenta, cyan, white, then the
    bright variants 9..15), returned as an int index in 0..15.
    Deterministic; on a distance tie the lower index wins, so e.g. pure
    red maps to 1 and pure white to 7."""
    r, g, b = rgb
    best_i, best_d = 0, None
    for i, (pr, pg, pb) in enumerate(ANSI16_RGB):
        d = (pr - r) * (pr - r) + (pg - g) * (pg - g) + (pb - b) * (pb - b)
        if best_d is None or d < best_d:
            best_d, best_i = d, i
    return best_i


def detect_color_mode(env=None):
    """Detect terminal color capability from environment variables.

    ``"none"`` on an EXPLICIT opt-out: ``NO_COLOR`` set to a non-empty
    value (wins over everything) or ``TERM == "dumb"``. Else
    ``"truecolor"`` when ``COLORTERM`` contains ``truecolor`` or ``24bit``
    (case-insensitive; takes precedence over ``TERM``). Else ``"256"`` --
    the default: most terminals support 256 colors even without an
    explicit signal. ``env`` defaults to ``os.environ``.
    """
    env = os.environ if env is None else env
    if env.get("NO_COLOR"):
        return "none"
    term = (env.get("TERM") or "").lower()
    if term == "dumb":
        return "none"
    colorterm = (env.get("COLORTERM") or "").lower()
    if "truecolor" in colorterm or "24bit" in colorterm:
        return "truecolor"
    return "256"


# --------------------------------------------------------------------------
# Simulation (pure, deterministic)
# --------------------------------------------------------------------------

DECAY = 0.84          # per-row heat retention while rising (strong cooling
                      # so the flame dies out well before the top row)
INJECT_PROB = 0.70    # base-row ignition probability per cell per tick
                      # (leaves gaps -> ragged, non-solid base)
INJECT_MIN = 0.88     # ignition heat floor
GAP_PROB = 0.20       # probability per cell of a cold pocket in the
                      # gap band (see GAP_ROW_FRACTION): the cell skips
                      # diffusion this tick, leaving internal gaps between
                      # tongues -- the flame body licks instead of forming
                      # a solid cone. A killed cell also feeds 0 to the row
                      # above next tick, so gaps streak slightly upward
                      # (tongue-like). The upper rows stay coherent, so the
                      # tip keeps its cone silhouette and heat still rises
                      # to the top rows.
GAP_ROW_FRACTION = 0.75  # cold pockets apply only to rows y >= h * this:
                        # the licking is concentrated in the lower body,
                        # never in the rising tip
SMOKE_PROB = 0.35     # smoke spawn probability per tick
SMOKE_FADE = 0.12     # life lost per tick
MAX_SMOKE = 12        # hard cap on live smoke particles
FLAME_TOP_HEAT = 0.40  # heat threshold for "flame top" / smoke spawning


class SmokeParticle:
    """A sparse deterministic smoke puff: integer grid position plus a
    life in (0, 1]."""

    __slots__ = ("x", "y", "life")

    def __init__(self, x, y, life):
        self.x = x
        self.y = y
        self.life = life


class FireSim:
    """A deterministic 2D heat-field fire simulation.

    ``heat`` is indexed ``[y][x]`` with ``y = 0`` at the TOP of the screen
    and ``y = height - 1`` at the base (where fuel is injected).
    """

    def __init__(self, width, height, seed=42, inject=True):
        self.w = width
        self.h = height
        self.heat = [[0.0] * width for _ in range(height)]
        depth = max(1, height // 10)
        self.base = [[(y >= height - depth) for _ in range(width)]
                     for y in range(height)]
        self.smoke = []
        self.inject = inject
        self.rng = random.Random(seed)
        # Cone taper, precomputed (no PRNG involved): 1.0 on the central
        # axis, shrinking to 0 at the row edges the higher a row sits
        # above the base -- the flame narrows to a point as it rises
        # instead of filling a rectangular block.
        self.taper = [[self._taper(x, y) for x in range(width)]
                      for y in range(height)]

    def _taper(self, x, y):
        """Lateral cone factor for cell ``(x, y)`` in [0, 1]: a hard gate
        for rising rows (0 outside the cone) and a gentle edge dimmer on
        the base row."""
        r = (self.h - 1) - y  # rows above the base
        c = (self.w - 1) / 2.0
        hw = (self.w / 2.0) * (1.0 - r / self.h)
        d = abs(x - c)
        if d >= hw:
            return 0.0
        return 1.0 - d / hw

    def _flame_top(self):
        """Smallest y (topmost row) whose row carries flame heat, or None."""
        for y in range(self.h):
            if max(self.heat[y]) > FLAME_TOP_HEAT:
                return y
        return None

    def tick(self):
        """Advance one frame: diffuse upward with turbulence, decay,
        inject at the base, and update the smoke particles."""
        rng = self.rng
        w, h = self.w, self.h
        old = self.heat

        # Per-row horizontal turbulence: the new row samples the row below
        # with a small deterministic-per-seed offset. The cone taper acts
        # as a hard gate (cells outside the cone stay cold); it must not
        # also multiply the heat, or it compounds row after row and the
        # flame dies out well before the upper rows.
        wobble = [rng.randint(-1, 1) for _ in range(h - 1)]
        new = [[0.0] * w for _ in range(h)]
        for y in range(h - 1):
            src = old[y + 1]
            row = new[y]
            taper = self.taper[y]
            off = wobble[y]
            for x in range(w):
                if taper[x] <= 0.0:
                    continue
                if y >= int(h * GAP_ROW_FRACTION) and rng.random() < GAP_PROB:
                    continue  # cold pocket: internal gap / tongue edge
                i = x + off
                s = 0.0
                if 0 <= i - 1 < w:
                    s += src[i - 1]
                if 0 <= i < w:
                    s += src[i]
                if 0 <= i + 1 < w:
                    s += src[i + 1]
                row[x] = (s / 3.0) * DECAY

        if self.inject:
            base_row = new[h - 1]
            base_taper = self.taper[h - 1]
            # CC-114: inject only in the central third of the terminal
            # (columns [w//3, 2*w//3], inclusive): the flame is a central
            # cone that scales with the width, not a mountain filling it.
            # Per-cell ignition probability keeps the band ragged, not solid.
            for x in range(w // 3, 2 * w // 3 + 1):
                if rng.random() < INJECT_PROB:
                    # Clamp at 1.0: the base taper dims only the row
                    # edges, and heat must stay within [0, 1].
                    heat = min(
                        1.0, (INJECT_MIN + 0.15 * rng.random()) * base_taper[x]
                    )
                    # Base-zone cells render blue for ANY heat > 0, so an
                    # edge ignition below the blank threshold would make
                    # the flame touch the terminal edge -- drop it.
                    if heat >= BLANK_THRESHOLD:
                        base_row[x] = heat

        self.heat = new
        self._tick_smoke()

    def _tick_smoke(self):
        """Age existing particles, drop dead/out-of-bounds ones, and
        occasionally spawn one above the current flame top."""
        rng = self.rng
        w, h = self.w, self.h
        smoke = []
        for p in self.smoke:
            p.life -= SMOKE_FADE
            p.y -= 1
            if rng.random() < 0.4:
                p.x += rng.randint(-1, 1)
            if 0.0 < p.life <= 1.0 and 0 <= p.x < w and 0 <= p.y < h:
                smoke.append(p)
        if self.inject and len(smoke) < MAX_SMOKE and rng.random() < SMOKE_PROB:
            ytop = self._flame_top()
            if ytop is not None and ytop > 0:
                hot = [x for x in range(w) if self.heat[ytop][x] > FLAME_TOP_HEAT]
                if hot:
                    smoke.append(SmokeParticle(rng.choice(hot), ytop - 1, 1.0))
        self.smoke = smoke


# --------------------------------------------------------------------------
# Renderer (pure)
# --------------------------------------------------------------------------

def render(sim, color_mode="truecolor"):
    """Render one ANSI frame: ``height`` newline-joined rows of exactly
    ``width`` cells. A cell is either a colored half-block (``\\u2580``)
    or a plain space. ``color_mode`` picks the escape style:

    - ``"truecolor"`` (default) -- ``\\x1b[38;2;R;G;Bm\\x1b[0m\\u2580``;
    - ``"256"`` -- ``\\x1b[38;5;Nm\\x1b[0m\\u2580`` with
      ``N = rgb_to_256(jittered rgb)``;
    - ``"16"`` -- basic SGR, the most compatible encoding: with
      ``N = rgb_to_16(jittered rgb)``, N in 0..7 renders
      ``\\x1b[3Xm\\x1b[0m\\u2580`` (X = N) and N in 8..15 renders
      ``\\x1b[9Xm\\x1b[0m\\u2580`` (X = N - 8): the last-resort fallback
      for terminals that drop extended ``\\x1b[38;5;N`` escapes even for
      N in 0..15;
    - ``"none"`` -- plain ``\\u2580``, no ANSI escapes.
    """
    w, h = sim.w, sim.h
    smoke = {}
    for p in sim.smoke:
        smoke[(p.x, p.y)] = p.life
    rows = []
    for y in range(h):
        row = sim.heat[y]
        flags = sim.base[y]
        cells = []
        for x in range(w):
            rgb = palette(row[x], flags[x], BLANK_THRESHOLD)
            if rgb is None and (x, y) in smoke:
                rgb = SMOKE_RGB
            if rgb is None:
                cells.append(" ")
            else:
                r, g, b = jittered_rgb(rgb, x, y)
                if color_mode == "256":
                    cells.append(
                        "\x1b[38;5;%dm\x1b[0m\u2580" % rgb_to_256((r, g, b))
                    )
                elif color_mode == "16":
                    # CC-117: basic SGR codes only -- the most compatible
                    # color encoding that exists. Terminals that drop the
                    # extended \x1b[38;5;N sequences do so even for N in
                    # 0..15, but usually still understand \x1b[3Xm (0..7)
                    # and \x1b[9Xm (bright 8..15).
                    n = rgb_to_16((r, g, b))
                    if n < 8:
                        cells.append("\x1b[3%dm\x1b[0m\u2580" % n)
                    else:
                        cells.append("\x1b[9%dm\x1b[0m\u2580" % (n - 8))
                elif color_mode == "none":
                    cells.append("\u2580")
                else:
                    cells.append(
                        "\x1b[38;2;%d;%d;%dm\x1b[0m\u2580" % (r, g, b)
                    )
        rows.append("".join(cells))
    return "\n".join(rows)


# --------------------------------------------------------------------------
# Loop (IO only)
# --------------------------------------------------------------------------

def _terminal_size():
    try:
        size = shutil.get_terminal_size()
        return size.columns, size.lines
    except OSError:
        return 80, 24


def _center(frame, width):
    """Left-pad each row so a flame of visible ``width`` sits centered in
    the terminal (no-op if the terminal is no wider)."""
    term_w, _ = _terminal_size()
    pad = (term_w - width) // 2
    if pad <= 0:
        return frame
    pad_s = " " * pad
    return "\n".join(pad_s + line for line in frame.split("\n"))


def _animation_loop(sim, fps, color_mode="truecolor"):
    """TTY mode: clear per frame, ~``fps`` frames/second, exit 0 on SIGINT
    with the cursor restored and ANSI reset."""
    out = sys.stdout
    out.write("\x1b[?25l\x1b[2J\x1b[H")
    out.flush()
    step = 1.0 / fps
    try:
        while True:
            t0 = time.monotonic()
            sim.tick()
            frame = _center(render(sim, color_mode), sim.w)
            out.write("\x1b[2J\x1b[H" + frame + "\n")
            out.flush()
            time.sleep(max(0.0, step - (time.monotonic() - t0)))
    except KeyboardInterrupt:
        out.write("\x1b[?25h\x1b[0m\n")
        out.flush()
        return 0


def main(argv=None):
    """CLI entrypoint: argparse flags, headless-safe, deterministic."""
    parser = argparse.ArgumentParser(
        prog="fire.py",
        description="Deterministic multicolor terminal fire.",
    )
    parser.add_argument("--seed", type=int, default=42,
                        help="PRNG seed (default 42)")
    parser.add_argument("--width", type=int, default=None,
                        help="frame width (default: terminal width)")
    parser.add_argument("--height", type=int, default=None,
                        help="frame height (default: terminal height)")
    parser.add_argument("--fps", type=int, default=30,
                        help="animation frames per second (default 30)")
    parser.add_argument("--frames", type=int, default=None,
                        help="render N frames then exit 0")
    parser.add_argument("--frame", type=int, default=None,
                        help="render exactly frame N then exit 0")
    parser.add_argument("--color",
                        choices=("truecolor", "256", "16", "none"),
                        default=None,
                        help="force the color mode (default: auto-detect on a "
                             "TTY -- 256 unless NO_COLOR/TERM=dumb or "
                             "COLORTERM truecolor/24bit -- truecolor headless); "
                             "16 = basic ANSI palette fallback for terminals "
                             "that drop 256-color escapes")
    args = parser.parse_args(argv)

    term_w, term_h = _terminal_size()
    w = args.width if args.width is not None else term_w
    h = args.height if args.height is not None else term_h
    if w < 1:
        parser.error("--width must be >= 1")
    if h < 1:
        parser.error("--height must be >= 1")
    if args.fps < 1:
        parser.error("--fps must be >= 1")
    if args.frames is not None and args.frames < 0:
        parser.error("--frames must be >= 0")
    if args.frame is not None and args.frame < 0:
        parser.error("--frame must be >= 0")

    sim = FireSim(w, h, seed=args.seed)

    # Color mode: --color forces it; otherwise auto-detect on a TTY and
    # keep the legacy truecolor default headless.
    if args.color is not None:
        color_mode = args.color
    elif sys.stdout.isatty():
        color_mode = detect_color_mode(os.environ)
    else:
        color_mode = "truecolor"

    def emit(frame):
        try:
            sys.stdout.write(frame + "\n")
            sys.stdout.flush()
            return 0
        except (BrokenPipeError, ValueError):
            # stdout is a closed pipe (e.g. `| head`): not a crash.
            return 0

    if args.frame is not None:
        for _ in range(args.frame):
            sim.tick()
        return emit(render(sim, color_mode))
    if args.frames is not None:
        rc = 0
        for _ in range(args.frames):
            sim.tick()
            rc = emit(render(sim, color_mode)) or rc
        return rc
    if sys.stdout.isatty():
        return _animation_loop(sim, args.fps, color_mode)
    # Headless: exactly one frame, no loop.
    return emit(render(sim, color_mode))


if __name__ == "__main__":
    try:
        rc = main()
    except KeyboardInterrupt:
        # SIGINT anywhere: restore the cursor, reset ANSI, exit 0.
        try:
            sys.stdout.write("\x1b[?25h\x1b[0m\n")
            sys.stdout.flush()
        except (OSError, ValueError, BrokenPipeError):
            pass
        rc = 0
    # Point the stdout fd at /dev/null before exiting so a pipe that was
    # closed early (e.g. `| head`) cannot raise BrokenPipeError at
    # interpreter shutdown and turn a clean run into rc=1.
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        os.close(devnull)
    except (OSError, ValueError, AttributeError):
        pass
    sys.exit(rc)
