"""vt_screen — the boundary judge for terminal-consumer evidence.

Host-authored fixture (the accept mechanism requires a trusted test the agent
cannot author). A consumer-view oracle: it runs a program under a real PTY and
checks SCREEN-LEVEL INVARIANTS of its output — not byte sequences, not the
program's own API. A program passes because a terminal user would see a
correct screen, whatever mechanism it used to get there.

Vocabulary (invariants), each independently assertable:
  assert_stable_line_origin — every drawn line starts at the SAME column
    (a bare-LF staircase, a drifting indent: caught). Column 0 is NOT
    required: "same column" is the invariant, "column 0" is one instance.
  assert_no_scroll — the program did not push content past the window
    (a full-screen redraw must home/clear; a streaming program may scroll —
    the CONTRACT picks which invariants apply, the helper never imposes all).
  assert_no_wrap — no line exceeded the window width. The width bound comes
    from the PTY window (TIOCSWINSZ), never from the program's own flags.
  assert_termios_restored — the terminal settings at exit equal those at
    start (raw mode is borrowed, not kept).
  assert_cursor_restored — the cursor is visible at exit.
  assert_exit — the process exited 0 within the timeout.

Modelled VT subset (the boundary vocabulary needs exactly this): printable
chars (1 column each), CR, LF (LF moves down, KEEPS the column — real
terminal semantics; ONLCR translation happens in the tty, so cooked output
arrives already CRLF-translated), line wrap, scroll, SGR sequences (skipped,
no geometry), DEC private mode ?25h/l (cursor visibility), and cursor
addressing — CUP (ESC[H, ESC[<row>[;<col>]H) and CUU (ESC[<n>A) — modelled
per the CC-281 incident: an in-place redraw must home or move up, and the
judge must read that as "no scroll", not as geometry. ESC[2J and other
CSIs stay unmodelled; extend by incident, not by speculation.

gVisor/runsc constraint (fresh-Job probe 2026-10-17): TIOCSWINSZ-set works
on master and slave, but the 2-argument fcntl.ioctl(fd, TIOCGWINSZ) form
fails with EFAULT — window size is READ via os.get_terminal_size only.
"""

from __future__ import annotations

import codecs
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time
from typing import List, NamedTuple, Optional


# ---------------------------------------------------------------------------
# Screen model (pure byte-stream interpreter, no PTY required)
# ---------------------------------------------------------------------------

class Screen:
    """Interpret a terminal's output byte stream the way a terminal would."""

    def __init__(self, rows: int, cols: int) -> None:
        self.rows = rows
        self.cols = cols
        self.row = 0
        self.col = 0
        self.wraps = 0
        self.scrolls = 0
        self.cursor_visible = True
        # Origin column of every line that actually received printable output.
        self.line_origins: List[int] = []
        self._row_used = False
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    # -- line/row mechanics -------------------------------------------------

    def _advance_line(self) -> None:
        self.row += 1
        self._row_used = False
        if self.row >= self.rows:
            self.scrolls += 1
            self.row = self.rows - 1

    def _put(self, ch: str) -> None:
        if self.col >= self.cols:
            self.wraps += 1
            self._advance_line()
            self.col = 0
        if not self._row_used:
            self.line_origins.append(self.col)
            self._row_used = True
        self.col += 1

    # -- byte stream ---------------------------------------------------------

    def feed(self, data) -> None:
        text = self._decoder.decode(data, False) if isinstance(data, bytes) else data
        i = 0
        n = len(text)
        while i < n:
            ch = text[i]
            o = ord(ch)
            if ch == "\x1b":
                i = self._csi(text, i)
                continue
            if ch == "\r":
                self.col = 0
            elif ch == "\n":
                self._advance_line()
            elif o == 0x08:  # BS: move back, no overwrite semantics modelled
                self.col = max(0, self.col - 1)
            elif o >= 0x20 and o != 0x7F:
                self._put(ch)
            # other C0 controls: ignored
            i += 1

    def _csi(self, text: str, i: int) -> int:
        """Consume one CSI sequence; return the index after it. SGR and
        unmodelled CSIs are skipped; ?25h/l drive cursor visibility."""
        i += 1  # ESC
        if i >= len(text) or text[i] != "[":
            return i  # a lone ESC: ignored
        i += 1
        params = ""
        while i < len(text):
            c = text[i]
            if "\x40" <= c <= "\x7E":  # final byte
                break
            params += c
            i += 1
        if i < len(text):
            final = text[i]
            i += 1
            if final in "hl" and params.startswith("?"):
                if params[1:] == "25":
                    self.cursor_visible = final == "h"
            elif final == "H" and not params.startswith("?"):
                # CUP: ESC[<row>[;<col>]H, 1-based, defaults 1. Addressing
                # clamps to the window; it never scrolls (CC-281).
                row = _csi_int(params, 0, 1)
                col = _csi_int(params, 1, 1)
                self.row = max(0, min(row - 1, self.rows - 1))
                self.col = max(0, min(col - 1, self.cols - 1))
                self._row_used = False
            elif final == "A" and not params.startswith("?"):
                # CUU: ESC[<n>A — move up n rows (min 1). Never scrolls.
                self.row = max(0, self.row - max(1, _csi_int(params, 0, 1)))
                self._row_used = False
        return i


def _csi_int(params: str, index: int, default: int) -> int:
    parts = params.split(";")
    if index < len(parts) and parts[index].isdigit():
        return int(parts[index])
    return default


# ---------------------------------------------------------------------------
# Invariants (each assertable independently; all raise AssertionError)
# ---------------------------------------------------------------------------

def assert_stable_line_origin(screen: Screen) -> None:
    origins = screen.line_origins
    if len(set(origins)) > 1:
        raise AssertionError(
            "line origins drift (staircase?): %r" % (origins[:8],))


def assert_no_scroll(screen: Screen) -> None:
    if screen.scrolls:
        raise AssertionError("screen scrolled %d times" % screen.scrolls)


def assert_no_wrap(screen: Screen) -> None:
    if screen.wraps:
        raise AssertionError("lines wrapped %d times (window %dx%d)"
                            % (screen.wraps, screen.rows, screen.cols))


def assert_cursor_restored(screen: Screen) -> None:
    if not screen.cursor_visible:
        raise AssertionError("cursor left hidden at exit")


def assert_termios_restored(result: "Result") -> None:
    if not result.termios_restored:
        raise AssertionError("terminal settings not restored after exit")


def assert_exit(result: "Result") -> None:
    if result.timed_out:
        raise AssertionError("program did not exit within the timeout")
    if result.rc != 0:
        raise AssertionError("exit rc=%d" % result.rc)


ALL_INVARIANTS = (
    ("stable_line_origin", lambda r: assert_stable_line_origin(r.screen)),
    ("no_scroll", lambda r: assert_no_scroll(r.screen)),
    ("no_wrap", lambda r: assert_no_wrap(r.screen)),
    ("cursor_restored", lambda r: assert_cursor_restored(r.screen)),
    ("termios_restored", lambda r: assert_termios_restored(r)),
    ("exit", lambda r: assert_exit(r)),
)


def check_all(result: "Result") -> dict:
    """Evaluate every invariant: name -> None (pass) or the failure message.
    The calibration matrix uses this to prove each mutant is caught by
    exactly its own invariant."""
    out = {}
    for name, fn in ALL_INVARIANTS:
        try:
            fn(result)
            out[name] = None
        except AssertionError as exc:
            out[name] = str(exc)
    return out


# ---------------------------------------------------------------------------
# PTY harness
# ---------------------------------------------------------------------------

class Result(NamedTuple):
    raw: bytes
    rc: int
    screen: Screen
    termios_restored: bool
    timed_out: bool


def window_size(fd: int):
    """Read the PTY window size. runsc-safe: os.get_terminal_size only —
    the 2-arg fcntl.ioctl(TIOCGWINSZ) form is EFAULT under gVisor."""
    return os.get_terminal_size(fd)


def set_window_size(fd: int, rows: int, cols: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("hhhh", rows, cols, 0, 0))


def run_pty(argv, feed=b"", rows: int = 24, cols: int = 80,
            timeout: float = 10.0, cwd: Optional[str] = None,
            env: Optional[dict] = None) -> Result:
    """Run argv under a real PTY (the consumer's view): the program's stdin,
    stdout and stderr are the slave; the judge reads the master. The window
    is set on the master BEFORE the child starts (TIOCSWINSZ works on the
    master under runsc; the child sees it via os.get_terminal_size).

    `feed` is written to the master (the user's keystrokes): either plain
    bytes (written once, as a user who types before the program starts) or a
    sequence of (delay_seconds, bytes) chunks (a user who types LATER — the
    only way to force a paced program to draw more than one frame before
    quitting; CC-281: a single-shot feed is consumed in the first poll and
    makes no_scroll vacuous). Returns the raw master byte stream, the exit
    code, the interpreted Screen, and whether the termios settings were
    restored."""
    master, slave = pty.openpty()
    set_window_size(master, rows, cols)
    attrs_before = termios.tcgetattr(slave)

    pid = os.fork()
    if pid == 0:  # child: the program under test
        os.close(master)
        try:
            os.setsid()
            try:  # make the slave the controlling terminal (best effort)
                fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            except OSError:
                pass
            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            os.close(slave)
            if cwd is not None:
                os.chdir(cwd)
            if env is not None:
                os.execve(argv[0], list(argv), env)
            else:
                os.execv(argv[0], list(argv))
        except Exception:
            os._exit(127)

    # The judge keeps BOTH ends open: the master for the byte stream, the
    # slave for the termios read-back (the canonical location of the state).
    schedule = None
    if isinstance(feed, (bytes, bytearray)):
        if feed:
            os.write(master, feed)
    else:
        schedule = sorted((float(d), bytes(c)) for d, c in feed)

    def _write_due(now: float) -> None:
        # A chunk whose delay has elapsed. If the child is already gone the
        # write fails (EIO) — the keystroke never reached a user, which is
        # the program's business, not the judge's.
        while schedule and schedule[0][0] <= now - t_feed:
            _, chunk = schedule.pop(0)
            try:
                os.write(master, chunk)
            except OSError:
                pass

    t_feed = time.monotonic()
    raw = b""
    timed_out = True
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        ready = select.select([master], [], [], min(remaining, 0.1))[0]
        if ready:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if chunk:
                raw += chunk
        if schedule:
            _write_due(time.monotonic())
        done = os.waitpid(pid, os.WNOHANG)
        if done[0] == pid:
            timed_out = False
            rc = os.waitstatus_to_exitcode(done[1])
            # drain whatever the program buffered before closing the slave
            drain_end = time.monotonic() + 0.5
            while time.monotonic() < drain_end:
                if not select.select([master], [], [], 0.1)[0]:
                    break
                try:
                    chunk = os.read(master, 65536)
                except OSError:
                    break
                if not chunk:
                    break
                raw += chunk
            break

    if timed_out:
        rc = -1
        try:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
        except OSError:
            pass

    # termios state lives on the slave; the child is gone, the settings it
    # left behind are what count.
    try:
        attrs_after = termios.tcgetattr(slave)
    except OSError:
        attrs_after = None
    termios_restored = attrs_after == list(attrs_before)

    os.close(master)
    os.close(slave)
    screen = Screen(rows, cols)
    screen.feed(raw)
    return Result(raw=raw, rc=rc, screen=screen,
                  termios_restored=termios_restored, timed_out=timed_out)
