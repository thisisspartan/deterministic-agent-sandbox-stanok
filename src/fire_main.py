"""fire_main — the runnable Doom fire: FPS-timed main loop, resize-safe
geometry, guaranteed teardown (TASK-STANOK-CC-242 / FIRE-03).

The engine (`src/fire_engine.py`) and the renderer (`src/fire_render.py`) are
imported, never modified. All loop dependencies are injectable so the loop is
drivable from tests without a real terminal:

- `out`: a sink with `.write(str)` (real app: sys.stdout).
- `clock`: an object with `.perf_counter()` and `.sleep(s)` (real app: `time`).
- `size_fn`: a callable returning `(cols, rows)` (real app:
  `shutil.get_terminal_size`). The field height is `rows * 2` — the renderer
  pairs two field rows per terminal row (half-block).

Contract:

- FireApp(out, clock, size_fn=shutil.get_terminal_size): builds the initial
  field from size_fn; `wind` defaults to 0.
- run(fps=30, max_frames=None): writes `fire_render.ENTER` once; each tick:
  if the resize flag is set, recompute dimensions/field AT TICK START only,
  then `field.step(wind)` and exactly one `out.write(render_frame(field))`.
  Delta-time compensation: the loop schedules absolute frame deadlines
  (`next_at += 1/fps`) and sleeps only the remaining time, via the injected
  clock. `max_frames` bounds the loop; a stop request (SIGINT/SIGTERM) ends
  it. Returns cleanly.
- Teardown is GUARANTEED (installed via `finally`, `atexit.register`, and
  SIGINT/SIGTERM handlers) and IDEMPOTENT: `fire_render.EXIT` is written
  exactly once total; a second `teardown()` is a no-op. Signal handlers are
  restored on teardown.
- SIGWINCH handler only sets a flag — no buffer work in the handler.
- parse_fps(argv=None) -> int: `--fps N`, default 30. main() builds the real
  app (sys.stdout, time, shutil terminal size) and runs it.
"""

import argparse
import atexit
import random
import shutil
import signal
import sys
import time

try:  # imported as part of the package (tests, `python3 -m pytest`)
    from src.fire_engine import FireField
    from src.fire_render import ENTER, EXIT, render_frame
except ImportError:  # run directly: `python3 src/fire_main.py` puts src/ on sys.path
    from fire_engine import FireField
    from fire_render import ENTER, EXIT, render_frame

DEFAULT_FPS = 30


class FireApp:
    """The Doom fire main loop with injectable out / clock / size_fn."""

    def __init__(self, out, clock, size_fn=shutil.get_terminal_size):
        self.out = out
        self.clock = clock
        self.size_fn = size_fn
        self.wind = 0
        self._stop = False
        self._resized = False
        self._torn_down = False
        self._prev_handlers = None
        self.field = self._new_field(*self._dimensions())

    # --- geometry ----------------------------------------------------------

    def _dimensions(self):
        """Terminal size -> field size; height = rows * 2 (half-block)."""
        cols, rows = self.size_fn()
        return cols, rows * 2

    def _new_field(self, width, height):
        return FireField(width, height, rng=random.Random())

    # --- signal handlers ----------------------------------------------------

    def _request_stop(self, signum=None, frame=None):
        self._stop = True

    def _on_winch(self, signum, frame):
        # Flag only: the new geometry is applied at the next tick start.
        self._resized = True

    def _install_handlers(self):
        self._prev_handlers = {}
        for sig, handler in (
            (signal.SIGINT, self._request_stop),
            (signal.SIGTERM, self._request_stop),
            (signal.SIGWINCH, self._on_winch),
        ):
            self._prev_handlers[sig] = signal.signal(sig, handler)

    def _restore_handlers(self):
        for sig, handler in (self._prev_handlers or {}).items():
            try:
                signal.signal(sig, handler)
            except (ValueError, OSError):
                pass  # not on the main thread: nothing left to restore
        self._prev_handlers = None

    # --- teardown ------------------------------------------------------------

    def teardown(self):
        """Leave the alternate screen. Guaranteed and idempotent: the EXIT
        sequence is written exactly once total; later calls are no-ops."""
        if self._torn_down:
            return
        self._torn_down = True
        self._restore_handlers()
        self.out.write(EXIT)

    # --- main loop -----------------------------------------------------------

    def run(self, fps=DEFAULT_FPS, max_frames=None):
        """Run the fire. ENTER once; one out.write per frame; resize applied
        at tick start only; delta-time compensation via the injected clock;
        teardown guaranteed via finally (+ atexit + signal handlers)."""
        self._install_handlers()
        atexit.register(self.teardown)
        self.out.write(ENTER)
        try:
            budget = 1.0 / fps
            frames = 0
            next_at = self.clock.perf_counter()
            while not self._stop and (max_frames is None or frames < max_frames):
                if self._resized:
                    self._resized = False
                    self.field = self._new_field(*self._dimensions())
                self.field.step(self.wind)
                self.out.write(render_frame(self.field))
                frames += 1
                next_at += budget
                now = self.clock.perf_counter()
                if next_at > now:
                    self.clock.sleep(next_at - now)
        finally:
            self.teardown()


def parse_fps(argv=None):
    """Parse `--fps N` from argv; default 30."""
    parser = argparse.ArgumentParser(prog="fire_main", description="Doom fire")
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS,
                        help="frames per second (default: %(default)s)")
    args = parser.parse_args(argv)
    return args.fps


def main(argv=None):
    app = FireApp(out=sys.stdout, clock=time, size_fn=shutil.get_terminal_size)
    app.run(fps=parse_fps(argv))


if __name__ == "__main__":
    main()
