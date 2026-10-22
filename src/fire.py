#!/usr/bin/env python3
"""fire — a terminal "doom-fire" torch.

Batch mode only (CC-317): CLI + heat engine + palette render on stdout.
Mode selection is ``sys.stdout.isatty()``; the interactive (TTY) branch is
the next ticket and is not implemented here — until it exists both paths
render the deterministic batch output.

Contract: SPEC-FIRE-2026-10-22 (C1..C8, Q6). See docs/fire.md.
"""

import argparse
import random
import sys

# C5: palette, index 0..9; a cell renders as PALETTE[heat // 26].
PALETTE = " .:-=+*#%@"

# Q6 boundaries.
WIDTH_MIN, WIDTH_MAX = 8, 256
HEIGHT_MIN, HEIGHT_MAX = 5, 120
FRAMES_MIN, FRAMES_MAX = 1, 1000
FPS_MIN, FPS_MAX = 1, 60
SEED_MIN = 0

# C4 engine constants.
BOTTOM_MIN, BOTTOM_MAX = 224, 255
COOL_MIN, COOL_MAX = 21, 45


def parse_args(argv=None):
    """C1 CLI; C2/Q6 validation. Any violation exits 2 with a message on
    stderr and an empty stdout (argparse semantics)."""
    parser = argparse.ArgumentParser(
        prog="fire",
        description="Terminal doom-fire torch (batch mode).",
    )
    parser.add_argument("--width", type=int, default=40,
                        help=f"frame width, {WIDTH_MIN}..{WIDTH_MAX} (default 40)")
    parser.add_argument("--height", type=int, default=12,
                        help=f"frame height, {HEIGHT_MIN}..{HEIGHT_MAX} (default 12)")
    parser.add_argument("--frames", type=int, required=True,
                        help=f"number of frames to render, {FRAMES_MIN}..{FRAMES_MAX}")
    parser.add_argument("--seed", type=int, default=0,
                        help=f"PRNG seed, >= {SEED_MIN} (default 0)")
    parser.add_argument("--fps", type=int, default=30,
                        help=f"frames per second, {FPS_MIN}..{FPS_MAX} "
                             "(unused in batch mode)")
    parser.add_argument("--no-color", action="store_true",
                        help="disable color (batch output is never colored)")
    args = parser.parse_args(argv)
    _validate(parser, args)
    return args


def _validate(parser, args):
    def check(value, lo, hi, name):
        if not lo <= value <= hi:
            parser.error(f"{name} must be in {lo}..{hi}, got {value}")

    check(args.width, WIDTH_MIN, WIDTH_MAX, "--width")
    check(args.height, HEIGHT_MIN, HEIGHT_MAX, "--height")
    check(args.frames, FRAMES_MIN, FRAMES_MAX, "--frames")
    check(args.fps, FPS_MIN, FPS_MAX, "--fps")
    if args.seed < SEED_MIN:
        parser.error(f"--seed must be >= {SEED_MIN}, got {args.seed}")


def step_heat(heat, rng):
    """C4 engine step, in place: seed the bottom row from the PRNG, then
    propagate bottom-up with a per-cell cooling draw. The order of PRNG
    calls is fixed, which is what C3 determinism rests on."""
    height = len(heat)
    width = len(heat[0])
    bottom = heat[height - 1]
    for x in range(width):
        bottom[x] = rng.randint(BOTTOM_MIN, BOTTOM_MAX)
    for y in range(height - 2, -1, -1):
        row = heat[y]
        below = heat[y + 1]
        for x in range(width):
            a = below[x - 1] if x > 0 else 0
            b = below[x]
            c = below[x + 1] if x + 1 < width else 0
            row[x] = max(0, (a + b + c) // 3 - rng.randint(COOL_MIN, COOL_MAX))


def render_frame(heat):
    """C5: one line per row, each cell PALETTE[heat // 26]."""
    return ["".join(PALETTE[heat_cell // 26] for heat_cell in row) for row in heat]


def run_batch(args):
    """C6 batch output: exactly `frames` frames separated by exactly one
    empty line; each frame `height` lines of `width` palette characters;
    ends with exactly one '\\n', no trailing empty line; never colored."""
    rng = random.Random(args.seed)  # C3: the single source of randomness
    heat = [[0] * args.width for _ in range(args.height)]
    blocks = []
    for _ in range(args.frames):
        step_heat(heat, rng)  # C4 step
        blocks.append("\n".join(render_frame(heat)))  # render AFTER the step
    sys.stdout.write("\n\n".join(blocks) + "\n")


def main(argv=None):
    args = parse_args(argv)
    if not sys.stdout.isatty():
        return run_batch(args)
    # TTY branch: interactive mode is the next ticket (CC-318). Until it
    # exists the torch renders the same deterministic batch output.
    return run_batch(args)


if __name__ == "__main__":
    sys.exit(main())
