"""Doomfire main loop (TASK-STANOK-CC-250, FIRE2-03): FPS timing, resize-safe
geometry, guaranteed teardown.

`python3 src/fire_main.py` runs the fire and always restores the terminal.
The loop logic is injectable — `out` (a sink with `.write(str)`), `clock`
(`.perf_counter()` / `.sleep(s)`) and `size_fn` (-> `(cols, rows)`) — so tests
can drive it frame by frame without a real TTY.

Depends on src/fire_engine.py and src/fire_render.py; neither is modified.

Interactivity (TASK-STANOK-CC-251, FIRE2-04): an optional `keys` source (a
KeyReader-like with `.read()`, see src/fire_input.py) is polled once per tick
before step; `main()` enables it on real stdin only when stdin is a tty.
"""

import argparse
import atexit
import shutil
import signal
import sys
import time

from fire_engine import WIND_LIMIT, FireField
from fire_input import KeyReader
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

    Keys (FIRE2-04): `keys` is an optional source with `.read()` returning
    an action name or None (a `fire_input.KeyReader`, or any stand-in).
    Once per tick, BEFORE step, it is polled and the action applied:
    wind_left/wind_right move `self.wind` (clamped to [-WIND_LIMIT,
    WIND_LIMIT]); intensity_up/down adjust a decay level applied to every
    field value before step (see `_apply_intensity_decay`); "quit" requests
    a stop through the same path as SIGINT. `keys=None` (the default)
    changes nothing.

    Teardown is guaranteed (finally + atexit + the signal handlers) and
    idempotent: EXIT is written at most once per run, and only if ENTER was
    written.
    """

    def __init__(self, out=None, clock=None, size_fn=None, wind=0, keys=None):
        self.out = sys.stdout if out is None else out
        self.clock = time if clock is None else clock
        self.size_fn = shutil.get_terminal_size if size_fn is None else size_fn
        self.wind = wind
        self.keys = keys
        self.intensity = 0
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

        Per frame: (resize flag? -> rebuild geometry at TICK START) -> poll
        `keys` once and apply the action (FIRE2-04) -> step -> exactly one
        `out.write(render_frame(...))` -> sleep the remainder of the 1/fps
        budget, measured with the injected clock.
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
                if self.keys is not None:
                    self._apply_key(self.keys.read())  # once per tick, before step
                self._apply_intensity_decay()
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

    def _apply_key(self, action):
        """Apply one polled key action (FIRE2-04); None is a no-op."""
        if action is None:
            return
        if action == "wind_left":
            self.wind = max(-WIND_LIMIT, self.wind - 1)
        elif action == "wind_right":
            self.wind = min(WIND_LIMIT, self.wind + 1)
        elif action == "intensity_up":
            self.intensity += 1
        elif action == "intensity_down":
            self.intensity = max(0, self.intensity - 1)
        elif action == "quit":
            self.handle_stop()  # the same stop path as SIGINT

    def _apply_intensity_decay(self):
        """Extra decay applied to every field value before step.

        Documented choice (the ticket's fallback): `FireField.step` has no
        intensity parameter, so the intensity level is implemented as an
        extra decay applied to the value before step — `value -= 1` per
        intensity level, clamped at 0. Level 0 (the default, and every
        run without intensity keys) changes nothing.
        """
        if self.intensity <= 0:
            return
        buf = self.field.buffer
        for i in range(len(buf)):
            if buf[i]:
                buf[i] = max(0, buf[i] - self.intensity)

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
    # Keys only on a real tty: non-tty runs (CI, pipes, the PTY harness)
    # keep the previous behavior with keys=None.
    keys = None
    try:
        if sys.stdin.isatty():
            keys = KeyReader(sys.stdin.fileno())
    except (OSError, AttributeError):
        keys = None
    app = FireApp(
        out=sys.stdout, clock=time, size_fn=shutil.get_terminal_size, keys=keys
    )
    try:
        app.run(fps=args.fps)
    finally:
        if keys is not None:
            keys.close()  # restore the terminal from raw mode


if __name__ == "__main__":
    main()
