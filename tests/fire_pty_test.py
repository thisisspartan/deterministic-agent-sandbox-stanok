"""End-to-end PTY integration for the Doomfire (TASK-STANOK-CC-252, FIRE2-05).

Byte-level proof that the terminal behavior needs no human at a keyboard: the
real program `python3 src/fire_main.py` is spawned under a real pseudo-terminal
built with the STANDARD LIBRARY ONLY (`pty`, `os`, `signal`, `select`, `time`,
plus `fcntl`/`termios`/`struct` for the window-size ioctls), and assertions are
made on the RAW BYTES read from the master side:

  1. the stream starts with the alt-screen enter and paints half-block cells
     with truecolor fg+bg, at the PTY's window size — the fire renders;
  2. changing the window size (TIOCSWINSZ -> the kernel delivers SIGWINCH)
     neither kills the child nor stops it painting, and the new geometry shows
     up in the frames — the fire survives a resize;
  3. SIGINT ends the child with exit code 0 and the stream contains the
     teardown that shows the cursor and leaves the alternate screen — the
     terminal is restored.

Robustness (ticket requirement 5): every read is bounded by a timeout, the
child is always reaped, and a child that is still alive when it should have
exited is SIGKILLed and the test fails instead of hanging. No temp files.
"""

import errno
import fcntl
import os
import pty
import select
import signal
import struct
import sys
import termios
import time

import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE_MAIN = os.path.join(REPO_ROOT, "src", "fire_main.py")

# The byte-level contract of the rendered stream (see src/fire_render.py).
ALT_ON = b"\x1b[?1049h"  # enter the alternate screen
ALT_OFF = b"\x1b[?1049l"  # leave it again
SHOW_CURSOR = b"\x1b[?25h"  # the cursor is restored
HOME = b"\x1b[H"  # cursor home: one per frame, no clear-screen
RESET = b"\x1b[0m"  # SGR reset: one per frame, at its end
FG = b"\x1b[38;2;"  # truecolor foreground
BG = b"\x1b[48;2;"  # truecolor background
CELL = "▀".encode("utf-8")  # b"\xe2\x96\x80" — U+2580 UPPER HALF BLOCK

INITIAL = (80, 24)  # (cols, rows) the PTY is opened with
RESIZED = (60, 12)  # (cols, rows) it is resized to

READ_CHUNK = 65536
# Reads that must not block forever (ticket requirement 5).
TEARDOWN_TIMEOUT = 10.0
# Errors that mean "the child closed the last reference to the slave": the
# stream is over, which is a normal end of a read phase, not a failure.
STREAM_CLOSED = (errno.EIO, errno.ENXIO, errno.EBADF, errno.ECONNRESET)


# --- the PTY plumbing ---------------------------------------------------------


def _set_winsize(fd, cols, rows):
    """TIOCSWINSZ on `fd`: the kernel stores the size and signals SIGWINCH to
    the terminal's foreground process group (the struct is rows, cols, x, y)."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _child_env():
    """Environment for the child: a real terminal type, UTF-8 stdio (the
    half-block cell must reach the master as its exact 3 bytes), and NO
    COLUMNS/LINES — shutil.get_terminal_size prefers those over the real
    window size, which would make every resize invisible."""
    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    return env


def _run_fire(slave, master):
    """The child side of the fork. Never returns.

    The child takes the slave as stdin/stdout/stderr and makes it its
    controlling terminal (setsid + TIOCSCTTY): without a controlling terminal
    the pty has no foreground process group, and the kernel would deliver
    SIGWINCH to nobody — the resize test would prove nothing.
    """
    try:
        os.close(master)
        os.setsid()
        fcntl.ioctl(slave, termios.TIOCSCTTY, 1)
        for fd in (0, 1, 2):
            os.dup2(slave, fd)
        if slave > 2:
            os.close(slave)
        os.chdir(REPO_ROOT)  # src/ imports resolve from the repo root
        os.execve(sys.executable, [sys.executable, FIRE_MAIN], _child_env())
    except BaseException:
        pass  # an exec failure must not fall through into the test process
    os._exit(127)


def frame_geometries(stream):
    """`(cols, rows)` of every COMPLETE frame in a raw byte stream.

    A frame is the segment between two cursor-homes; it is complete when it
    contains the SGR reset that ends it and every one of its rows has the same
    number of half-block cells. A segment cut off by the read boundary has no
    reset and is skipped, so the result is a property of the renderer, not of
    where the reader happened to stop.
    """
    geometries = []
    for segment in stream.split(HOME)[1:]:  # [0] is the ENTER sequence
        if RESET not in segment:
            continue
        rows = segment.split(b"\n")
        widths = {row.count(CELL) for row in rows}
        if len(widths) != 1:
            continue  # rows of different widths: not a whole frame
        cols = widths.pop()
        if cols:
            geometries.append((cols, len(rows)))
    return geometries


def teardown_written(stream):
    """True when the stream contains both halves of the terminal restore."""
    return ALT_OFF in stream and SHOW_CURSOR in stream


class FirePty:
    """`python3 src/fire_main.py` running on a real PTY, plus a bounded reader.

    Contract:
      - `openpty()`; the window size is set on the slave BEFORE the spawn (so
        the child starts at that size and takes no SIGWINCH at startup) and can
        be changed later through the master fd;
      - `read(seconds)` pumps the master for AT MOST `seconds` and returns the
        bytes read in that call, accumulating them in `self.stream`; it stops
        early when `stop(self.stream)` is true or when the stream closes (the
        child is gone). It never blocks past its deadline;
      - `wait(timeout)` reaps the child and returns its exit code, continuing
        to drain the master while it waits (a child whose output nobody reads
        blocks in write() and stops responding to signals); a child still alive
        at the deadline is SIGKILLed and the test FAILS — the harness cannot
        hang;
      - `close()` (also run by `__exit__`) is the last-resort cleanup: SIGKILL
        + reap + close the master, so no child and no fd ever leaks.
    """

    def __init__(self, cols, rows):
        self.cols, self.rows = cols, rows
        self.pid = None
        self.master = None
        self.stream = b""
        self.exit_code = None  # set once the child has been reaped
        self.killed = False  # True when a SIGKILL was needed
        self._closed = False

    # --- lifecycle ---------------------------------------------------------

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def start(self):
        master, slave = pty.openpty()
        _set_winsize(slave, self.cols, self.rows)
        pid = os.fork()
        if pid == 0:
            _run_fire(slave, master)  # never returns
        self.pid = pid
        self.master = master
        os.close(slave)  # the parent keeps only the master

    # --- the raw stream ----------------------------------------------------

    def read(self, seconds, stop=None):
        """Pump the master for at most `seconds`; return what was read."""
        got = []
        deadline = time.monotonic() + seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                ready, _, _ = select.select([self.master], [], [], remaining)
            except OSError as exc:
                if exc.errno not in STREAM_CLOSED:
                    raise
                break
            if not ready:
                break  # the read window is over: bounded, never a hang
            try:
                data = os.read(self.master, READ_CHUNK)
            except OSError as exc:
                if exc.errno not in STREAM_CLOSED:
                    raise
                break  # EIO: the child closed the last slave reference
            if not data:
                break
            got.append(data)
            self.stream += data
            if stop is not None and stop(self.stream):
                break
        return b"".join(got)

    def set_size(self, cols, rows):
        """Resize the window through the master; the kernel signals the child."""
        self.cols, self.rows = cols, rows
        _set_winsize(self.master, cols, rows)

    # --- the child -----------------------------------------------------------

    def send_signal(self, sig):
        try:
            os.kill(self.pid, sig)
        except ProcessLookupError:
            pass  # already gone: the test's own assertions will say so

    def alive(self):
        """Reap if the child has exited; report whether it is still running."""
        if self.pid is None or self.exit_code is not None:
            return False
        pid, status = os.waitpid(self.pid, os.WNOHANG)
        if pid == 0:
            return True
        self.exit_code = os.waitstatus_to_exitcode(status)
        return False

    def wait(self, timeout=TEARDOWN_TIMEOUT):
        """Reap the child, bounded, while KEEPING ITS OUTPUT DRAINED.

        Draining while waiting is part of stopping, not an optimization: the
        child writes a whole frame per tick to the pty, and if the master is
        left unread the tty buffer fills and the child blocks inside write() —
        and a child blocked in write() cannot act on SIGINT until the buffer
        drains again. A parent that stops reading turns a graceful child into an
        apparently hung one.

        A child that outlives `timeout` is SIGKILLed and the test fails: a hung
        child must never turn into a hung test (ticket requirement 5).
        """
        deadline = time.monotonic() + timeout
        while True:
            if self.exit_code is not None:
                return self.exit_code
            self.read(0.05, stop=teardown_written)
            if not self.alive():
                self.read(0.05)  # whatever the child queued on its way out
                return self.exit_code
            if time.monotonic() >= deadline:
                self.kill()
                pytest.fail(
                    f"the child (pid {self.pid}) was still alive after "
                    f"{timeout}s; it was SIGKILLed"
                )
            time.sleep(0.01)

    def kill(self):
        """SIGKILL the child and reap it."""
        self.killed = True
        try:
            os.kill(self.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            _, status = os.waitpid(self.pid, 0)
            self.exit_code = os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            pass

    def close(self):
        """Last-resort cleanup: no child and no fd survives the test."""
        if self._closed:
            return
        self._closed = True
        if self.pid is not None and self.exit_code is None:
            self.kill()
        if self.master is not None:
            try:
                os.close(self.master)
            except OSError:
                pass
            self.master = None


# --- 1 + 4: the fire renders on the alt screen, and restores the terminal ----


def test_the_pty_stream_starts_with_the_alt_screen_and_paints_truecolor_cells():
    with FirePty(*INITIAL) as fire:
        fire.read(1.5)  # ~45 frames at the default 30 fps
        stream = fire.stream

        assert stream, "the child wrote nothing to the PTY"
        assert stream.startswith(ALT_ON), (
            "the stream must start with the alternate-screen enter, got "
            f"{stream[:24]!r}"
        )
        assert CELL in stream, "no half-block cell (U+2580) was rendered"
        assert FG in stream, "no truecolor foreground (SGR 38;2) was emitted"
        assert BG in stream, "no truecolor background (SGR 48;2) was emitted"

        # The frames are whole frames at the PTY's own window size: the child
        # read the size from the terminal, it did not guess it.
        geometries = frame_geometries(stream)
        assert geometries, "no complete frame in the stream"
        assert set(geometries) == {INITIAL}, (
            f"every frame must be {INITIAL[0]}x{INITIAL[1]}, got {set(geometries)}"
        )

        fire.send_signal(signal.SIGINT)
        assert fire.wait() == 0, "SIGINT must end the program with exit code 0"


def test_sigint_ends_the_child_cleanly_and_the_stream_carries_the_teardown():
    with FirePty(*INITIAL) as fire:
        fire.read(0.5)  # some frames, then stop it
        fire.send_signal(signal.SIGINT)
        code = fire.wait()  # wait() drains, so the teardown lands in the stream

        assert code == 0, f"graceful exit expected, got exit code {code}"
        assert SHOW_CURSOR in fire.stream, "the cursor must be shown again"
        assert ALT_OFF in fire.stream, "the alternate screen must be left"
        assert not fire.killed, "the child exited on its own; no SIGKILL was needed"


# --- 3: a resize is survived, and it is actually seen -------------------------


def test_a_resize_does_not_kill_the_child_and_it_keeps_rendering():
    with FirePty(*INITIAL) as fire:
        fire.read(0.6)
        assert set(frame_geometries(fire.stream)) == {INITIAL}, (
            "the fire must be painting at the initial window size first"
        )

        fire.set_size(*RESIZED)  # the kernel delivers SIGWINCH to the child
        after = fire.read(0.5)

        assert CELL in after, "the child must keep painting after a resize"
        assert fire.alive(), "SIGWINCH must not kill the child"
        # The new geometry is in the frames: the resize was applied, not ignored.
        assert RESIZED in set(frame_geometries(after)), (
            f"a frame must use the new {RESIZED[0]}x{RESIZED[1]} window, got "
            f"{set(frame_geometries(after))}"
        )

        fire.send_signal(signal.SIGINT)
        assert fire.wait() == 0, "the resized fire must still exit cleanly"


# --- 5: the harness itself cannot hang, and cannot leak a child --------------


def test_a_child_that_never_stops_is_killed_and_reaped_by_the_harness():
    fire = FirePty(*INITIAL)
    fire.start()
    try:
        fire.read(0.3)
        assert fire.alive(), "the child is running (no signal was sent)"
    finally:
        fire.close()  # no SIGINT was sent: close() must SIGKILL and reap it

    assert fire.killed, "close() must SIGKILL a child that is still running"
    assert fire.exit_code == -signal.SIGKILL, (
        f"the child must have been killed by SIGKILL, got {fire.exit_code}"
    )
    assert not fire.alive(), "no child may outlive the test"
