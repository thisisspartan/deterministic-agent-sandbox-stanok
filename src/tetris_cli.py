"""tetris_cli — the terminal boundary layer of the TETRIS3 wave (CC-292).

Consumer of tetris_engine (rules) and tetris_render (frames): the only module
in the wave that does I/O. Two modes: a bounded pipe tool (--ticks N, fully
deterministic, never homes/clears/hides the cursor) and an interactive loop
(termios raw on a TTY stdin, one frame per 1/fps period, home before every
frame on a TTY stdout). run_loop is the single frame-output point; sleep and
monotonic are injectable keyword hooks so tests run without wall-clock. The
contract is pinned in docs/tetris_cli.md.
"""

from __future__ import annotations

import copy
import os
import select
import signal
import sys
import termios
import time

try:
    # Entry point `python -m src.tetris_cli` from the repo root.
    from . import tetris_engine, tetris_render
except ImportError:
    # Entry point via the run.sh registry: PYTHONPATH=src, bare `import tetris_cli`.
    import tetris_engine
    import tetris_render

HOME = "\x1b[H"

_USAGE = (
    "usage: python -m src.tetris_cli [-h] [--seed N] [--width W] [--height H]"
    " [--fps F] [--ticks N]\n"
    "  --seed N     rng seed (default 1)\n"
    "  --width W    board width, >= 2 (default 10)\n"
    "  --height H   board height, even and >= 2 (default 20)\n"
    "  --fps F      frames per second, > 0 (default 2.0)\n"
    "  --ticks N    bounded mode: apply stdin commands, then exactly N\n"
    "               gravity ticks with one frame each, and exit\n"
)

_VALUE_FLAGS = ("--seed", "--width", "--height", "--fps", "--ticks")
_QUIT_CHARS = frozenset("q\x03")
_ARROW_KEYS = {"A": "w", "B": "s", "C": "d", "D": "a"}


# ---------------------------------------------------------------------------
# argument parsing and validation
# ---------------------------------------------------------------------------

def _parse_args(argv):
    """Return an options dict, the sentinel "help", or None for invalid input.

    Invalid: a non-numeric or out-of-range value (--height odd or < 2,
    --width < 2, --fps <= 0, --ticks < 1), an unknown flag, a missing value,
    or a positional argument.
    """
    opts = {"seed": 1, "width": 10, "height": 20, "fps": 2.0, "ticks": None}
    args = list(argv)
    i = 0
    while i < len(args):
        flag = args[i]
        if flag in ("-h", "--help"):
            return "help"
        if flag not in _VALUE_FLAGS:
            return None
        if i + 1 >= len(args):
            return None
        raw = args[i + 1]
        i += 2
        try:
            value = float(raw) if flag == "--fps" else int(raw)
        except ValueError:
            return None
        opts[flag[2:]] = value
    if opts["width"] < 2:
        return None
    if opts["height"] < 2 or opts["height"] % 2 != 0:
        return None
    if not opts["fps"] > 0.0:
        return None
    if opts["ticks"] is not None and opts["ticks"] < 1:
        return None
    return opts


# ---------------------------------------------------------------------------
# commands and frames
# ---------------------------------------------------------------------------

def _parse_commands(data):
    """Yield command characters; arrow escape sequences (ESC [ A/B/C/D) map
    to w/s/d/a. A lone or incomplete ESC is yielded as-is (and ignored)."""
    i = 0
    n = len(data)
    while i < n:
        ch = data[i]
        if ch == "\x1b" and i + 2 < n and data[i + 1] == "[" and data[i + 2] in _ARROW_KEYS:
            yield _ARROW_KEYS[data[i + 2]]
            i += 3
            continue
        yield ch
        i += 1


def _apply_command(state, ch):
    """Apply one command character; an invalid move or an unlisted character
    leaves the state unchanged."""
    if ch == "a":
        return tetris_engine.try_move(state, -1)
    if ch == "d":
        return tetris_engine.try_move(state, 1)
    if ch == "w":
        return tetris_engine.try_rotate(state, 1)
    if ch == "s":
        return tetris_engine.soft_drop(state)
    if ch == " ":
        return tetris_engine.hard_drop(state)
    return None


def _render(state):
    """The frame: render_board with the active piece overlaid in its own
    piece color (the engine's piece matrix is 0/1; the overlay carries
    piece_id)."""
    active = None
    if state.piece is not None:
        shape = [[state.piece_id if cell else 0 for cell in row] for row in state.piece]
        active = (shape, state.x, state.y)
    return tetris_render.render_board(state.board, active)


def _emit_frame(stdout, state, *, home):
    if home:
        stdout.write(HOME)
    stdout.write(_render(state) + "\n")
    stdout.flush()


# ---------------------------------------------------------------------------
# stdin reading
# ---------------------------------------------------------------------------

def _read_available(stdin):
    """Read the characters currently available on stdin without blocking.

    Returns (text, eof). eof is True only when a real file descriptor
    reports end-of-file (a read of zero bytes); duck-typed streams (no
    usable fileno) are read once and never report eof.
    """
    try:
        fd = stdin.fileno()
    except (AttributeError, ValueError, OSError):
        data = stdin.read()
        if isinstance(data, bytes):
            data = data.decode("utf-8", "replace")
        return data, False
    parts = []
    eof = False
    while select.select([fd], [], [], 0.0)[0]:
        try:
            chunk = os.read(fd, 4096)
        except (BlockingIOError, OSError):
            break
        if not chunk:
            eof = True
            break
        parts.append(chunk.decode("utf-8", "replace"))
    return "".join(parts), eof


def _read_bounded(stdin):
    """Bounded-mode stdin: a TTY is polled non-blocking (whatever is typed
    so far); a pipe/DEVNULL is read to EOF — a finite input, which is what
    makes the bounded stream deterministic."""
    if stdin.isatty():
        data, _ = _read_available(stdin)
        return data
    data = stdin.read()
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    return data


# ---------------------------------------------------------------------------
# bounded mode (--ticks N): the pipe tool
# ---------------------------------------------------------------------------

def _run_bounded(stdin, stdout, state, ticks):
    """Apply the stdin commands in order (q/\\x03 quits immediately, before
    any tick or frame), then exactly N gravity ticks with exactly one frame
    after each; stop after the tick that ends the game. Never emits
    home/clear/cursor sequences, even on a TTY stdout."""
    for ch in _parse_commands(_read_bounded(stdin)):
        if ch in _QUIT_CHARS:
            return 0
        moved = _apply_command(state, ch)
        if moved is not None:
            state = moved
    for _ in range(ticks):
        state = tetris_engine.tick(state)
        _emit_frame(stdout, state, home=False)
        if tetris_engine.is_game_over(state):
            return 0
    return 0


# ---------------------------------------------------------------------------
# interactive mode: the terminal loop
# ---------------------------------------------------------------------------

def _run_interactive(stdin, stdout, state, fps, sleep, monotonic):
    """Each period (1/fps): poll the available commands non-blocking, apply
    them, then one gravity tick and one frame. On a TTY stdout every frame,
    including the first, is prefixed with HOME; the cursor is never hidden.
    On a TTY stdin the terminal is put in raw mode (ICANON/ECHO off, OPOST
    untouched, attributes deep-copied) and restored via TCSADRAIN in finally.
    q, \\x03, SIGINT or a closed non-TTY stdin quit with rc 0; game over
    prints the final frame and exits 0."""
    period = 1.0 / fps
    saved_attrs = None
    tty_fd = None
    old_handler = None
    quit_requested = [False]

    def _request_quit(signum, frame):
        quit_requested[0] = True

    try:
        if stdin.isatty():
            tty_fd = stdin.fileno()
            saved_attrs = copy.deepcopy(termios.tcgetattr(tty_fd))
            raw_attrs = copy.deepcopy(saved_attrs)
            raw_attrs[3] &= ~(termios.ECHO | termios.ICANON)  # lflag only; OPOST untouched
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, raw_attrs)
        try:
            old_handler = signal.signal(signal.SIGINT, _request_quit)
        except ValueError:  # not the main thread: SIGINT cannot be trapped
            old_handler = None

        next_t = monotonic()
        while True:
            if quit_requested[0]:
                return 0
            data, eof = _read_available(stdin)
            for ch in _parse_commands(data):
                if ch in _QUIT_CHARS:
                    quit_requested[0] = True
                    break
                moved = _apply_command(state, ch)
                if moved is not None:
                    state = moved
            if quit_requested[0] or eof:
                return 0
            state = tetris_engine.tick(state)
            _emit_frame(stdout, state, home=stdout.isatty())
            if tetris_engine.is_game_over(state):
                return 0
            next_t += period
            delay = next_t - monotonic()
            if delay > 0:
                sleep(delay)
    except KeyboardInterrupt:
        return 0
    finally:
        if old_handler is not None:
            signal.signal(signal.SIGINT, old_handler)
        if saved_attrs is not None:
            termios.tcsetattr(tty_fd, termios.TCSADRAIN, saved_attrs)


# ---------------------------------------------------------------------------
# public API (names pinned by the contract)
# ---------------------------------------------------------------------------

def run_loop(stdin, stdout, *, seed=1, width=10, height=20, fps=2.0, ticks=None,
             sleep=time.sleep, monotonic=time.monotonic) -> int:
    """Run the game on the given streams; the single frame-output point.

    ticks is None: interactive mode; ticks >= 1: bounded mode. The TTY gates
    call isatty() on the passed objects. sleep/monotonic are keyword hooks
    (default time.sleep/time.monotonic) so tests run without wall-clock.
    Returns the process exit code (0 on quit/game over).
    """
    state = tetris_engine.new_game(seed, width, height)
    if ticks is not None:
        return _run_bounded(stdin, stdout, state, ticks)
    return _run_interactive(stdin, stdout, state, fps, sleep, monotonic)


def main(argv) -> int:
    """Parse argv and run the game on sys.stdin/sys.stdout. Invalid flags or
    values: usage on stderr, rc 2, no frame bytes on stdout. --help: rc 0."""
    opts = _parse_args(argv)
    if opts is None:
        sys.stderr.write(_USAGE)
        return 2
    if opts == "help":
        sys.stdout.write(_USAGE)
        return 0
    return run_loop(sys.stdin, sys.stdout, **opts)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
