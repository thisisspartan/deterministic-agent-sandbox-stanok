"""Non-blocking keyboard input for the Doomfire (TASK-STANOK-CC-251, FIRE2-04).

`parse_key(data)` is a pure byte-sequence -> action mapping. `KeyReader(fd)`
sets a tty fd to raw mode via termios/tty (saving the state for restore on
close) and polls it WITHOUT ever blocking: `select.select([fd], [], [], 0)`
first, and EAGAIN is handled defensively if the fd is already non-blocking.
A non-tty fd (a pipe, /dev/null) is left as-is — `read()` still works, which
is what the tests use.
"""

import os
import select
import termios
import tty

# The key contract: exact byte sequences of the arrow keys (CSI), 'q' and
# Ctrl-C. Anything else is not a key event.
KEY_ACTIONS = {
    b"\x1b[D": "wind_left",
    b"\x1b[C": "wind_right",
    b"\x1b[A": "intensity_up",
    b"\x1b[B": "intensity_down",
    b"q": "quit",
    b"\x03": "quit",  # Ctrl-C
}

MAX_READ = 64  # one poll drains at most this many bytes


def parse_key(data):
    """Map one key event to an action name, or None for anything else.

    Pure: an exact lookup of the whole byte sequence; partial sequences,
    unknown bytes and multi-byte noise all yield None.
    """
    if not isinstance(data, (bytes, bytearray)):
        return None
    return KEY_ACTIONS.get(bytes(data))


class KeyReader:
    """Raw-mode, non-blocking key reader over a file descriptor.

    - Construction puts the fd in raw mode when it is a tty (the termios
      state is saved first); a non-tty fd is left untouched.
    - `read()` NEVER blocks: select with timeout 0; no data -> None. If
      select reports readability, os.read cannot block; BlockingIOError
      (EAGAIN) and EOF are handled as None.
    - `close()` restores the saved termios state and is idempotent; the
      reader is also usable as a context manager.
    """

    def __init__(self, fd):
        self.fd = fd
        self._closed = False
        self._saved_termios = None
        try:
            self._saved_termios = termios.tcgetattr(fd)
        except (termios.error, OSError):
            self._saved_termios = None  # not a tty: nothing to set raw or restore
        if self._saved_termios is not None:
            try:
                tty.setraw(fd)
            except (termios.error, OSError):
                self._saved_termios = None

    def read(self):
        """Return the action for one key event, or None — never blocks."""
        if self._closed:
            return None
        try:
            ready, _, _ = select.select([self.fd], [], [], 0)
            if not ready:
                return None
            data = os.read(self.fd, MAX_READ)
        except (BlockingIOError, InterruptedError):
            return None  # EAGAIN / signal: no key available right now
        except OSError:
            return None  # closed or invalid fd: treat as no input
        if not data:
            return None  # EOF
        return parse_key(data)

    def close(self):
        """Restore the termios state saved at construction; safe to call twice."""
        if self._closed:
            return
        self._closed = True
        saved, self._saved_termios = self._saved_termios, None
        if saved is not None:
            try:
                termios.tcsetattr(self.fd, termios.TCSADRAIN, saved)
            except (termios.error, OSError):
                pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False
