"""galaxian_cli — terminal boundary of the Galaxian wave (CC-295).

Consumer of the pure engine (src.galaxian_engine) and renderer
(src.galaxian_render): parses CLI flags, decodes keypresses into
move/fire/quit commands, paces ticks at 1/fps, and writes frames.
Entry points: main(argv) -> int (also `python -m src.galaxian_cli` from
the repo root, and bare `import galaxian_cli` with PYTHONPATH=src);
run_loop(stdin, stdout, ...) is the ONLY place frames are written, with
keyword hooks sleep/monotonic for testability. TTY gates read isatty()
on the passed streams. See docs/galaxian_cli.md.
"""

from __future__ import annotations

import argparse
import copy
import io
import os
import select
import signal
import sys
import termios
import time

try:  # namespace-package form: `python -m src.galaxian_cli` from the repo root
    from src import galaxian_engine, galaxian_render
except ImportError:  # bare form: PYTHONPATH=src (run.sh test/smoke)
    import galaxian_engine, galaxian_render

# Defaults and validation bounds (pinned by the contract).
DEFAULT_SEED = 1
DEFAULT_WIDTH = 32
DEFAULT_HEIGHT = 24
DEFAULT_FPS = 8.0
MIN_WIDTH = 12
MIN_HEIGHT = 8

HOME = "\x1b[H"  # interactive TTY only; bounded mode NEVER emits it

# Decoded commands: (kind, payload).
_MOVE_LEFT = ("move", -1)
_MOVE_RIGHT = ("move", 1)
_FIRE = ("fire", None)
_QUIT = ("quit", None)

_KEY_COMMANDS = {
    ord("a"): _MOVE_LEFT,
    ord("d"): _MOVE_RIGHT,
    ord(" "): _FIRE,
    ord("w"): _FIRE,
    ord("q"): _QUIT,
    0x03: _QUIT,  # ^C byte
}
_ARROW_COMMANDS = {
    b"\x1b[A": _FIRE,  # up
    b"\x1b[C": _MOVE_RIGHT,  # right
    b"\x1b[D": _MOVE_LEFT,  # left
}


class _SignalQuit(Exception):
    """Raised from the SIGINT handler; unwinds the loop to rc 0."""


def parse_keys(data: bytes) -> list:
    """Decode a raw key byte string into commands, in order.

    'a'/left -> move(-1); 'd'/right -> move(+1); space, 'w', up -> fire;
    'q' and \\x03 -> quit. Arrow keys are the 3-byte CSI sequences; a lone
    ESC or an unmodelled escape is skipped byte by byte. Other bytes are
    ignored.
    """
    commands = []
    i = 0
    n = len(data)
    while i < n:
        seq = data[i : i + 3]
        if seq in _ARROW_COMMANDS:
            commands.append(_ARROW_COMMANDS[seq])
            i += 3
            continue
        command = _KEY_COMMANDS.get(data[i])
        if command is not None:
            commands.append(command)
        i += 1
    return commands


def _apply_commands(state, commands) -> tuple:
    """Apply commands in order; stop at the first quit. -> (state, quit)."""
    for command in commands:
        if command is _QUIT:
            return state, True
        if command[0] == "move":
            state = galaxian_engine.move(state, command[1])
        else:
            state = galaxian_engine.fire(state)
    return state, False


def _emit_frame(stdout, state, home: bool) -> None:
    """The single frame write: optional home, render_frame unchanged, '\\n'."""
    if home:
        stdout.write(HOME)
    stdout.write(galaxian_render.render_frame(state) + "\n")
    stdout.flush()


def _read_available(stdin) -> tuple:
    """Drain currently available bytes without blocking. -> (data, eof).

    Real fds go through select+os.read (timeout 0); a stream without a
    fileno (a test fake) is drained via read() until it returns b"".
    """
    fileno = getattr(stdin, "fileno", None)
    fd = None
    if fileno is not None:
        try:
            fd = fileno()
        except (io.UnsupportedOperation, ValueError, OSError):
            fd = None
    if fd is None:
        # Duck-typed stream (a test fake): an empty read means "nothing
        # available right now", never EOF — only real fds signal EOF.
        data = b""
        while True:
            try:
                chunk = stdin.read(1)
            except (BlockingIOError, InterruptedError, OSError):
                return data, False
            if not chunk:
                return data, False
            data += chunk
    data = b""
    while True:
        try:
            if not select.select([fd], [], [], 0)[0]:
                return data, False
            chunk = os.read(fd, 4096)
        except (BlockingIOError, InterruptedError, OSError):
            return data, False
        if not chunk:  # EOF on the stream
            return data, True
        data += chunk


def _borrow_termios(stdin):
    """Raw-mode the terminal (ICANON/ECHO off, OPOST untouched), deep-copying
    the attributes (cc list included) for restoration. -> (fd, saved) or
    (None, None) when termios is unavailable on this stream."""
    try:
        fd = stdin.fileno()
    except (AttributeError, io.UnsupportedOperation, ValueError, OSError):
        return None, None
    try:
        saved = termios.tcgetattr(fd)
    except (termios.error, OSError):
        return None, None
    raw = copy.deepcopy(saved)
    raw[3] &= ~(termios.ICANON | termios.ECHO)  # lflag only; OPOST untouched
    termios.tcsetattr(fd, termios.TCSADRAIN, raw)
    return fd, saved


def _restore_termios(fd, saved) -> None:
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, saved)
    except (termios.error, OSError):
        pass


def _run_bounded(stdin, stdout, state, ticks: int) -> int:
    """--ticks N: drain stdin non-blocking, apply commands in order; a quit
    means rc 0 with NO frames. Otherwise exactly N ticks, exactly one frame
    after each; game over -> final frame, stop. NEVER homes/clears/hides
    the cursor, even on a TTY stdout."""
    keys, _eof = _read_available(stdin)
    state, quit_now = _apply_commands(state, parse_keys(keys))
    if quit_now:
        return 0
    for _ in range(ticks):
        state = galaxian_engine.tick(state)
        _emit_frame(stdout, state, home=False)
        if galaxian_engine.is_game_over(state):
            return 0
    return 0


def _run_interactive(stdin, stdout, state, fps: float, sleep, monotonic) -> int:
    """Period 1/fps: drain all available commands, apply, tick, emit one
    frame. stdin TTY -> termios raw, restored in finally. stdout TTY ->
    every frame (including the first) prefixed with ESC[H; non-TTY -> no
    homes. q/^C/SIGINT or game over -> rc 0 (final frame emitted)."""
    stdin_tty = bool(stdin.isatty())
    fd, saved = _borrow_termios(stdin) if stdin_tty else (None, None)
    home = bool(stdout.isatty())
    period = 1.0 / fps

    def _on_sigint(signum, frame):
        raise _SignalQuit()

    previous_handler = signal.signal(signal.SIGINT, _on_sigint)
    try:
        next_at = monotonic() + period
        while True:
            now = monotonic()
            if now < next_at:
                sleep(next_at - now)
            keys, eof = _read_available(stdin)
            state, quit_now = _apply_commands(state, parse_keys(keys))
            if quit_now:
                return 0
            if eof and not stdin_tty:
                return 0  # non-TTY stdin closed: nothing left to drive
            state = galaxian_engine.tick(state)
            _emit_frame(stdout, state, home)
            if galaxian_engine.is_game_over(state):
                return 0
            next_at = monotonic() + period
    except _SignalQuit:
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_handler)
        if fd is not None:
            _restore_termios(fd, saved)


def run_loop(
    stdin,
    stdout,
    seed: int = DEFAULT_SEED,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: float = DEFAULT_FPS,
    ticks=None,
    *,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> int:
    """The single frame-output point of the CLI (the ONLY writer of frames).

    ticks is None -> interactive mode; ticks is an int -> bounded mode.
    sleep/monotonic are injectable hooks (defaults time.sleep/time.monotonic).
    TTY gates: isatty() on the passed stdin/stdout. Returns the exit code.
    """
    state = galaxian_engine.new_game(seed, width, height)
    if ticks is not None:
        return _run_bounded(stdin, stdout, state, ticks)
    return _run_interactive(stdin, stdout, state, fps, sleep, monotonic)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="galaxian_cli",
        description="Galaxian terminal CLI (engine+render boundary).",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=float, default=DEFAULT_FPS)
    parser.add_argument("--ticks", type=int, default=None)
    return parser


def _validate(args) -> str:
    if args.width < MIN_WIDTH:
        return f"width must be >= {MIN_WIDTH}, got {args.width}"
    if args.height < MIN_HEIGHT:
        return f"height must be >= {MIN_HEIGHT}, got {args.height}"
    if args.height % 2 != 0:
        return f"height must be even, got {args.height}"
    if not args.fps > 0:
        return f"fps must be > 0, got {args.fps}"
    if args.ticks is not None and args.ticks < 1:
        return f"ticks must be >= 1, got {args.ticks}"
    return ""


def main(argv) -> int:
    """Parse flags, validate, run. rc 2 on any invalid flag (stdout stays
    empty); --help -> rc 0."""
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:  # argparse: 0 for --help, 2 for a bad/unknown flag
        return 0 if exc.code in (0, None) else 2
    error = _validate(args)
    if error:
        print(f"galaxian_cli: error: {error}", file=sys.stderr)
        return 2
    return run_loop(
        sys.stdin,
        sys.stdout,
        seed=args.seed,
        width=args.width,
        height=args.height,
        fps=args.fps,
        ticks=args.ticks,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
