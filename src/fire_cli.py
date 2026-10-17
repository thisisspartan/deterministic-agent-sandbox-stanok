"""fire_cli — stage 3 of the console-fire pipeline: the CLI and animation loop.

The ONLY module of the program with IO: argparse, writes to stdout, terminal
size probing, sleeps. It composes the two pure stages — fire_sim (seeded
fields + palette) and fire_render (field -> frame string) — into a runnable
program. Everything here is IO; the numerics and the glyphs stay in stages
1 and 2.

The contract is documented in docs/fire_cli.md and pinned by
tests/fire_cli_test.py.
"""

import argparse
import random
import shutil
import sys
import time

import fire_render
import fire_sim

FRAME_SEPARATOR = "\n\n"  # a blank line between frame blocks on stdout
ANSI_CLEAR = "\x1b[2J\x1b[H"  # clear + home: redraw the animation in place


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A seeded console fire: fire_sim fields rendered by fire_render.",
    )
    parser.add_argument("--seed", type=int, default=1, help="seed of the whole run (default: 1)")
    parser.add_argument("--width", type=int, default=40, help="grid width, >= 1 (default: 40)")
    parser.add_argument(
        "--height", type=int, default=16, help="grid height, >= 1 and EVEN (default: 16)"
    )
    parser.add_argument("--fps", type=int, default=30, help="animation rate, >= 1 (default: 30)")
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--frames", type=int, help="print N frames (N >= 1) to stdout and exit")
    target.add_argument("--frame", type=int, help="print only frame N (N >= 0) of the sequence and exit")
    return parser


def _validated_args(parser: argparse.ArgumentParser, argv: list[str] | None):
    """Parse, then enforce the value ranges. An invalid value is rejected with
    parser.error -> usage message on stderr, exit code 2, no traceback."""
    args = parser.parse_args(argv)
    if args.width < 1:
        parser.error(f"--width must be >= 1 (got {args.width})")
    if args.height < 1 or args.height % 2 != 0:
        parser.error(f"--height must be >= 1 and even (got {args.height})")
    if args.fps < 1:
        parser.error(f"--fps must be >= 1 (got {args.fps})")
    if args.frames is not None and args.frames < 1:
        parser.error(f"--frames must be >= 1 (got {args.frames})")
    if args.frame is not None and args.frame < 0:
        parser.error(f"--frame must be >= 0 (got {args.frame})")
    return args


def _canvas(frame: str, *, full_screen: bool) -> str:
    """Compose one frame into a canvas sized by the probed terminal.

    The terminal size is the canvas the user asked for; it is clamped UP to
    the frame's own size, because compose_frame measures raw string length
    (truecolor escape sequences included) and must never reject the frame:
    a small terminal renders the whole flame instead of failing.

    full_screen=False (the deterministic --frames/--frame modes) keeps the
    canvas exactly as tall as the frame: a frame stream is a stream of
    blocks, and padding each block to the terminal height would bury the
    frame separator between blank lines.
    """
    size = shutil.get_terminal_size(
        (fire_render.FALLBACK_COLUMNS, fire_render.FALLBACK_ROWS)
    )
    lines = frame.split("\n")
    columns = max(size.columns, max((len(line) for line in lines), default=0))
    rows = max(size.lines, len(lines)) if full_screen else len(lines)
    return fire_render.compose_frame(frame, columns, rows)


def _print_frames(
    seed: int, width: int, height: int, count: int, *, only_last: bool
) -> int:
    """Render `count` frames of the seeded sequence to stdout.

    ONE random.Random(seed) drives heat_to_rgb across every rendered frame
    (render_frame's color_rng), so frame i's colors are that stream's state
    after frames 0..i-1. That is what makes `--frame N` byte-identical to the
    last frame of `--frames N+1` (the prefix property): with only_last=True
    the earlier frames are still rendered — advancing the color stream — but
    not printed.

    Frames are written as blocks of `height // 2` lines separated by
    FRAME_SEPARATOR; stdout ends with a newline.
    """
    color_rng = random.Random(seed)
    rendered = [
        _canvas(fire_render.render_frame(field, color_rng), full_screen=False)
        for field in fire_sim.simulate(seed, width, height, count)
    ]
    if only_last:
        rendered = rendered[-1:]
    sys.stdout.write(FRAME_SEPARATOR.join(rendered) + "\n")
    sys.stdout.flush()
    return 0


def _animate(seed: int, width: int, height: int, fps: int) -> int:
    """Loop frames at 1/fps, redrawing the full-screen canvas in place, until
    SIGINT (KeyboardInterrupt) — which ends the animation cleanly: rc 0, no
    traceback. The simulation and the color stream are two rngs seeded with
    the same value, so a run is reproducible up to the interrupt."""
    sim_rng = random.Random(seed)
    color_rng = random.Random(seed)
    field = fire_sim.new_field(width, height)
    try:
        while True:
            field = fire_sim.advance(field, sim_rng)
            frame = fire_render.render_frame(field, color_rng)
            sys.stdout.write(ANSI_CLEAR + _canvas(frame, full_screen=True) + "\n")
            sys.stdout.flush()
            time.sleep(1.0 / fps)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns the exit code: 0 on success, 2 on a usage error
    (argparse's own code — parser.error prints the usage to stderr and exits
    before main returns)."""
    parser = _build_parser()
    args = _validated_args(parser, argv)

    if args.frames is not None:
        return _print_frames(args.seed, args.width, args.height, args.frames, only_last=False)
    if args.frame is not None:
        return _print_frames(args.seed, args.width, args.height, args.frame + 1, only_last=True)
    return _animate(args.seed, args.width, args.height, args.fps)


if __name__ == "__main__":
    sys.exit(main())
