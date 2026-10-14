"""doomfire terminal controller — alternate screen, cursor, teardown, signals.

Owns the terminal lifecycle only: enters the alternate screen with the cursor
hidden, presents whole frames with one write/flush, and restores the terminal
exactly once (idempotent teardown, registered via atexit). Signal handlers
follow the async-signal-safe pattern: they only set flags and record an exit
code; all real work happens in the main loop (a later ticket).

Depends on nothing: the stream is injected (any object with write(str) and
flush()); the module imports only `signal` and `atexit` — no sys/os/time, no
project modules, no real terminal size, no main loop.
"""

import atexit
import signal

EXIT_SIGINT = 130
EXIT_SIGTERM = 143

_ENTER_ALT_SCREEN_AND_HIDE_CURSOR = "\x1b[?1049h\x1b[?25l"
_SHOW_CURSOR_AND_EXIT_ALT_SCREEN = "\x1b[?25h\x1b[?1049l"


class TerminalController:
    """Terminal lifecycle for the doomfire CLI (dependency-injected stream)."""

    def __init__(self, stream):
        self._stream = stream
        self._setup_done = False
        self._torn_down = False
        self.should_exit = False
        self.resize_requested = False
        self.exit_code = 0

    def setup(self):
        """Enter the alternate screen, hide the cursor, install teardown and
        signal handlers. Idempotent: a second call writes and registers
        nothing."""
        if self._setup_done:
            return
        self._setup_done = True
        self._stream.write(_ENTER_ALT_SCREEN_AND_HIDE_CURSOR)
        self._stream.flush()
        atexit.register(self.teardown)
        signal.signal(signal.SIGINT, self._handle_sigint)
        signal.signal(signal.SIGTERM, self._handle_sigterm)
        signal.signal(signal.SIGWINCH, self._handle_sigwinch)

    def present(self, frame):
        """Write one whole rendered frame and flush it (one write, one flush)."""
        self._stream.write(frame)
        self._stream.flush()

    def teardown(self):
        """Show the cursor, leave the alternate screen. Idempotent: the second
        call is a no-op, so it is safe from atexit after an explicit call."""
        if self._torn_down:
            return
        self._torn_down = True
        self._stream.write(_SHOW_CURSOR_AND_EXIT_ALT_SCREEN)
        self._stream.flush()

    def clear_flags(self):
        """Reset the signal flags at frame boundaries (called by the CLI)."""
        self.should_exit = False
        self.resize_requested = False

    def _handle_sigint(self, signum, frame):
        self.should_exit = True
        self.exit_code = EXIT_SIGINT

    def _handle_sigterm(self, signum, frame):
        self.should_exit = True
        self.exit_code = EXIT_SIGTERM

    def _handle_sigwinch(self, signum, frame):
        self.resize_requested = True
