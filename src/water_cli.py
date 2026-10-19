"""water_cli — terminal boundary of the water surface (CC-301).

Consumer of the pure engine (src.water_engine) and renderer
(src.water_render): parses CLI flags, then writes frames in one of two
modes chosen by isatty() on the passed stdout — pipe mode (the render bytes
only) or TTY mode (alt-buffer + hidden cursor + per-frame home, fixed
timestep pacing, teardown exactly once on every exit path). Entry points:
main(argv) -> int and run_loop(stdin, stdout, ...) — the ONLY place frames
are written, with keyword hooks sleep/monotonic for testability.
_SignalQuit unwinds the frame loop to rc 0. stdlib only.
See docs/water_cli.md.
"""

from __future__ import annotations

import argparse
import os
import signal
import sys
import time

try:  # namespace-package form: `python -m src.water_cli` from the repo root
    from src import water_engine, water_render
except ImportError:  # bare form: PYTHONPATH=src (run.sh test/smoke)
    import water_engine, water_render

# Defaults and validation bounds (pinned by the contract, C1).
DEFAULT_SEED = 1
DEFAULT_HEIGHT = 24
DEFAULT_FPS = 24.0
FALLBACK_WIDTH = 80
MIN_WIDTH = 12
MAX_WIDTH = 200
MIN_HEIGHT = 4
MAX_HEIGHT = 60
MIN_SEED = 0
MIN_FRAMES = 1
MIN_FPS = 1.0
MAX_FPS = 60.0

# Alt-buffer / cursor protocol (C3): opened once at the start, closed once
# at the end — on EVERY exit path, including a signal.
ENTER_ALT = "\x1b[?1049h"
HIDE_CURSOR = "\x1b[?25l"
HOME = "\x1b[H"  # frame prefix, TTY mode only
EXIT_ALT = "\x1b[?1049l"
SHOW_CURSOR = "\x1b[?25h"

NO_TTY_MESSAGE = "water: no terminal and no --frames"  # C5 host literal
RC_NO_TERMINAL = 3


class _SignalQuit(Exception):
    """Raised from the SIGINT/SIGTERM handler; unwinds the loop to rc 0."""


def _terminal_width() -> int:
    """Default width: the terminal's columns, else FALLBACK_WIDTH."""
    for stream in (sys.stdout, sys.stderr):
        try:
            return os.get_terminal_size(stream.fileno()).columns
        except (AttributeError, ValueError, OSError):
            continue
    return FALLBACK_WIDTH


def _bounded_int(low: int, high: int, name: str):
    """argparse type: integer in [low, high], else a usage error (rc 2)."""

    def parse(raw: str) -> int:
        try:
            value = int(raw)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{name} must be an integer in {low}..{high}, got {raw!r}"
            )
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(
                f"{name} must be in {low}..{high}, got {value}"
            )
        return value

    return parse


def _bounded_float(low: float, high: float, name: str):
    """argparse type: number in [low, high], else a usage error (rc 2)."""

    def parse(raw: str) -> float:
        try:
            value = float(raw)
        except ValueError:
            raise argparse.ArgumentTypeError(
                f"{name} must be a number in {low}..{high}, got {raw!r}"
            )
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(
                f"{name} must be in {low}..{high}, got {value}"
            )
        return value

    return parse


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="water_cli",
        description="Water surface terminal CLI (engine+render boundary).",
    )
    parser.add_argument("--width", type=_bounded_int(MIN_WIDTH, MAX_WIDTH, "width"),
                        default=_terminal_width(), help=f"columns ({MIN_WIDTH}..{MAX_WIDTH})")
    parser.add_argument("--height", type=_bounded_int(MIN_HEIGHT, MAX_HEIGHT, "height"),
                        default=DEFAULT_HEIGHT, help=f"rows ({MIN_HEIGHT}..{MAX_HEIGHT})")
    parser.add_argument("--seed", type=_bounded_int(MIN_SEED, 2 ** 63 - 1, "seed"),
                        default=DEFAULT_SEED, help="engine seed (>= 0)")
    parser.add_argument("--frames", type=_bounded_int(MIN_FRAMES, 10 ** 9, "frames"),
                        default=None, help="frame count (pipe-mode requires it)")
    parser.add_argument("--fps", type=_bounded_float(MIN_FPS, MAX_FPS, "fps"),
                        default=DEFAULT_FPS, help=f"frame rate ({MIN_FPS:g}..{MAX_FPS:g})")
    return parser


def _render_frame(params, t: int, width: int, height: int) -> str:
    """The one frame write source: render_frame of the engine's state."""
    return water_render.render_frame(
        water_engine.frame_state(params, t, width), width, height
    )


def _run_pipe(stdout, *, seed, width, height, frames) -> int:
    """Pipe mode (C2): exactly `frames` render frames, one print per frame
    ('\\n' per frame), nothing else — no alt-buffer, no cursor codes, no
    homes. Identical argv -> identical bytes. frames None here is the C5
    situation (no terminal, no frame count) -> rc 3."""
    if frames is None:
        return RC_NO_TERMINAL
    params = water_engine.make_params(seed)
    for t in range(frames):
        stdout.write(_render_frame(params, t, width, height) + "\n")
    stdout.flush()
    return 0


def _install_signal_handlers() -> dict:
    """SIGINT/SIGTERM -> raise _SignalQuit in the main thread. -> {sig: old}."""

    def _handler(signum, frame):
        raise _SignalQuit()

    installed = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            installed[sig] = signal.signal(sig, _handler)
        except (ValueError, OSError, RuntimeError):
            pass  # not the main thread, or the signal is uncatchable here
    return installed


def _run_tty(stdin, stdout, *, seed, width, height, frames, fps, sleep, monotonic) -> int:
    """TTY mode (C3/C4): alt-buffer + hidden cursor opened exactly once at
    the start, every frame (including the first) prefixed with home, fixed
    timestep 1/fps pacing via the injected clock, and teardown (alt-buffer
    close + cursor show) exactly once on every exit path — normal, by
    --frames, or by signal. frames None -> until _SignalQuit."""
    params = water_engine.make_params(seed)
    handlers = _install_signal_handlers()
    opened = False
    try:
        stdout.write(ENTER_ALT + HIDE_CURSOR)
        stdout.flush()
        opened = True
        period = 1.0 / fps
        next_at = monotonic()
        t = 0
        while True:
            stdout.write(HOME + _render_frame(params, t, width, height))
            stdout.flush()
            t += 1
            if frames is not None and t >= frames:
                break
            next_at += period
            delay = next_at - monotonic()
            if delay > 0.0:
                sleep(delay)
    except _SignalQuit:
        pass  # C4: the teardown below runs exactly once, rc 0
    finally:
        if opened:
            stdout.write(EXIT_ALT + SHOW_CURSOR)
            stdout.flush()
        for sig, previous in handlers.items():
            try:
                signal.signal(sig, previous)
            except (ValueError, OSError, RuntimeError):
                pass
    return 0


def run_loop(
    stdin,
    stdout,
    *,
    seed: int,
    width: int,
    height: int,
    frames,
    fps: float,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> int:
    """The single frame-output point of the CLI (the ONLY writer of frames).

    frames: int >= 1 (exactly N frames) or None (until _SignalQuit).
    The mode gate is isatty() on the passed stdout — never on process
    globals. sleep/monotonic are injectable keyword hooks. Returns rc.
    """
    if stdout.isatty():
        return _run_tty(stdin, stdout, seed=seed, width=width, height=height,
                        frames=frames, fps=fps, sleep=sleep, monotonic=monotonic)
    return _run_pipe(stdout, seed=seed, width=width, height=height, frames=frames)


def main(argv) -> int:
    """Parse and validate flags, then run. rc 2 on any invalid/unknown flag
    (argparse usage on stderr, stdout stays empty); --help -> rc 0;
    no terminal and no --frames -> rc 3 (C5)."""
    parser = _build_parser()
    try:
        args = parser.parse_args(list(argv))
    except SystemExit as exc:  # argparse: 0 for --help, 2 for a bad/unknown flag
        return 0 if exc.code in (0, None) else 2
    if not sys.stdout.isatty() and args.frames is None:
        print(NO_TTY_MESSAGE, file=sys.stderr)
        return RC_NO_TERMINAL
    return run_loop(
        sys.stdin,
        sys.stdout,
        seed=args.seed,
        width=args.width,
        height=args.height,
        frames=args.frames,
        fps=args.fps,
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
