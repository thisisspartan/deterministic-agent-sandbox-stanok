#!/usr/bin/env python3
"""console fire — a heat field, a palette, a half-block renderer, a CLI.

Four concerns in one file, each pure except the CLI:

* simulation — a seeded heat field (rows x columns of floats in [0, 1]);
* palette    — heat -> 24-bit RGB, or None for an empty cell;
* renderer   — a heat field -> one frame string of half-block characters;
* CLI        — the only IO, and it is headless-safe.

Determinism rule: every random value comes from a `random.Random` seeded by
the single `--seed` value, and the colour-jitter stream is derived from that
seed rather than shared with the simulation stream — so rendering a frame
never perturbs the heat field, and the same seed + dimensions always produce
identical frames no matter how many frames were rendered before it.
"""

from __future__ import annotations

import argparse
import random
import re
import shutil
import sys
import time

# --- defaults -------------------------------------------------------------

DEFAULT_SEED = 1
DEFAULT_WIDTH = 40
DEFAULT_HEIGHT = 16
DEFAULT_FPS = 30
FALLBACK_SIZE = (80, 24)  # shutil.get_terminal_size fallback
BASE_ZONE_ROWS = 2  # bottom rows render as the blue combustion zone

# --- simulation constants -------------------------------------------------

IGNITION_LOW = 0.85  # the base row is ignited near 1.0
COOL_LOW = 0.02  # per-step cooling jitter, low end
COOL_HIGH = 0.18  # ... high end: heat decays geometrically with height

# --- palette constants ----------------------------------------------------

# heat -> colour, cold to hot. Luminance increases at every stop, so the
# piecewise-linear gradient is monotone in luminance.
FIRE_STOPS = (
    (0.00, (90, 15, 8)),  # dark red
    (0.20, (160, 30, 10)),  # red
    (0.40, (220, 60, 20)),  # red-orange
    (0.60, (255, 140, 0)),  # orange
    (0.80, (255, 220, 80)),  # yellow
    (1.00, (255, 255, 240)),  # white-hot
)
# The combustion zone: blue-dominant at every stop (b > r holds at both ends
# of every segment, and both channels interpolate linearly).
BLUE_STOPS = (
    (0.00, (12, 14, 46)),
    (0.50, (30, 70, 170)),
    (1.00, (90, 160, 255)),
)
JITTER = 4  # per-cell colour jitter, breaks banding without breaking b > r

# --- ANSI -----------------------------------------------------------------

FG = "\x1b[38;2;{};{};{}m"
BG = "\x1b[48;2;{};{};{}m"
RESET = "\x1b[0m"
DEFAULT_FG = "\x1b[39m"
DEFAULT_BG = "\x1b[49m"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
CLEAR = "\x1b[2J\x1b[H"
HALF_BLOCK = "▀"  # fg paints the upper half, bg paints the lower half
FULL_BLOCK = "█"

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


# --- 1. simulation (pure, deterministic) ----------------------------------


def new_field(width: int, height: int) -> list[list[float]]:
    """An empty heat field: `height` rows of `width` zeros, row 0 at the top."""
    return [[0.0] * max(0, width) for _ in range(max(0, height))]


def advance(field: list[list[float]], rng: random.Random) -> list[list[float]]:
    """One tick, as a new field (the input is never mutated).

    The base row is ignited with seeded values near 1.0. Every cell above
    takes a seeded choice among the cells below it — same column, left,
    right, only cells that exist — reduced by seeded cooling jitter and
    clamped to [0, 1]. The seeded choice among the below-neighbours is what
    makes tongues; a static cone would come from a fixed neighbour rule.
    """
    height = len(field)
    width = len(field[0]) if height else 0
    out = new_field(width, height)
    if height == 0 or width == 0:
        return out

    base = out[height - 1]
    for col in range(width):
        base[col] = min(1.0, max(0.0, rng.uniform(IGNITION_LOW, 1.0)))

    for row in range(height - 1):
        below = field[row + 1]
        target = out[row]
        for col in range(width):
            candidates = [below[col]]
            if col > 0:
                candidates.append(below[col - 1])
            if col < width - 1:
                candidates.append(below[col + 1])
            heat = rng.choice(candidates) * (1.0 - rng.uniform(COOL_LOW, COOL_HIGH))
            target[col] = min(1.0, max(0.0, heat))
    return out


def simulate(
    seed: int, width: int, height: int, ticks: int
) -> list[list[list[float]]]:
    """Fields after ticks 1..ticks from an all-zero start (frame 0 = tick 1)."""
    rng = random.Random(seed)
    field = new_field(width, height)
    frames = []
    for _ in range(max(0, ticks)):
        field = advance(field, rng)
        frames.append(field)
    return frames


# --- 2. palette (pure) ----------------------------------------------------


def _gradient(stops: tuple, heat: float) -> tuple[int, int, int]:
    """Linear interpolation between the palette stops."""
    heat = min(1.0, max(0.0, heat))
    for (start, cold), (end, hot) in zip(stops, stops[1:]):
        if heat <= end:
            span = end - start
            step = 0.0 if span <= 0 else (heat - start) / span
            return tuple(
                int(round(cold[i] + (hot[i] - cold[i]) * step)) for i in range(3)
            )
    return stops[-1][1]


def _jitter(rgb: tuple[int, int, int], rng: random.Random) -> tuple[int, int, int]:
    return tuple(min(255, max(0, c + rng.randint(-JITTER, JITTER))) for c in rgb)


def heat_to_rgb(
    heat: float, base_zone: bool = False, rng: random.Random | None = None
) -> tuple[int, int, int] | None:
    """heat -> (r, g, b), or None for an empty cell (heat <= 0).

    `base_zone` selects the blue combustion gradient (blue-dominant: b > r)
    instead of the fire gradient. `rng` adds a small per-cell jitter that
    breaks colour banding; without it the mapping is exact.
    """
    if heat <= 0.0:
        return None
    rgb = _gradient(BLUE_STOPS if base_zone else FIRE_STOPS, heat)
    if rng is not None:
        rgb = _jitter(rgb, rng)
    return rgb


def _color_seed(seed: int) -> int:
    """The colour stream, derived from the seed but disjoint from the sim one."""
    return seed ^ 0x9E3779B97F4A7C15


# --- 3. renderer (pure) ---------------------------------------------------


def render_frame(
    field: list[list[float]],
    base_zone_rows: int = BASE_ZONE_ROWS,
    rng: random.Random | None = None,
) -> str:
    """A heat field -> ONE frame string: two grid rows per character row.

    Each character is a half-block: its foreground colour is the upper cell,
    its background colour the lower one. Zero-heat cells are plain spaces
    with no ANSI at all, so an all-zero field renders as blank lines.
    """
    height = len(field)
    if height == 0:
        return ""
    width = len(field[0])
    zone_rows = max(0, min(base_zone_rows, height))
    base_start = height - zone_rows

    lines = []
    for char_row in range((height + 1) // 2):
        upper_index = char_row * 2
        lower_index = upper_index + 1
        has_lower = lower_index < height
        parts: list[str] = []
        colored = False
        for col in range(width):
            upper = heat_to_rgb(
                field[upper_index][col],
                base_zone=upper_index >= base_start,
                rng=rng,
            )
            lower = (
                heat_to_rgb(
                    field[lower_index][col],
                    base_zone=lower_index >= base_start,
                    rng=rng,
                )
                if has_lower
                else None
            )
            if upper is None and lower is None:
                parts.append(" ")
                continue
            parts.append(FG.format(*upper) if upper is not None else DEFAULT_FG)
            parts.append(
                BG.format(*lower) if lower is not None else DEFAULT_BG
            )
            parts.append(HALF_BLOCK if has_lower else FULL_BLOCK)
            colored = True
        line = "".join(parts)
        if colored:
            line += RESET  # keeps padding/centring out of a coloured cell
        lines.append(line)
    return "\n".join(lines)


# --- 4. CLI (IO only, headless-safe) --------------------------------------


def _visible(text: str) -> str:
    return _ANSI_RE.sub("", text)


def _centered(lines: list[str], columns: int, rows: int) -> str:
    pad_x = max(0, (columns - max((len(_visible(line)) for line in lines), default=0)) // 2)
    pad_y = max(0, rows - len(lines))
    return "\n".join([""] * pad_y + [" " * pad_x + line for line in lines])


def _is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


def _emit(text: str) -> None:
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="fire.py", description="A console fire. Ctrl-C to stop."
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="grid columns")
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT, help="grid rows")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS, help="animation rate")
    choices = parser.add_mutually_exclusive_group()
    choices.add_argument("--frames", type=int, default=None, help="render N frames, exit")
    choices.add_argument("--frame", type=int, default=None, help="render frame N, exit")
    return parser


def _animate(args, width: int, height: int, columns: int, rows: int) -> int:
    rng = random.Random(args.seed)
    field = new_field(width, height)
    delay = 1.0 / max(1, args.fps)
    sys.stdout.write(HIDE_CURSOR)
    try:
        while True:
            field = advance(field, rng)
            frame = render_frame(field, rng=random.Random(_color_seed(args.seed)))
            sys.stdout.write(CLEAR + _centered(frame.split("\n"), columns, rows) + "\n")
            sys.stdout.flush()
            time.sleep(delay)
    except KeyboardInterrupt:
        pass
    sys.stdout.write(SHOW_CURSOR + RESET)
    sys.stdout.flush()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.width < 1 or args.height < 1:
        parser.error("--width and --height must be at least 1")
    if args.frame is not None and args.frame < 0:
        parser.error("--frame must be at least 0")
    if args.frames is not None and args.frames < 1:
        parser.error("--frames must be at least 1")

    columns, rows = shutil.get_terminal_size(FALLBACK_SIZE)
    # The flame never exceeds the terminal: a 10x5 terminal renders a 10x10
    # grid, not an error.
    width = min(max(1, args.width), columns)
    height = min(max(1, args.height), max(1, rows * 2))

    try:
        if args.frame is not None:
            frames = simulate(args.seed, width, height, args.frame + 1)
            _emit(render_frame(frames[-1], rng=random.Random(_color_seed(args.seed))))
            return 0
        if args.frames is not None:
            for field in simulate(args.seed, width, height, args.frames):
                _emit(render_frame(field, rng=random.Random(_color_seed(args.seed))))
            return 0
        if not _is_tty():
            # Headless (the smoke path: stdin=/dev/null): exactly ONE frame.
            _emit(
                render_frame(
                    simulate(args.seed, width, height, 1)[-1],
                    rng=random.Random(_color_seed(args.seed)),
                )
            )
            return 0
        return _animate(args, width, height, columns, rows)
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
