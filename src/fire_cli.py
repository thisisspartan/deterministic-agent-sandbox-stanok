"""fire_cli — CLI flame animation over src/fire_engine and src/fire_render (CC-289).

In-place animation under a TTY (hide cursor, cbreak stdin, CUP home before
EVERY frame including the first, restore everything at any exit), a bounded
deterministic --frames mode for scripted runs, non-blocking input polling
(q quits, SIGINT exits cleanly). All frame output goes through run_loop();
main() only parses flags and delegates to it.

Contract documentation: docs/fire_cli.md.
"""
from __future__ import annotations

import argparse
import io
import os
import select
import signal
import sys
import termios
import time
import tty

try:  # package context: python -m src.fire_cli
    from . import fire_engine as engine
    from . import fire_render as render
except ImportError:  # flat context: src/ on sys.path (tests)
    import fire_engine as engine
    import fire_render as render

HOME = "\x1b[H"  # CUP: cursor home — in-place redraw marker (TTY stdout only)
HIDE_CURSOR = "\x1b[?25l"  # DEC private mode: hide cursor (TTY segment start)
SHOW_CURSOR = "\x1b[?25h"  # DEC private mode: show cursor (TTY segment end)

DEFAULT_SEED = 1
DEFAULT_WIDTH = 40
DEFAULT_HEIGHT = 12
DEFAULT_FPS = 15.0

QUIT = "q"
# Inter-frame sleep is taken in small steps, polling input between them, so
# a typed 'q' is seen well within 0.5 s even at a low fps.
_POLL_STEP = 0.05


# ---------------------------------------------------------------- argparse

def _int_at_least(value, low, label):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected an integer: {value!r}") from None
    if number < low:
        raise argparse.ArgumentTypeError(f"must be an integer >= {low}: {value!r}")
    return number


def _dimension(value):
    return _int_at_least(value, 2, "dimension")


def _frames_count(value):
    return _int_at_least(value, 1, "frame count")


def _positive_float(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected a number: {value!r}") from None
    if not number > 0:
        raise argparse.ArgumentTypeError(f"must be > 0: {value!r}")
    return number


def _build_parser():
    parser = argparse.ArgumentParser(
        prog="fire_cli",
        description="Fire CLI — animated flame (in place under a TTY) or a "
                    "bounded deterministic run (--frames N).",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED,
                        help="RNG seed (default 1)")
    parser.add_argument("--width", type=_dimension, default=DEFAULT_WIDTH,
                        help="grid width, >= 2 (default 40)")
    parser.add_argument("--height", type=_dimension, default=DEFAULT_HEIGHT,
                        help="grid height, >= 2 (default 12)")
    parser.add_argument("--fps", type=_positive_float, default=DEFAULT_FPS,
                        help="frames per second, > 0 (default 15)")
    parser.add_argument("--frames", type=_frames_count, default=None,
                        help="bounded mode: emit exactly N frames (N >= 1) and exit")
    return parser


# ---------------------------------------------------------------- streams

def _isatty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _fileno(stream):
    try:
        return stream.fileno()
    except (AttributeError, io.UnsupportedOperation, ValueError, OSError):
        return None


def _drain_lines(stdin):
    """Every line currently available on stdin; never blocks on absent input."""
    lines = []
    fd = _fileno(stdin)
    if fd is None:
        # In-memory stream (tests): drain whatever it holds.
        try:
            data = stdin.read()
        except (ValueError, OSError, EOFError):
            return lines
        if data:
            lines.extend(data.splitlines())
        return lines
    if _isatty(stdin):
        return lines  # interactive stdin: keys come one by one, not as lines
    try:
        while select.select([fd], [], [], 0.0)[0]:
            line = stdin.readline()
            if not line:
                break  # EOF (e.g. /dev/null): no input, not an error
            lines.extend(line.splitlines())
    except (ValueError, OSError):
        pass
    return lines


# ---------------------------------------------------------------- TTY segment

def _enter_terminal(stdin, stdout):
    """Start the isatty segment: hide the cursor, save termios and enter
    cbreak on a TTY stdin (ISIG is preserved). Returns a restore() that
    re-applies the saved termios and shows the cursor — safe to call at
    any exit."""
    try:
        stdout.write(HIDE_CURSOR)
        stdout.flush()
    except (OSError, ValueError):
        pass

    fd = _fileno(stdin)
    old = None
    if fd is not None and _isatty(stdin):
        try:
            old = termios.tcgetattr(fd)
            tty.setcbreak(fd)
        except (termios.error, ValueError, OSError):
            old = None

    def restore():
        if old is not None:
            try:
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
            except (termios.error, ValueError, OSError):
                pass
        try:
            stdout.write(SHOW_CURSOR)
            stdout.flush()
        except (OSError, ValueError):
            pass

    return restore


# ---------------------------------------------------------------- input polling

def _key_quit_tty(stdin) -> bool:
    """Consume available keys on a cbreak TTY; True if 'q' among them."""
    fd = _fileno(stdin)
    if fd is None:
        return False
    while True:
        try:
            if not select.select([fd], [], [], 0.0)[0]:
                return False
            chunk = os.read(fd, 1)
        except OSError:
            return False
        if not chunk:
            return False  # EOF
        if chunk == b"q":
            return True


def _poll_quit(stdin, tty_mode) -> bool:
    """Is 'q' available right now? Never blocks; other input is ignored."""
    if tty_mode:
        return _key_quit_tty(stdin)
    for line in _drain_lines(stdin):
        if QUIT in line:
            return True
    return False


# ---------------------------------------------------------------- SIGINT

def _install_sigint(stop):
    """Replace the SIGINT handler with a flag-setter (clean exit, no
    exception mid-frame). Returns the previous handler, or None."""
    def handler(signum, frame):
        stop["quit"] = True

    try:
        return signal.signal(signal.SIGINT, handler)
    except (ValueError, OSError):  # not the main thread, or unsupported
        return None


# ---------------------------------------------------------------- loop

def _emit_frame(stdout, grid, home):
    """The single frame-output path: render the grid, write, flush.
    `home` inserts CUP only in the TTY segment (before EVERY frame)."""
    if home:
        stdout.write(HOME)
    stdout.write(render.render(grid))
    stdout.write("\n")
    stdout.flush()


def _run_frames(stdin, stdout, sim, frames, fps, terminal_mode, tty_stdin,
                stop, sleep, monotonic) -> int:
    """Emit frames at a 1/fps cadence: step, render, flush; poll input in
    small steps between frames. frames=None -> until quit (interactive)."""
    period = 1.0 / fps
    emitted = 0
    while True:
        if stop["quit"]:
            return 0
        if frames is not None and emitted >= frames:
            return 0
        sim.step()
        _emit_frame(stdout, sim.grid, home=terminal_mode)
        emitted += 1
        if frames is not None and emitted >= frames:
            return 0
        deadline = monotonic() + period
        while True:
            if _poll_quit(stdin, tty_stdin) or stop["quit"]:
                return 0
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(_POLL_STEP, remaining))


def run_loop(stdin, stdout, *, seed=DEFAULT_SEED, width=DEFAULT_WIDTH,
             height=DEFAULT_HEIGHT, fps=DEFAULT_FPS, frames=None,
             sleep=time.sleep, monotonic=time.monotonic) -> int:
    """The flame loop and the ONLY frame-output path. Returns the exit code.

    frames is not None -> bounded mode (exactly N frames); None -> the
    interactive loop until q or SIGINT. When stdout.isatty() the full TTY
    segment runs in BOTH modes: hide cursor + cbreak stdin at start, CUP
    before every frame including the first, termios restore + show cursor
    at every exit (success, q, SIGINT, error). Outside a TTY none of it
    appears and termios is untouched. sleep/monotonic are injectable
    clocks — test hooks; production uses the real clock.
    """
    sim = engine.FireEngine(seed, width, height)
    terminal_mode = _isatty(stdout)
    tty_stdin = _isatty(stdin)
    stop = {"quit": False}
    restore = _enter_terminal(stdin, stdout) if terminal_mode else None
    previous_handler = _install_sigint(stop)
    try:
        return _run_frames(stdin, stdout, sim, frames, fps,
                          terminal_mode, tty_stdin, stop, sleep, monotonic)
    except KeyboardInterrupt:  # SIGINT raced the handler install
        return 0
    finally:
        if previous_handler is not None:
            try:
                signal.signal(signal.SIGINT, previous_handler)
            except (ValueError, OSError):
                pass
        if restore is not None:
            restore()


# ---------------------------------------------------------------- entry point

def main(argv=None) -> int:
    """Parse flags and delegate everything to run_loop(). Returns the exit code."""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # --help -> 0; usage/value errors -> 2
        return 0 if exc.code in (0, None) else 2
    return run_loop(
        sys.stdin, sys.stdout,
        seed=args.seed, width=args.width, height=args.height,
        fps=args.fps, frames=args.frames,
    )


if __name__ == "__main__":
    sys.exit(main())
