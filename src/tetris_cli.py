"""tetris_cli — terminal boundary of the tetris console (CC-304).

Consumer of the pure engine (src.tetris_engine) and renderer
(src.tetris_render): parses CLI flags, decodes stdin lines / TTY
keypresses into move/rotate/drop/quit commands, paces ticks at 1/fps,
and writes frames. Entry points: main(argv) -> int (also
`python -m src.tetris_cli` from the repo root, and bare `import
tetris_cli` with PYTHONPATH=src); run_loop(stdin, stdout, *, ...) is the
ONLY place frames are written, with keyword hooks sleep/monotonic for
testability. TTY gates read isatty() on the passed streams.
See docs/tetris_cli.md.
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

try:  # namespace-package form: `python -m src.tetris_cli` from the repo root
    from src import tetris_engine, tetris_render
except ImportError:  # bare form: PYTHONPATH=src (run.sh test/smoke)
    import tetris_engine, tetris_render

# Defaults and validation bounds (pinned by the contract).
DEFAULT_SEED = 1
DEFAULT_WIDTH = 10
DEFAULT_HEIGHT = 20
DEFAULT_FPS = 2.0
MIN_WIDTH = 2
MIN_HEIGHT = 2

HOME = "\x1b[H"  # interactive TTY stdout only; bounded mode NEVER emits it

# Decoded commands: (kind, payload).
_MOVE_LEFT = ("move", -1)
_MOVE_RIGHT = ("move", 1)
_ROTATE = ("rotate", 1)
_SOFT_DROP = ("soft", None)
_HARD_DROP = ("hard", None)
_QUIT = ("quit", None)

# Pipe/line commands: an exact single-character line is one command;
# every other line is junk and ignored.
_LINE_COMMANDS = {
    "a": _MOVE_LEFT,
    "d": _MOVE_RIGHT,
    "w": _ROTATE,
    "s": _SOFT_DROP,
    " ": _HARD_DROP,
    "q": _QUIT,
    "\x03": _QUIT,
}

# TTY key bytes: 3-byte CSI arrow sequences (matched before single bytes).
_ARROW_COMMANDS = {
    b"\x1b[A": _ROTATE,      # up
    b"\x1b[B": _SOFT_DROP,   # down
    b"\x1b[C": _MOVE_RIGHT,  # right
    b"\x1b[D": _MOVE_LEFT,   # left
}
_KEY_COMMANDS = {
    ord("a"): _MOVE_LEFT,
    ord("d"): _MOVE_RIGHT,
    ord("w"): _ROTATE,
    ord("s"): _SOFT_DROP,
    ord(" "): _HARD_DROP,
    ord("q"): _QUIT,
    0x03: _QUIT,  # ^C byte
}


class _SignalQuit(Exception):
    """Raised from the SIGINT/SIGTERM handlers; unwinds the loop to rc 0."""


# ---------------------------------------------------------------------------
# Command decoding
# ---------------------------------------------------------------------------

def parse_line(line: str):
    """Decode one stdin line -> a command, or None (ignored).

    Only exact single-character command lines count ('a','d','w','s',' ',
    'q', \\x03); a single trailing \\r is stripped (CRLF pipes), everything
    else is junk.
    """
    if line.endswith("\r"):
        line = line[:-1]
    return _LINE_COMMANDS.get(line)


def parse_keys(data: bytes) -> list:
    """Decode a raw key byte string into commands, in byte order.

    Arrow keys are the 3-byte CSI sequences (matched before single
    bytes); a lone ESC or an unmodelled escape is skipped byte by byte;
    other bytes are ignored.
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


def _apply_one(state, command):
    """One engine operation; a blocked move/rotate/drop (None) keeps the
    current state."""
    kind, payload = command
    if kind == "move":
        return tetris_engine.try_move(state, payload)
    if kind == "rotate":
        return tetris_engine.try_rotate(state, payload)
    if kind == "soft":
        return tetris_engine.soft_drop(state)
    if kind == "hard":
        return tetris_engine.hard_drop(state)
    return state


def _apply_commands(state, commands) -> tuple:
    """Apply commands in order. -> (state, status) with status None,
    "quit" (stop, NO frame) or "game_over" (final frame, stop)."""
    for command in commands:
        if command is _QUIT:
            return state, "quit"
        new_state = _apply_one(state, command)
        if new_state is not None:
            state = new_state
        if tetris_engine.is_game_over(state):
            return state, "game_over"
    return state, None


# ---------------------------------------------------------------------------
# Frame output (the single point where frames are written)
# ---------------------------------------------------------------------------

def _active(state):
    if state.piece is None:
        return None
    return (state.piece, state.x, state.y, state.piece_id)


def _emit_frame(stdout, state, home: bool) -> None:
    """The single frame write: optional home, render_board unchanged, '\\n'."""
    if home:
        stdout.write(HOME)
    stdout.write(tetris_render.render_board(state.board, _active(state)) + "\n")
    stdout.flush()


# ---------------------------------------------------------------------------
# Input plumbing
# ---------------------------------------------------------------------------

def _is_tty(stream) -> bool:
    try:
        return bool(stream.isatty())
    except (AttributeError, ValueError, OSError):
        return False


def _stream_fd(stdin):
    fileno = getattr(stdin, "fileno", None)
    if fileno is None:
        return None
    try:
        return fileno()
    except (io.UnsupportedOperation, ValueError, OSError):
        return None


def _read_nonblocking(fd) -> tuple:
    """Drain currently available bytes on a real fd. -> (data, eof)."""
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


def _read_bounded_input(stdin) -> str:
    """Bounded mode input. A TTY stdin is drained once, non-blocking (an
    interactive stdin has no EOF to wait for); a pipe or duck-typed
    stream is read to EOF."""
    fd = _stream_fd(stdin)
    if fd is not None and _is_tty(stdin):
        data, _eof = _read_nonblocking(fd)
        return data.decode("utf-8", "replace")
    try:
        data = stdin.read()
    except (BlockingIOError, InterruptedError, OSError, ValueError):
        return ""
    if data is None:
        return ""
    if isinstance(data, bytes):
        data = data.decode("utf-8", "replace")
    return data


def _read_available(stdin) -> tuple:
    """Interactive drain, non-blocking. -> (bytes, eof).

    Real fds: select(..., 0) + os.read (a b"" read is EOF). A stream
    without a usable fileno (a test fake) is drained via read() until an
    empty read — for a duck-typed stream an empty read IS EOF (the
    interactive pipe contract: EOF terminates the loop).
    """
    fd = _stream_fd(stdin)
    if fd is None:
        try:
            data = stdin.read()
        except (BlockingIOError, InterruptedError, OSError):
            return b"", False
        if data is None:
            return b"", False
        if isinstance(data, str):
            data = data.encode("utf-8", "replace")
        return data, data == b""
    return _read_nonblocking(fd)


def _take_complete_lines(buffer: str, flush: bool) -> tuple:
    """Split complete command lines off a pending pipe buffer; on EOF the
    remainder is treated as a final line. -> (commands, rest)."""
    lines = buffer.split("\n")
    rest = "" if flush else lines.pop()
    commands = []
    for line in lines:
        command = parse_line(line)
        if command is not None:
            commands.append(command)
    return commands, rest


# ---------------------------------------------------------------------------
# termios borrow/restore (interactive TTY stdin)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Modes
# ---------------------------------------------------------------------------

def _run_bounded(stdin, stdout, state, ticks: int) -> int:
    """--ticks N: read the stdin commands, apply in order (q -> rc 0 with
    NO frames, before any tick; game over after a command -> final frame,
    stop). Otherwise exactly N ticks, exactly one frame after each; game
    over -> final frame, stop. NEVER homes/clears/hides the cursor, even
    on a TTY stdout."""
    commands = []
    for line in _read_bounded_input(stdin).split("\n"):
        command = parse_line(line)
        if command is not None:
            commands.append(command)
    state, status = _apply_commands(state, commands)
    if status == "quit":
        return 0
    if status == "game_over":
        _emit_frame(stdout, state, home=False)
        return 0
    for _ in range(ticks):
        state = tetris_engine.tick(state)
        _emit_frame(stdout, state, home=False)
        if tetris_engine.is_game_over(state):
            return 0
    return 0


def _run_interactive(stdin, stdout, state, fps: float, sleep, monotonic) -> int:
    """Period 1/fps: drain all currently available commands, apply them,
    tick, emit one frame. stdin TTY -> termios raw, restored in finally;
    pipe stdin -> line commands, EOF ends the loop. stdout TTY -> every
    frame (including the first) prefixed with ESC[H; non-TTY -> no homes.
    q/^C/SIGINT/SIGTERM or game over -> rc 0 (final frame emitted)."""
    stdin_tty = _is_tty(stdin)
    fd, saved = _borrow_termios(stdin) if stdin_tty else (None, None)
    home = _is_tty(stdout)
    period = 1.0 / fps
    pending = ""

    def _on_signal(signum, frame):
        raise _SignalQuit()

    previous_int = signal.signal(signal.SIGINT, _on_signal)
    previous_term = signal.signal(signal.SIGTERM, _on_signal)
    try:
        next_at = monotonic() + period
        while True:
            now = monotonic()
            if now < next_at:
                sleep(next_at - now)
            data, eof = _read_available(stdin)
            if stdin_tty:
                commands = parse_keys(data)
            else:
                pending += data.decode("utf-8", "replace")
                commands, pending = _take_complete_lines(pending, eof)
            state, status = _apply_commands(state, commands)
            if status == "quit":
                return 0
            if status == "game_over":
                _emit_frame(stdout, state, home)
                return 0
            if eof and not stdin_tty:
                return 0  # non-TTY stdin closed: nothing left to drive
            state = tetris_engine.tick(state)
            _emit_frame(stdout, state, home)
            if tetris_engine.is_game_over(state):
                return 0
            next_at = monotonic() + period
    except _SignalQuit:
        return 0
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)
        if fd is not None:
            _restore_termios(fd, saved)


def run_loop(
    stdin,
    stdout,
    *,
    seed: int = DEFAULT_SEED,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    fps: float = DEFAULT_FPS,
    ticks=None,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> int:
    """The single frame-output point of the CLI (the ONLY writer of frames).

    ticks is None -> interactive mode; ticks is an int -> bounded mode.
    sleep/monotonic are injectable keyword hooks (defaults
    time.sleep/time.monotonic). TTY gates: isatty() on the passed
    stdin/stdout. Returns the exit code.
    """
    state = tetris_engine.new_game(seed, width, height)
    if ticks is not None:
        return _run_bounded(stdin, stdout, state, ticks)
    return _run_interactive(stdin, stdout, state, fps, sleep, monotonic)


# ---------------------------------------------------------------------------
# argv
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tetris_cli",
        description="Tetris terminal CLI (engine+render boundary).",
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
    """Parse flags, validate, run. rc 2 on any invalid flag (usage on
    stderr, stdout stays empty); --help -> rc 0."""
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:  # argparse: 0 for --help, 2 for a bad/unknown flag
        return 0 if exc.code in (0, None) else 2
    error = _validate(args)
    if error:
        print(parser.format_usage(), end="", file=sys.stderr)
        print(f"tetris_cli: error: {error}", file=sys.stderr)
        return 2
    try:
        return run_loop(
            sys.stdin,
            sys.stdout,
            seed=args.seed,
            width=args.width,
            height=args.height,
            fps=args.fps,
            ticks=args.ticks,
        )
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
