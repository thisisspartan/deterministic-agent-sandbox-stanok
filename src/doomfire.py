"""doomfire runner CLI — wires the model, the palette and the controller.

Two modes, one entry point:

* headless (``--headless N``): no TTY, no signals, no sleep. The field is
  built with the core model driven by a private ``random.Random(seed)`` and
  each rendered frame is written as UTF-8 bytes to ``sys.stdout.buffer``, so
  the output is locale-independent and byte-identical for identical arguments.
* interactive (no ``--headless``): only on a TTY; otherwise the CLI prints a
  one-line hint on stderr and exits 2. The loop steps the model, presents the
  frame through ``TerminalController`` (which owns setup/teardown and the
  signal flags) and sleeps to the next frame deadline on a monotonic clock.

Importing this module has no side effects: no loop starts, nothing is printed.
"""

import argparse
import random
import shutil
import sys
import time

from doomfire_core import create_field, seed_bottom, step
from doomfire_palette import render_frame
from doomfire_terminal import TerminalController

DEFAULT_WIDTH = 80
DEFAULT_HEIGHT = 24
DEFAULT_FPS = 30
MIN_FPS = 1
MAX_FPS = 60

_NOT_A_TTY_HINT = "doomfire: interactive mode needs a TTY; run with --headless N instead"


def _positive_int(value):
    """argparse type: an integer >= 1 (field dimensions)."""
    number = _integer(value)
    if number < 1:
        raise argparse.ArgumentTypeError(f"expected an integer >= 1, got {number}")
    return number


def _nonnegative_int(value):
    """argparse type: an integer >= 0 (a frame count)."""
    number = _integer(value)
    if number < 0:
        raise argparse.ArgumentTypeError(f"expected an integer >= 0, got {number}")
    return number


def _frames_per_second(value):
    """argparse type: an integer in [MIN_FPS, MAX_FPS]."""
    number = _integer(value)
    if not MIN_FPS <= number <= MAX_FPS:
        raise argparse.ArgumentTypeError(
            f"expected an integer in [{MIN_FPS}, {MAX_FPS}], got {number}"
        )
    return number


def _integer(value):
    try:
        return int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected an integer, got {value!r}") from None


def build_parser():
    parser = argparse.ArgumentParser(
        prog="doomfire",
        description="The classic DOOM fire effect in the terminal.",
    )
    parser.add_argument(
        "--headless",
        type=_nonnegative_int,
        metavar="N",
        default=None,
        help="render N frames non-interactively (no TTY, no signals, no sleep) and exit 0",
    )
    parser.add_argument("--seed", type=int, default=0, metavar="S", help="RNG seed (default: 0)")
    parser.add_argument(
        "--width", type=_positive_int, metavar="W", default=DEFAULT_WIDTH,
        help="field width in cells (default: 80)",
    )
    parser.add_argument(
        "--height", type=_positive_int, metavar="H", default=DEFAULT_HEIGHT,
        help="field height in rows (default: 24)",
    )
    parser.add_argument(
        "--fps", type=_frames_per_second, metavar="F", default=DEFAULT_FPS,
        help=f"interactive frame cap in {MIN_FPS}..{MAX_FPS} (default: {DEFAULT_FPS})",
    )
    parser.add_argument(
        "--ascii", action="store_true",
        help="render the 1:1 ASCII ramp instead of ANSI 24-bit half-blocks",
    )
    return parser


def _render(field, ascii_mode):
    return render_frame(field, ascii=ascii_mode)


def _run_headless(args):
    """Render N frames to sys.stdout.buffer. Deterministic: the only RNG is the
    private Random(seed), so identical arguments give byte-identical output."""
    rng = random.Random(args.seed)
    field = create_field(args.width, args.height)
    seed_bottom(field, rng)
    stream = sys.stdout.buffer
    for _ in range(args.headless):
        field = step(field, rng)
        stream.write(_render(field, args.ascii).encode("utf-8"))
    stream.flush()
    return 0


def _resize_field(field, width, height, rng):
    """Rebuild the field at a new size, keeping the heat of the overlapping
    region (top-left aligned). A bottom (source) row left without heat is
    reseeded; otherwise the next step reseeds it anyway."""
    new = create_field(width, height)
    old_height, old_width = len(field), len(field[0])
    for y in range(min(old_height, height)):
        for x in range(min(old_width, width)):
            new[y][x] = field[y][x]
    if not any(new[-1]):
        seed_bottom(new, rng)
    return new


def _run_interactive(args):
    """The animated loop. Terminal setup and teardown belong to the controller
    (atexit + signal flags); this loop only polls the flags and paces frames."""
    if not sys.stdout.isatty():
        print(_NOT_A_TTY_HINT, file=sys.stderr)
        return 2

    controller = TerminalController(sys.stdout)
    controller.setup()

    rng = random.Random(args.seed)
    field = create_field(args.width, args.height)
    seed_bottom(field, rng)

    frame_interval = 1.0 / args.fps
    next_deadline = time.monotonic() + frame_interval
    while True:
        if controller.resize_requested:
            columns, lines = shutil.get_terminal_size()
            field = _resize_field(field, max(1, columns), max(1, lines), rng)
        if controller.should_exit:
            return controller.exit_code
        controller.clear_flags()
        field = step(field, rng)
        controller.present(_render(field, args.ascii))
        time.sleep(max(0.0, next_deadline - time.monotonic()))
        next_deadline += frame_interval


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.headless is not None:
        return _run_headless(args)
    return _run_interactive(args)


if __name__ == "__main__":
    sys.exit(main())
