#!/usr/bin/env python3
"""fire — a terminal "doom-fire" torch.

Two renderings of the same engine (CC-317 batch, CC-318 interactive). Mode
selection is ``sys.stdout.isatty()``:

* batch (not a tty) — frames as plain text, C6, never colored;
* interactive (a tty) — one in-place screen: home + paint per frame,
  truecolor per drawn cell, cursor hidden while drawing, clean exit and a
  clean stop on Ctrl+C (C9..C11).

Contract: SPEC-FIRE-2026-10-22 (C1..C11, Q6). See docs/fire.md.
"""

import argparse
import random
import sys
import time

# C5: palette, index 0..9; a cell renders as PALETTE[heat // 26].
PALETTE = " .:-=+*#%@"

# C10 truecolor table: palette index -> (R, G, B). Index 0 (space) is not
# colored — the table has no entry for it, so no color can leak from it.
FIRE_COLORS = {
    1: (30, 10, 6),
    2: (58, 14, 8),
    3: (96, 22, 10),
    4: (138, 34, 12),
    5: (186, 56, 14),
    6: (222, 94, 22),
    7: (242, 140, 38),
    8: (250, 186, 66),
    9: (255, 240, 170),
}

# C9/C10 control vocabulary. HOME is the only cursor addressing the renderer
# uses; CRLF starts each drawn row at column 0 without relying on the tty's
# ONLCR translation; CLEANUP is the one exit sequence (order fixed by C10).
HOME = "\x1b[H"
HIDE_CURSOR = "\x1b[?25l"
SHOW_CURSOR = "\x1b[?25h"
RESET = "\x1b[0m"
CLEANUP = RESET + SHOW_CURSOR
CRLF = "\r\n"

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
        description="Terminal doom-fire torch (batch on a pipe, "
                    "interactive on a terminal).",
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
                             "(pacing in interactive mode; unused in batch)")
    parser.add_argument("--no-color", action="store_true",
                        help="disable color (interactive only: batch output "
                             "is never colored)")
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


def color_sgr(char):
    """C10: the truecolor SGR that must precede one palette character, or ''
    for the space (index 0 has no entry in the table — nothing to invent)."""
    index = PALETTE.index(char)
    if index == 0:
        return ""
    r, g, b = FIRE_COLORS[index]
    return f"\x1b[38;2;{r};{g};{b}m"


def frame_bytes(heat, color=True):
    """C9/C10: one frame as terminal bytes — home to (0,0), then exactly
    `height` rows of exactly `width` cells (spaces included, so nothing of
    what was on the screen survives), rows started by CRLF, and NO newline
    after the last row (a trailing LF on a height==rows screen would scroll
    it). With color=True every drawn non-space cell is preceded by its table
    SGR; color=False emits no SGR and the same grid."""
    parts = [HOME]
    for y, row in enumerate(render_frame(heat)):
        if y:
            parts.append(CRLF)
        if color:
            parts.append("".join(color_sgr(cell) + cell for cell in row))
        else:
            parts.append(row)
    return "".join(parts)


def interactive_stream(heats, color=True):
    """The interactive byte stream as data: hide the cursor, then for every
    frame home+paint, then CLEANUP. No I/O, no pacing — this is what
    run_interactive writes, piece by piece, so the two cannot disagree."""
    parts = [HIDE_CURSOR]
    for heat in heats:
        parts.append(frame_bytes(heat, color))
    parts.append(CLEANUP)
    return "".join(parts)


def run_interactive(args):
    """C9..C11 on a terminal: hide the cursor once, then per frame home and
    paint the grid, paced at --fps; stop after the last frame or on Ctrl+C
    (SIGINT, whatever the delivery — the PTY line discipline for a real
    Ctrl+C), and in both cases emit CLEANUP (ESC[0m then ESC[?25h) before
    returning. rc 0 on a natural end and on a Ctrl+C stop (C11 allows 0 or
    130). The terminal's own settings are never touched — borrowed, not kept.

    The engine and the PRNG call order are the batch ones (C3/C4/C5): the
    same seed drives both renderings."""
    rng = random.Random(args.seed)
    heat = [[0] * args.width for _ in range(args.height)]
    color = not args.no_color
    out = sys.stdout

    out.write(HIDE_CURSOR)  # C9: hidden before the first frame
    out.flush()
    try:
        for frame_index in range(args.frames):
            step_heat(heat, rng)
            out.write(frame_bytes(heat, color))  # C9 home + C10 color
            out.flush()
            if frame_index + 1 < args.frames:
                time.sleep(1.0 / args.fps)
    except KeyboardInterrupt:
        # C11: Ctrl+C — stop drawing, clean up, exit. No traceback, no
        # further frame; the handler itself is the interpreter's default.
        pass
    out.write(CLEANUP)
    out.flush()
    return 0


def main(argv=None):
    args = parse_args(argv)
    if not sys.stdout.isatty():
        return run_batch(args)
    return run_interactive(args)  # C9: the TTY branch


if __name__ == "__main__":
    sys.exit(main())
