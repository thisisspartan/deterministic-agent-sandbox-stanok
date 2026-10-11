"""fire_input — non-blocking raw-mode keyboard input for the Doom fire
(TASK-STANOK-CC-243 / FIRE-04).

Two pieces:

- parse_key(data: bytes) -> action | None: a PURE parser mapping terminal
  input bytes to a fire action:
    b"\\x1b[D" -> "wind_left",   b"\\x1b[C" -> "wind_right",
    b"\\x1b[A" -> "intensity_up", b"\\x1b[B" -> "intensity_down",
    b"q" / b"\\x03" -> "quit";   anything else -> None.

- KeyReader(fd): puts the fd into raw mode via termios/tty (restored on
  close) and polls it WITHOUT ever blocking: read() uses select.select with
  timeout 0 and returns the parsed action, or None when there is no data
  (EAGAIN / EOF / closed fd all yield None, never an exception, never a
  block). On a non-tty fd (e.g. a pipe) the raw-mode setup is skipped
  gracefully — polling still works.
"""

import os
import select
import termios
import tty

# Escape sequences / control bytes -> fire action (pure table).
_KEY_ACTIONS = {
    b"\x1b[D": "wind_left",
    b"\x1b[C": "wind_right",
    b"\x1b[A": "intensity_up",
    b"\x1b[B": "intensity_down",
    b"q": "quit",
    b"\x03": "quit",  # Ctrl-C
}

# Longest sequence we parse; a read never consumes more than this.
_MAX_KEY_BYTES = 8


def parse_key(data: bytes):
    """Map raw input bytes to a fire action; None for anything unknown."""
    return _KEY_ACTIONS.get(data)


class KeyReader:
    """Raw-mode, non-blocking key reader over a file descriptor.

    KeyReader(fd): enter raw mode (termios.tcgetattr + tty.setraw) when the
    fd is a tty; restore the original settings on close() (idempotent).
    read() -> action | None: never blocks — select.select([fd], [], [], 0)
    gates the read, and EAGAIN (BlockingIOError) is handled as "no data".
    """

    def __init__(self, fd):
        self.fd = fd
        self._saved = None  # original termios attrs, set only for a real tty
        try:
            self._saved = termios.tcgetattr(fd)
            tty.setraw(fd)
        except (termios.error, OSError):
            self._saved = None  # not a tty (pipe, closed fd): poll anyway
        self._closed = False

    def read(self):
        """Poll the fd once; return the parsed action or None. Never blocks."""
        if self._closed:
            return None
        try:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                return None
            data = os.read(self.fd, _MAX_KEY_BYTES)
        except (BlockingIOError, OSError):  # EAGAIN / EBADF / EIO
            return None
        if not data:  # EOF (writer closed)
            return None
        return parse_key(data)

    def close(self):
        """Restore the original terminal settings. Idempotent."""
        if self._closed:
            return
        self._closed = True
        if self._saved is None:
            return
        saved, self._saved = self._saved, None
        try:
            termios.tcsetattr(self.fd, termios.TCSADRAIN, saved)
        except (termios.error, OSError):
            pass
