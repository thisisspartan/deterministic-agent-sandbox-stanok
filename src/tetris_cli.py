"""tetris_cli — CLI + game loop over src/tetris_engine and src/tetris_render (CC-284).

Hybrid input (termios-raw TTY keys / line-based pipe commands), in-place
redraw under a TTY (CUP home before every frame after the first, only when
stdout.isatty()), and a bounded deterministic --ticks mode for scripted runs.
All frame output goes through run_loop(); main() only parses flags and
delegates to it.

Contract documentation: docs/tetris_cli.md.
"""
from __future__ import annotations

import argparse
import io
import os
import select
import sys
import termios
import time

try:  # package context: python -m src.tetris_cli
    from . import tetris_engine as engine
    from . import tetris_render as render
except ImportError:  # flat context: src/ on sys.path (tests)
    import tetris_engine as engine
    import tetris_render as render

HOME = "\x1b[H"  # CUP: cursor home — in-place redraw marker (TTY stdout only)

DEFAULT_SEED = 1
DEFAULT_WIDTH = 10
DEFAULT_HEIGHT = 20
DEFAULT_FPS = 2.0

QUIT = "q"
# Piped commands: a left, d right, w rotate, s soft drop, space hard drop, q quit.
# TTY keys additionally map WASD (x rotates too) and the arrow keys.
_TTY_KEY_MAP = {
    "a": "a", "d": "d", "s": "s", "w": "w", "x": "w", " ": " ",
    "q": QUIT, "\x03": QUIT,  # Ctrl-C in raw mode behaves like q
}
_TTY_ARROW_MAP = {"A": "w", "B": "s", "C": "d", "D": "a"}  # ESC [ <letter>


# ---------------------------------------------------------------- argparse

def _positive_int(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError(f"expected an integer: {value!r}") from None
    if number < 1:
        raise argparse.ArgumentTypeError(f"must be an integer >= 1: {value!r}")
    return number


def _even_int(value):
    number = _positive_int(value)
    if number % 2 != 0:
        raise argparse.ArgumentTypeError(f"must be an even integer >= 2: {value!r}")
    return number


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
        prog="tetris_cli",
        description="Tetris CLI — interactive play or a bounded scripted run (--ticks N).",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (default 1)")
    parser.add_argument("--width", type=_positive_int, default=DEFAULT_WIDTH, help="board width (default 10)")
    parser.add_argument("--height", type=_even_int, default=DEFAULT_HEIGHT, help="board height, even (default 20)")
    parser.add_argument("--fps", type=_positive_float, default=DEFAULT_FPS, help="frames per second (default 2)")
    parser.add_argument("--ticks", type=_positive_int, default=None,
                        help="bounded mode: apply all piped commands, then run exactly N gravity ticks")
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
        return lines  # interactive stdin: commands come key-by-key, not as lines
    try:
        while select.select([fd], [], [], 0.0)[0]:
            line = stdin.readline()
            if not line:
                break  # EOF
            lines.extend(line.splitlines())
    except (ValueError, OSError):
        pass
    return lines


def _enter_raw(stdin):
    """Put a TTY stdin into termios raw mode; returns a restore() or None."""
    fd = _fileno(stdin)
    if fd is None:
        return None
    try:
        old = termios.tcgetattr(fd)
        attrs = list(old)
        attrs[3] &= ~(termios.ECHO | termios.ICANON)  # lflags: no echo, no line buffering
        attrs[6][termios.VMIN] = 1
        attrs[6][termios.VTIME] = 0
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except (termios.error, ValueError, OSError):
        return None

    def restore():
        try:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        except (termios.error, ValueError, OSError):
            pass

    return restore


def _read_key_tty(stdin):
    """One key command available right now on a raw TTY, else None."""
    fd = _fileno(stdin)
    if fd is None or not select.select([fd], [], [], 0.0)[0]:
        return None
    try:
        chunk = os.read(fd, 1)
    except OSError:
        return None
    if not chunk:
        return None
    ch = chunk.decode("latin-1")
    if ch == "\x1b":
        # Arrow keys arrive as ESC [ <letter>; wait briefly for the tail.
        if not select.select([fd], [], [], 0.05)[0]:
            return None  # bare Escape: no command
        try:
            tail = os.read(fd, 2).decode("latin-1")
        except OSError:
            return None
        if len(tail) == 2 and tail[0] == "[":
            return _TTY_ARROW_MAP.get(tail[1])
        return None
    return _TTY_KEY_MAP.get(ch)


def _poll_commands(stdin, tty_mode):
    """All commands available right now; never blocks."""
    if tty_mode:
        commands = []
        while True:
            key = _read_key_tty(stdin)
            if key is None:
                return commands
            commands.append(key)
    commands = []
    for line in _drain_lines(stdin):
        for ch in line:
            if ch != "\r":
                commands.append(ch)
    return commands


# ---------------------------------------------------------------- engine glue

def _apply(state, cmd):
    """Apply one command character; unknown characters are no-ops."""
    if cmd == "a":
        moved = engine.try_move(state, -1)
    elif cmd == "d":
        moved = engine.try_move(state, 1)
    elif cmd == "w":
        moved = engine.try_rotate(state, 1)
    elif cmd == "s":
        moved = engine.soft_drop(state)
    elif cmd == " ":
        moved = engine.hard_drop(state)
    else:
        return state
    return state if moved is None else moved


def _render_frame(state) -> str:
    """Current state -> frame string via tetris_render (overlay carries piece ids)."""
    if not state.piece:
        return render.render_board(state.board)
    piece_id = state.piece_id
    overlay = tuple(tuple(piece_id if cell else 0 for cell in row) for row in state.piece)
    return render.render_board(state.board, active=(overlay, state.x, state.y))


def _emit_frame(stdout, state, home):
    """The single frame-output path. `home` inserts CUP only on a TTY stdout."""
    if home and _isatty(stdout):
        stdout.write(HOME)
    stdout.write(_render_frame(state))
    stdout.write("\n")
    stdout.flush()


# ---------------------------------------------------------------- loops

def _bounded(stdin, stdout, state, ticks) -> int:
    """--ticks N: apply all available piped commands in order (q quits
    immediately), then exactly N gravity ticks, printing a frame per tick.
    Never emits ESC[H."""
    _emit_frame(stdout, state, home=False)
    for line in _drain_lines(stdin):
        for ch in line:
            if ch == "\r":
                continue
            if ch == QUIT:
                return 0
            state = _apply(state, ch)
    for _ in range(ticks):
        state = engine.tick(state)
        _emit_frame(stdout, state, home=False)
    return 0


def _interactive(stdin, stdout, state, fps, max_frames, sleep, monotonic) -> int:
    """Period 1/fps: poll input, tick, redraw each frame. q or SIGINT -> 0.

    max_frames bounds the number of emitted frames (test hook; None = run
    until quit). The first frame is emitted without CUP; every later frame
    is preceded by CUP when — and only when — stdout is a TTY.
    """
    tty_mode = _isatty(stdin)
    restore = _enter_raw(stdin) if tty_mode else None
    try:
        _emit_frame(stdout, state, home=False)
        frames = 1
        period = 1.0 / fps
        next_t = monotonic() + period
        while max_frames is None or frames < max_frames:
            for cmd in _poll_commands(stdin, tty_mode):
                if cmd == QUIT:
                    return 0
                state = _apply(state, cmd)
            state = engine.tick(state)
            _emit_frame(stdout, state, home=True)
            frames += 1
            delay = next_t - monotonic()
            if delay > 0:
                sleep(delay)
            next_t += period
        return 0
    finally:
        if restore is not None:
            restore()


def run_loop(stdin, stdout, *, seed=DEFAULT_SEED, width=DEFAULT_WIDTH,
             height=DEFAULT_HEIGHT, fps=DEFAULT_FPS, ticks=None,
             max_frames=None, sleep=time.sleep, monotonic=time.monotonic) -> int:
    """The game loop and the ONLY frame-output path. Returns the exit code.

    ticks is not None -> bounded mode; otherwise the interactive loop.
    sleep/monotonic/max_frames are injectable for tests; production uses the
    real clock.
    """
    state = engine.new_game(seed, width, height)
    try:
        if ticks is not None:
            return _bounded(stdin, stdout, state, ticks)
        return _interactive(stdin, stdout, state, fps, max_frames, sleep, monotonic)
    except KeyboardInterrupt:
        return 0


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
        fps=args.fps, ticks=args.ticks,
    )


if __name__ == "__main__":
    sys.exit(main())
