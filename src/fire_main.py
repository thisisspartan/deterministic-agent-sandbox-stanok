"""Doomfire main loop (TASK-STANOK-CC-250, FIRE2-03): FPS timing, resize-safe
geometry, guaranteed teardown.

`python3 src/fire_main.py` runs the fire and always restores the terminal.
The loop logic is injectable — `out` (a sink with `.write(str)`), `clock`
(`.perf_counter()` / `.sleep(s)`) and `size_fn` (-> `(cols, rows)`) — so tests
can drive it frame by frame without a real TTY.

Depends on src/fire_engine.py and src/fire_render.py; neither is modified.
"""

import argparse
import atexit
import shutil
import signal
import sys
import time

from fire_engine import FireField
from fire_render import ENTER, EXIT, render_frame

DEFAULT_FPS = 30


class FireApp:
    """The fire as a process loop: one write per frame, one teardown per run.

    Geometry: `size_fn()` yields `(cols, rows)`; the field is `cols x rows*2`
    because the renderer is half-block — one terminal row covers two field
    rows (see src/fire_render.py).

    Signal contract:
      - SIGINT / SIGTERM -> `handle_stop`: request a stop, the loop ends at
        the next check and the `finally` tears the terminal back down;
      - SIGWINCH -> `handle_winch`: sets a flag ONLY — no dimensions, no
        buffer work in the handler. The new geometry is rebuilt at the START
        of the next tick, never inside step/render.

    Teardown is guaranteed (finally + atexit + the signal handlers) and
    idempotent: EXIT is written at most once per run, and only if ENTER was
    written.
    """

    def __init__(self, out=None, clock=None, size_fn=None, wind=0):
        self.out = sys.stdout if out is None else out
        self.clock = time if clock is None else clock
        self.size_fn = shutil.get_terminal_size if size_fn is None else size_fn
        self.wind = wind
        self.field = None
        self._stop_requested = False
        self._resize_pending = False
        self._entered = False
        self._torn_down = False
        self._saved_handlers = None

    # --- signal entry points: a flag, nothing else --------------------------

    def handle_stop(self, signum=None, frame=None):
        self._stop_requested = True

    def handle_winch(self, signum=None, frame=None):
        self._resize_pending = True

    # --- the loop ------------------------------------------------------------

    def run(self, fps=DEFAULT_FPS, max_frames=None):
        """Animate until `max_frames` frames are drawn or a stop is requested.

        Per frame: (resize flag? -> rebuild geometry at TICK START) -> step ->
        exactly one `out.write(render_frame(...))` -> sleep the remainder of
        the 1/fps budget, measured with the injected clock.
        """
        if fps <= 0:
            raise ValueError(f"fps must be positive, got {fps}")
        frame_budget = 1.0 / fps
        self._torn_down = False
        self._entered = False
        self._stop_requested = False
        self._resize_pending = False
        self._install_signal_handlers()
        atexit.register(self.teardown)
        try:
            self.out.write(ENTER)
            self._entered = True
            self._build_field()
            frames = 0
            while not self._stop_requested and (
                max_frames is None or frames < max_frames
            ):
                tick_start = self.clock.perf_counter()
                if self._resize_pending:
                    self._resize_pending = False
                    self._build_field()  # new geometry at TICK START only
                self.field.step(self.wind)
                self.out.write(render_frame(self.field))
                frames += 1
                elapsed = self.clock.perf_counter() - tick_start
                remaining = frame_budget - elapsed
                if remaining > 0:
                    self.clock.sleep(remaining)
        finally:
            self.teardown()

    def teardown(self):
        """Leave the alternate screen — exactly once per run, safe to call twice."""
        if self._torn_down:
            return
        self._torn_down = True
        self._restore_signal_handlers()
        if not self._entered:
            return
        try:
            self.out.write(EXIT)
        except Exception:
            pass  # teardown also runs from atexit: it must not raise there

    # --- internals -------------------------------------------------------------

    def _build_field(self):
        cols, rows = self.size_fn()
        self.field = FireField(int(cols), max(0, int(rows)) * 2)

    def _install_signal_handlers(self):
        self._saved_handlers = {}
        for sig, handler in (
            (signal.SIGINT, self.handle_stop),
            (signal.SIGTERM, self.handle_stop),
            (signal.SIGWINCH, self.handle_winch),
        ):
            try:
                self._saved_handlers[sig] = signal.getsignal(sig)
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # not the main thread, or this signal is unavailable here

    def _restore_signal_handlers(self):
        saved, self._saved_handlers = self._saved_handlers, None
        for sig, previous in (saved or {}).items():
            try:
                signal.signal(sig, previous)
            except (ValueError, OSError, TypeError):
                pass


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="fire_main",
        description="Doom fire in the terminal (half-block ANSI), Ctrl-C to stop.",
    )
    parser.add_argument(
        "--fps",
        type=int,
        default=DEFAULT_FPS,
        help="target frames per second (default: %(default)s)",
    )
    args = parser.parse_args(argv)
    app = FireApp(out=sys.stdout, clock=time, size_fn=shutil.get_terminal_size)
    app.run(fps=args.fps)


if __name__ == "__main__":
    main()
