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
- ``--wind``: static wind ``-3..3`` or ``auto`` (default ``auto``).
"""

from __future__ import annotations

import argparse
import os
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
    ``sys.stdout``) — injectable for testing.
    """

    def __init__(
        self,
        fps: int = DEFAULT_FPS,
        palette_name: str = "fire",
        wind: Union[int, str] = WIND_AUTO,
        stream=None,
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
        self._resize_requested = False
        self._running = True
        self._old_termios = None
        self._prev_sigint = None
        self._prev_sigwinch = None
        self.handle_resize()

    # --- construction / dynamic resize ----------------------------------------

    def handle_resize(self) -> None:
        """Recreate the simulator and its buffer for the current size.

        The terminal size is read with ``shutil.get_terminal_size``; the
        heat buffer is ``2 * lines`` rows tall so that the half-block
        renderer produces exactly ``lines`` terminal rows. The fresh
        simulator is re-ignited at the fuel line.
        """
        size = get_terminal_size()
        width = max(1, size.columns)
        height = max(1, size.lines)
        self.width = width
        self.height = height
        if self.palette_name == "fire":
            palette = generate_fire_palette()
        else:
            palette = generate_blue_fire_palette()
        self.sim = FireSimulation(width=width, height=2 * height)
        self.sim.ignite_bottom()
        self.renderer = FireRenderer(palette)

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
        embers (``spawn_sparks``) in both branches.
        """
        if self.wind == WIND_AUTO:
            self.sim.update_wind()
            self.sim.step()
        else:
            self.sim.step(wind=self.wind)
        self.sim.spawn_sparks()

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
                self.stream.write(self.renderer.render(self.sim.buffer))
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
