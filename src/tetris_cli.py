"""CC-279 — tetris_cli: the CLI + interactive loop over the engine and renderer.

Wraps the public API of src/tetris_engine (pure game state) and
src/tetris_render (pure frame renderer). This module owns all I/O: argument
parsing, hybrid input (a raw terminal on a TTY, command lines on a pipe),
frame output and the tick pacing. It adds no game logic of its own.

Module contract: see docs/tetris_cli.md.
"""

from __future__ import annotations

import argparse
import os
import select
import signal
import sys
import time
from typing import IO, Any, List, Optional, Sequence, Tuple

try:  # package form: python -m src.tetris_cli
    from . import tetris_engine as engine
    from . import tetris_render as render
except ImportError:  # flat form: src/ on sys.path (pytest pythonpath=src)
    import tetris_engine as engine  # type: ignore[no-redef]
    import tetris_render as render  # type: ignore[no-redef]

try:
    import termios
except ImportError:  # pragma: no cover - non-POSIX
    termios = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Pinned constants
# ---------------------------------------------------------------------------

DEFAULT_SEED = 1
DEFAULT_FPS = 2.0

# Actions the two input sources can request.
LEFT, RIGHT, ROTATE, SOFT, HARD, QUIT = "left", "right", "rotate", "soft", "hard", "quit"

# Piped stdin: one command character per line (a line may hold several).
PIPE_COMMANDS = {
    "a": LEFT,
    "d": RIGHT,
    "w": ROTATE,
    "s": SOFT,
    " ": HARD,
    "q": QUIT,
}

# Raw terminal keys: WASD/X + Space + q (arrows are decoded separately).
KEY_COMMANDS = {
    "a": LEFT,
    "d": RIGHT,
    "s": SOFT,
    "w": ROTATE,
    "x": ROTATE,
    " ": HARD,
    "q": QUIT,
}

# Terminal control sequences -> action.
ARROW_COMMANDS = {b"[A": ROTATE, b"[B": SOFT, b"[C": RIGHT, b"[D": LEFT}

READ_CHUNK = 4096
MAX_INPUT_BYTES = 1 << 20  # safety cap for one non-blocking read burst
INPUT_GRACE = 0.05  # bounded mode: at most this long for the first piped byte

EXIT_OK = 0
EXIT_USAGE = 2


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tetris_cli",
        description="Play tetris in the terminal (truecolor half-block frames).",
    )
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed (default 1)")
    parser.add_argument(
        "--width", type=int, default=engine.DEFAULT_WIDTH, help="field width (default 10)"
    )
    parser.add_argument(
        "--height",
        type=int,
        default=engine.DEFAULT_HEIGHT,
        help="field height, must be a positive EVEN number (default 20)",
    )
    parser.add_argument(
        "--fps", type=float, default=DEFAULT_FPS, help="ticks per second (default 2)"
    )
    parser.add_argument(
        "--ticks",
        type=int,
        default=None,
        metavar="N",
        help="bounded deterministic mode: N gravity ticks (N >= 1), no interactive loop",
    )
    return parser


def _valid(args: argparse.Namespace) -> bool:
    """Flag-value validation: everything outside these bounds is a usage error."""
    if args.width < 1:
        return False
    if args.height < 2 or args.height % 2 != 0:
        return False
    fps = args.fps
    if not isinstance(fps, float) or not (fps > 0.0) or fps != fps or fps == float("inf"):
        return False
    if args.ticks is not None and args.ticks < 1:
        return False
    return True


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def _frame(state: engine.GameState) -> str:
    """Render one frame of the state (the active piece is overlaid unless the
    game is over)."""
    active = None
    if not engine.is_game_over(state):
        active = (state.piece_matrix, state.x, state.y)
    return render.render_board(state.board, active=active)


# Cursor home (CUP ESC[H): moves the cursor to the top-left of the screen.
# Emitted before every interactive frame after the first, so the frame is
# redrawn over the previous one and the screen never scrolls (CC-281).
CURSOR_HOME = "\x1b[H"


def _is_tty(stream: IO[str]) -> bool:
    """True when the stream is a real terminal — the only output for which
    in-place redraw applies (CC-281). Any failure to ask (closed stream, no
    fileno) counts as 'not a terminal'."""
    try:
        return bool(stream.isatty())
    except Exception:
        return False


def _emit(out: IO[str], state: engine.GameState, home: bool = False) -> None:
    """Write one frame plus a newline; fall back to raw UTF-8 bytes when the
    text stream cannot encode the half-block glyph. `home` prefixes the CUP
    sequence so the frame overwrites the previous one in place instead of
    scrolling the screen down — used only on a TTY in interactive mode
    (CC-281); pipe output stays byte-identical."""
    text = _frame(state) + "\n"
    if home:
        text = CURSOR_HOME + text
    try:
        out.write(text)
        out.flush()
    except UnicodeEncodeError:  # pragma: no cover - non-UTF-8 stdout
        buffer = getattr(out, "buffer", None)
        if buffer is None:
            raise
        buffer.write(text.encode("utf-8"))
        buffer.flush()


# ---------------------------------------------------------------------------
# Input: piped command lines (non-blocking)
# ---------------------------------------------------------------------------

def _read_available(stdin: IO[str], grace: float = 0.0) -> Tuple[List[str], bool]:
    """Read every line currently available on stdin WITHOUT blocking on the
    absence of input. Returns (lines, eof): eof is True only when the stream
    really ended. Any I/O problem (closed stdin, no fileno — e.g. a captured
    pytest stdin) is treated as end of input.

    `grace` is an optional upper bound on the wait for the FIRST chunk: it
    keeps a pipe whose writer starts a moment later from being mistaken for
    "no input" (0 = strictly non-blocking).
    """
    try:
        fd = stdin.fileno()
    except Exception:
        return [], True
    data = b""
    eof = False
    first = True
    while True:
        timeout = grace if first else 0.0
        first = False
        try:
            ready, _, _ = select.select([fd], [], [], timeout)
        except Exception:
            break
        if not ready:
            break
        try:
            chunk = os.read(fd, READ_CHUNK)
        except Exception:
            break
        if not chunk:  # EOF
            eof = True
            break
        data += chunk
        if len(data) >= MAX_INPUT_BYTES:
            break
    return data.decode("utf-8", "replace").splitlines(), eof


def _actions_from_line(line: str) -> List[str]:
    """Map one piped line to actions; unknown characters are ignored."""
    actions = []
    for ch in line:
        action = PIPE_COMMANDS.get(ch)
        if action is not None:
            actions.append(action)
    return actions


# ---------------------------------------------------------------------------
# Input: raw terminal keys
# ---------------------------------------------------------------------------

def _raw_attrs(attrs: List[Any]) -> List[Any]:
    """Raw-mode attributes for INPUT (tty.setraw equivalent, non-blocking
    reads). OPOST stays ON: frames are emitted with bare LF and the tty must
    keep translating LF->CRLF, otherwise every line starts one column further
    than the previous one (a staircase under a real terminal). cc is copied
    before mutation: the caller keeps `attrs` as the restore state, and a
    shallow copy would let VMIN=0/VTIME=0 leak into it (CC-280)."""
    iflag, oflag, cflag, lflag, ispeed, ospeed, cc = list(attrs)
    cc = list(cc)
    iflag &= ~(
        termios.IGNBRK
        | termios.BRKINT
        | termios.PARMRK
        | termios.ISTRIP
        | termios.INLCR
        | termios.IGNCR
        | termios.ICRNL
        | termios.IXON
    )
    lflag &= ~(termios.ECHO | termios.ECHONL | termios.ICANON | termios.ISIG | termios.IEXTEN)
    cflag &= ~(termios.CSIZE | termios.PARENB)
    cflag |= termios.CS8
    cc[termios.VMIN] = 0
    cc[termios.VTIME] = 0
    return [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]


def _enter_raw(stdin: IO[str]) -> Optional[Tuple[int, List[Any]]]:
    """Put a TTY stdin into raw mode; returns (fd, saved_attrs) or None when
    the input is not a raw-capable terminal."""
    if termios is None:
        return None
    try:
        fd = stdin.fileno()
        saved = termios.tcgetattr(fd)
        termios.tcsetattr(fd, termios.TCSADRAIN, _raw_attrs(saved))
    except Exception:
        return None
    return fd, saved


def _exit_raw(saved: Optional[Tuple[int, List[Any]]]) -> None:
    if saved is None:
        return
    fd, attrs = saved
    try:
        termios.tcsetattr(fd, termios.TCSADRAIN, attrs)
    except Exception:
        pass


def _poll_keys(fd: int, timeout: float) -> bytes:
    """Read the bytes the user has typed, waiting at most `timeout` seconds."""
    data = b""
    deadline = time.monotonic() + max(0.0, timeout)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return data
        try:
            ready, _, _ = select.select([fd], [], [], remaining)
        except Exception:
            return data
        if not ready:
            return data
        try:
            chunk = os.read(fd, 1)
        except Exception:
            return data
        if not chunk:  # stdin closed
            return data + b"q"
        data += chunk


def _actions_from_keys(data: bytes) -> List[str]:
    """Decode raw-terminal bytes into actions (arrows, WASD/X, Space, q, Ctrl-C)."""
    actions: List[str] = []
    i = 0
    while i < len(data):
        byte = data[i : i + 1]
        if byte == b"\x1b":
            sequence = data[i + 1 : i + 3]
            action = ARROW_COMMANDS.get(sequence)
            if action is None:
                i += 1  # a lone escape: ignore it
                continue
            actions.append(action)
            i += 3
            continue
        if byte == b"\x03":  # Ctrl-C in raw mode (ISIG is off)
            actions.append(QUIT)
            return actions
        action = KEY_COMMANDS.get(byte.decode("utf-8", "replace"))
        if action is not None:
            actions.append(action)
            if action == QUIT:
                return actions
        i += 1
    return actions


# ---------------------------------------------------------------------------
# Applying actions to the engine state
# ---------------------------------------------------------------------------

def _apply(state: engine.GameState, action: str) -> engine.GameState:
    """One action -> the next state. An impossible move leaves the state unchanged."""
    if action == LEFT:
        moved = engine.try_move(state, -1)
    elif action == RIGHT:
        moved = engine.try_move(state, 1)
    elif action == ROTATE:
        moved = engine.try_rotate(state, 1)
    elif action == SOFT:
        return engine.soft_drop(state)
    elif action == HARD:
        return engine.hard_drop(state)
    else:
        return state
    return state if moved is None else moved


# ---------------------------------------------------------------------------
# Bounded mode: --ticks N
# ---------------------------------------------------------------------------

def _run_bounded(
    state: engine.GameState, ticks: int, fps: float, stdin: IO[str], out: IO[str]
) -> int:
    """Read every available command line (never blocking on the absence of
    input), apply them in order, then run exactly N gravity ticks paced at
    1/fps, printing a frame per tick — the last one is the final frame.
    `q` stops the run immediately: the current frame is printed, the ticks
    are skipped, rc 0."""
    lines, _eof = _read_available(stdin, grace=INPUT_GRACE)
    for line in lines:
        for action in _actions_from_line(line):
            if action == QUIT:
                _emit(out, state)
                return EXIT_OK
            state = _apply(state, action)

    period = 1.0 / fps
    for _ in range(ticks):
        time.sleep(period)
        state = engine.tick(state)
        _emit(out, state)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Interactive mode: paced loop until q / SIGINT
# ---------------------------------------------------------------------------

def _run_interactive(state: engine.GameState, fps: float, stdin: IO[str], out: IO[str]) -> int:
    """Redraw every 1/fps seconds. Input is hybrid: raw terminal keys on a
    TTY, command lines on a pipe. q, Ctrl-C, SIGINT or the end of piped
    input end the run cleanly with rc 0.

    On a real terminal (stdout is a tty) every frame after the first is
    preceded by the CUP home sequence: the frame is redrawn in place and the
    screen never scrolls (CC-281). On a pipe the output stays a plain stream
    of frames, byte-identical to before."""
    stop = {"quit": False}

    def _on_signal(signum: int, frame: Any) -> None:
        stop["quit"] = True

    previous = signal.signal(signal.SIGINT, _on_signal)
    raw = _enter_raw(stdin)
    redraw_in_place = _is_tty(out)
    period = 1.0 / fps
    try:
        _emit(out, state)
        while not stop["quit"]:
            deadline = time.monotonic() + period
            if raw is not None:
                fd, _saved = raw
                actions = _actions_from_keys(_poll_keys(fd, period))
                eof = False
            else:
                lines, eof = _read_available(stdin)
                actions = [a for line in lines for a in _actions_from_line(line)]
            if QUIT in actions:
                break
            for action in actions:
                state = _apply(state, action)
            if eof:  # piped input exhausted: nothing more can be typed
                break
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(remaining)
            if stop["quit"]:
                break
            state = engine.tick(state)
            _emit(out, state, home=redraw_in_place)
    except KeyboardInterrupt:
        return EXIT_OK
    finally:
        _exit_raw(raw)
        signal.signal(signal.SIGINT, previous)
    return EXIT_OK


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point: returns the process exit code (never raises SystemExit).

    rc 0 — the game ran (or --help); rc 2 — unknown flag, invalid value or an
    odd --height.
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:  # argparse: --help -> 0, usage error -> 2
        code = exc.code
        return EXIT_OK if code in (0, None) else EXIT_USAGE

    if not _valid(args):
        sys.stderr.write("tetris_cli: invalid flag value (see --help)\n")
        return EXIT_USAGE

    state = engine.new_game(args.seed, args.width, args.height)
    try:
        if args.ticks is not None:
            return _run_bounded(state, args.ticks, args.fps, sys.stdin, sys.stdout)
        return _run_interactive(state, args.fps, sys.stdin, sys.stdout)
    except KeyboardInterrupt:
        return EXIT_OK
    except BrokenPipeError:  # stdout closed by the consumer
        return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
