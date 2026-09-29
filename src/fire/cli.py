"""Terminal CLI for the TrueColor fire (TASK-FIRE-05).

Raw ANSI terminal control, no third-party libraries:

- entry: alternate screen (``\\033[?1049h``) + hidden cursor (``\\033[?25l``);
- exit (``Ctrl+C`` or ``q``): normal screen (``\\033[?1049l``), visible
  cursor (``\\033[?25h``), color reset (``\\033[0m``);
- ``signal.SIGWINCH``: the simulator and its buffer are recreated for the
  new terminal size (``shutil.get_terminal_size``);
- frame pacing: ``time.perf_counter`` +
  ``time.sleep(max(0, frame_time - elapsed))``.

CLI arguments (``argparse``):

- ``--fps``: target frames per second, ``1..60`` (default ``30``);
- ``--palette``: ``fire`` or ``blue`` (default ``fire``);
- ``--wind``: static wind ``-3..3`` or ``auto`` (default ``auto``);
- ``--seed``: PRNG seed for the simulator (deterministic frames);
- ``--width`` / ``--height``: override the terminal size (``>= 1``);
- ``--frame N``: render exactly frame N and exit (``>= 0``);
- ``--frames N``: render N frames (0..N-1) and exit (``>= 0``);
  ``--frame`` and ``--frames`` are mutually exclusive.

Headless entry point (TASK-FIRE-09): ``main(argv=None, stream=None)``
parses the CLI, renders deterministically and returns the exit code.
Without ``--frame``/``--frames`` and with a non-TTY stdin exactly one
frame (frame 0) is written to the stream; on a TTY the interactive
animation runs. ``python3 -m fire`` is supported via ``fire/__main__.py``.
"""

from __future__ import annotations

import argparse
import os
import random
import select
import signal
import sys
import termios
import time
import tty
from shutil import get_terminal_size
from typing import List, Optional, Union

# Make the ``fire`` package importable both when this module is imported as
# ``fire.cli`` (``src`` on ``sys.path``) and when the file is executed
# directly (``python3 src/fire/cli.py`` puts ``src/fire`` on ``sys.path``).
_SRC_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SRC_ROOT not in sys.path:
    sys.path.insert(0, _SRC_ROOT)

from fire.palette import generate_blue_fire_palette, generate_fire_palette
from fire.renderer import FireRenderer
from fire.simulator import FireSimulation

# --- Raw ANSI terminal control sequences --------------------------------------
ENTER_ALT_SCREEN = "\033[?1049h"  # switch to the alternate screen
HIDE_CURSOR = "\033[?25l"  # hide the cursor
EXIT_ALT_SCREEN = "\033[?1049l"  # back to the normal screen
SHOW_CURSOR = "\033[?25h"  # show the cursor
RESET_COLOR = "\033[0m"  # reset SGR (colors) attributes
CURSOR_HOME = "\033[H"  # cursor to the top-left corner (redraw in place)

# --- CLI limits -----------------------------------------------------------------
MIN_FPS = 1
DEFAULT_FPS = 30
MAX_FPS = 60
WIND_MIN = -3
WIND_MAX = 3
WIND_AUTO = "auto"
PALETTES = ("fire", "blue")
# Blue combustion base: the number of BOTTOM heat-buffer rows (2 buffer
# rows = 1 terminal line) rendered with the blue (gas) palette.
BASE_ROWS = 4


def _fps(value: str) -> int:
    """argparse type: integer FPS in ``[MIN_FPS..MAX_FPS]``."""
    try:
        fps = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"fps must be an integer, got {value!r}"
        )
    if not MIN_FPS <= fps <= MAX_FPS:
        raise argparse.ArgumentTypeError(
            f"fps must be in [{MIN_FPS}..{MAX_FPS}], got {fps}"
        )
    return fps


def _wind(value: str) -> Union[int, str]:
    """argparse type: ``auto`` or an integer wind in ``[WIND_MIN..WIND_MAX]``."""
    if value == WIND_AUTO:
        return WIND_AUTO
    try:
        wind = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"wind must be an integer in [{WIND_MIN}..{WIND_MAX}] or 'auto', "
            f"got {value!r}"
        )
    if not WIND_MIN <= wind <= WIND_MAX:
        raise argparse.ArgumentTypeError(
            f"wind must be in [{WIND_MIN}..{WIND_MAX}] or 'auto', got {wind}"
        )
    return wind


def _non_negative_int(value: str) -> int:
    """argparse type: integer ``>= 0``."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be a non-negative integer, got {value!r}"
        )
    if n < 0:
        raise argparse.ArgumentTypeError(f"must be >= 0, got {n}")
    return n


def _positive_int(value: str) -> int:
    """argparse type: integer ``>= 1``."""
    try:
        n = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"must be a positive integer, got {value!r}"
        )
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be >= 1, got {n}")
    return n


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="fire",
        description=(
            "TrueColor terminal fire: raw ANSI, no third-party libraries. "
            "Press 'q' or Ctrl+C to quit."
        ),
    )
    parser.add_argument(
        "--fps",
        type=_fps,
        default=DEFAULT_FPS,
        metavar="N",
        help=(
            f"target frames per second, {MIN_FPS}..{MAX_FPS} "
            f"(default: {DEFAULT_FPS})"
        ),
    )
    parser.add_argument(
        "--palette",
        choices=PALETTES,
        default="fire",
        help="color palette: fire or blue (default: fire)",
    )
    parser.add_argument(
        "--wind",
        type=_wind,
        default=WIND_AUTO,
        metavar="N|auto",
        help=(
            f"static wind {WIND_MIN}..{WIND_MAX} or 'auto' "
            f"(default: auto)"
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="PRNG seed for the simulator (deterministic frames)",
    )
    parser.add_argument(
        "--width",
        type=_positive_int,
        default=None,
        metavar="W",
        help="override the terminal width (>= 1)",
    )
    parser.add_argument(
        "--height",
        type=_positive_int,
        default=None,
        metavar="H",
        help="override the terminal height (>= 1)",
    )
    frame_group = parser.add_mutually_exclusive_group()
    frame_group.add_argument(
        "--frame",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="render exactly frame N and exit with code 0",
    )
    frame_group.add_argument(
        "--frames",
        type=_non_negative_int,
        default=None,
        metavar="N",
        help="render N frames (0..N-1) and exit with code 0",
    )
    return parser


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    """Parse CLI arguments (``argv=None`` -> ``sys.argv[1:]``)."""
    return build_parser().parse_args(argv)


def enter_fullscreen(stream) -> None:
    """Enter the alternate screen and hide the cursor."""
    stream.write(ENTER_ALT_SCREEN + HIDE_CURSOR)
    stream.flush()


def exit_fullscreen(stream) -> None:
    """Leave the alternate screen, show the cursor, reset colors."""
    stream.write(EXIT_ALT_SCREEN + SHOW_CURSOR + RESET_COLOR)
    stream.flush()


class FireApp:
    """Owns the simulation, the renderer and the frame loop.

    ``fps`` is the target frame rate (``1..60``); ``palette_name`` is
    ``fire`` or ``blue``; ``wind`` is ``auto`` or a static integer in
    ``[-3, 3]``. ``stream`` is the writable output (defaults to
    ``sys.stdout``) — injectable for testing. ``seed`` (``None`` or an
    int) seeds the simulator's PRNG for deterministic frames;
    ``width``/``height`` (``None`` or ``>= 1``) override the terminal
    size instead of ``shutil.get_terminal_size``.
    """

    def __init__(
        self,
        fps: int = DEFAULT_FPS,
        palette_name: str = "fire",
        wind: Union[int, str] = WIND_AUTO,
        stream=None,
        seed: Optional[int] = None,
        width: Optional[int] = None,
        height: Optional[int] = None,
    ) -> None:
        if not isinstance(fps, int) or not MIN_FPS <= fps <= MAX_FPS:
            raise ValueError(f"fps must be an int in [{MIN_FPS}..{MAX_FPS}]")
        if palette_name not in PALETTES:
            raise ValueError(f"palette must be one of {PALETTES}")
        if wind != WIND_AUTO and not (WIND_MIN <= wind <= WIND_MAX):
            raise ValueError(
                f"wind must be in [{WIND_MIN}..{WIND_MAX}] or 'auto'"
            )
        self.fps = fps
        self.palette_name = palette_name
        self.wind = wind
        self.stream = stream if stream is not None else sys.stdout
        self.seed = seed
        self._width = width
        self._height = height
        self._resize_requested = False
        self._running = True
        self._old_termios = None
        self._prev_sigint = None
        self._prev_sigwinch = None
        # TASK-FIRE-11: per-frame global intensity factor, driven by the
        # app's OWN PRNG (never ``sim._rng``) so the stub in cli_test.py
        # stays valid.
        self._flicker = 1.0
        self._flicker_rng = random.Random(seed)
        self.handle_resize()

    # --- construction / dynamic resize ----------------------------------------

    def handle_resize(self) -> None:
        """Recreate the simulator and its buffer for the current size.

        The terminal size is read with ``shutil.get_terminal_size``
        unless ``width``/``height`` were given to the constructor
        (a non-``None`` override wins); the heat buffer is ``2 * lines``
        rows tall so that the half-block renderer produces exactly
        ``lines`` terminal rows. The fresh simulator is re-ignited at
        the fuel line with the constructor's ``seed``.
        """
        size = get_terminal_size()
        width = self._width if self._width is not None else size.columns
        height = self._height if self._height is not None else size.lines
        width = max(1, width)
        height = max(1, height)
        self.width = width
        self.height = height
        if self.palette_name == "fire":
            palette = generate_fire_palette()
        else:
            palette = generate_blue_fire_palette()
        self.sim = FireSimulation(width=width, height=2 * height, seed=self.seed)
        self.sim.ignite_bottom()
        self.renderer = FireRenderer(
            palette,
            blue_palette=generate_blue_fire_palette(),
            base_rows=BASE_ROWS,
            jitter_seed=self.seed,
        )

    # --- signals -----------------------------------------------------------------

    def _on_sigint(self, signum, frame) -> None:
        """Ctrl+C: stop the frame loop (cleanup happens in ``run``)."""
        self._running = False

    def _on_sigwinch(self, signum, frame) -> None:
        """Terminal resized: request a rebuild on the next frame."""
        self._resize_requested = True

    def _install_signal_handlers(self) -> None:
        self._prev_sigint = signal.getsignal(signal.SIGINT)
        self._prev_sigwinch = signal.getsignal(signal.SIGWINCH)
        signal.signal(signal.SIGINT, self._on_sigint)
        signal.signal(signal.SIGWINCH, self._on_sigwinch)

    def _restore_signal_handlers(self) -> None:
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
        if self._prev_sigwinch is not None:
            signal.signal(signal.SIGWINCH, self._prev_sigwinch)

    # --- terminal input mode --------------------------------------------------------

    def _enable_cbreak(self) -> None:
        """Read single keys without waiting for Enter (TTY only)."""
        if not sys.stdin.isatty():
            return
        self._old_termios = termios.tcgetattr(sys.stdin.fileno())
        tty.setcbreak(sys.stdin.fileno())

    def _restore_termios(self) -> None:
        if self._old_termios is not None:
            termios.tcsetattr(
                sys.stdin.fileno(), termios.TCSADRAIN, self._old_termios
            )
            self._old_termios = None

    # --- frame loop --------------------------------------------------------------------

    def frame_time(self) -> float:
        """Seconds per frame at the target FPS."""
        return 1.0 / self.fps

    def sleep_frame(self, elapsed: float) -> None:
        """Sleep the remainder of the current frame (never negative)."""
        time.sleep(max(0, self.frame_time() - elapsed))

    def _step(self) -> None:
        """Advance the simulation by one frame.

        ``auto`` wind drifts the simulator's target wind; a static wind is
        passed to ``step`` directly. Every frame also spawns floating
        embers (``spawn_sparks``) in both branches. At the end of the
        frame the per-frame flicker factor is recomputed from the app's
        own PRNG (``self._flicker`` in ``[0.85, 1.15]``).
        """
        if self.wind == WIND_AUTO:
            self.sim.update_wind()
            self.sim.step()
        else:
            self.sim.step(wind=self.wind)
        self.sim.spawn_sparks()
        # TASK-FIRE-11: per-frame global intensity in [0.85, 1.15], from
        # the app's own PRNG (no new calls to self.sim).
        self._flicker = 1.0 + self._flicker_rng.uniform(-0.15, 0.15)

    def advance(self, n: int) -> None:
        """Advance the simulation by ``n`` frames (``n`` calls to ``_step``)."""
        for _ in range(n):
            self._step()

    def current_frame(self) -> str:
        """The currently rendered frame as a string.

        TASK-FIRE-11: rendered with the current per-frame ``flicker`` and
        the simulator's ``smoke`` grid.
        """
        return self.renderer.render(
            self.sim.buffer, flicker=self._flicker, smoke=self.sim.smoke
        )

    def _poll_key(self) -> Optional[str]:
        """Non-blocking read of one key (``None`` if none is available)."""
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 0)
        except (OSError, ValueError):
            return None
        if not ready:
            return None
        return sys.stdin.read(1) or None

    def run(self, max_frames: Optional[int] = None) -> None:
        """Run the animation until ``q``/Ctrl+C (or ``max_frames`` frames).

        Enters the alternate screen with a hidden cursor; on exit (always,
        even on error) restores the normal screen, shows the cursor and
        resets colors.
        """
        self._install_signal_handlers()
        self._enable_cbreak()
        enter_fullscreen(self.stream)
        try:
            frames = 0
            while self._running:
                if self._resize_requested:
                    self._resize_requested = False
                    self.handle_resize()
                start = time.perf_counter()
                self._step()
                self.stream.write(CURSOR_HOME)
                self.stream.write(self.current_frame())
                self.stream.flush()
                elapsed = time.perf_counter() - start
                self.sleep_frame(elapsed)
                key = self._poll_key()
                if key in ("q", "Q"):
                    self._running = False
                frames += 1
                if max_frames is not None and frames >= max_frames:
                    break
        finally:
            self._restore_termios()
            exit_fullscreen(self.stream)
            self._restore_signal_handlers()


def main(argv: Optional[List[str]] = None, stream=None) -> int:
    """Headless-capable CLI entry point (TASK-FIRE-09).

    Parses ``argv`` (``None`` -> ``sys.argv[1:]``) with
    ``build_parser()``, constructs a ``FireApp`` and:

    - ``--frame N``: advance N frames, write the rendered frame to
      ``stream``, return 0;
    - else ``--frames N``: N times write ``current_frame() + "\\n"``
      (frames 0..N-1) then advance one frame, return 0;
    - else if stdin is NOT a TTY: write one frame (frame 0) to
      ``stream``, return 0;
    - else (interactive TTY): run the animation, return 0.

    ``--frame``/``--frames`` take priority over the TTY check.
    ``stream`` defaults to ``sys.stdout``.
    """
    args = build_parser().parse_args(argv)
    out = stream if stream is not None else sys.stdout
    app = FireApp(
        fps=args.fps,
        palette_name=args.palette,
        wind=args.wind,
        stream=out,
        seed=args.seed,
        width=args.width,
        height=args.height,
    )
    if args.frame is not None:
        app.advance(args.frame)
        out.write(app.current_frame())
        out.flush()
        return 0
    if args.frames is not None:
        for _ in range(args.frames):
            out.write(app.current_frame() + "\n")
            app.advance(1)
        out.flush()
        return 0
    if not sys.stdin.isatty():
        out.write(app.current_frame())
        out.flush()
        return 0
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
