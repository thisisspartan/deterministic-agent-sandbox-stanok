"""End-to-end PTY integration test for the Doom fire (TASK-STANOK-CC-244 / FIRE-05).

No src/ code is under test here: this is the machine-side proof that the real
program (`python3 src/fire_main.py`) renders and sanitizes a REAL terminal,
spawned under a REAL pseudo-terminal built from the Python standard library
(`pty`, `os`, `signal`, `select`, `time`, `fcntl`, `termios`, `struct`) — no
node-pty, no third-party harness, no human eyeballing the screen.

Contract proven on the RAW byte stream read from the PTY master:

1. Spawn under a PTY: `pty.openpty()`, the slave is the child's
   stdin/stdout/stderr, `TERM=xterm-256color` in the child env, the window is
   80x24 via `fcntl.ioctl(fd, termios.TIOCSWINSZ, ...)`. The child runs with
   cwd = repo root so `src/` imports resolve.
2. The stream contains half-block cells (`b"\\xe2\\x96\\x80"` = ▀) and truecolor
   fg+bg (`b"\\x1b[38;2;"`, `b"\\x1b[48;2;"`), and it STARTS with the
   alternate-screen enter `b"\\x1b[?1049h"`.
3. Resize survival: a new TIOCSWINSZ on the master makes the kernel deliver
   SIGWINCH to the child; the child must keep producing frames (more ▀ bytes,
   now in the new geometry) and must NOT die.
4. Clean exit: SIGINT ends the loop; the child exits with code 0 and the
   stream contains the teardown `b"\\x1b[?25h"` + `b"\\x1b[?1049l"` — the
   terminal is restored.
5. No unbounded waits: every read is select-bounded by a deadline; a child
   that outlives its budget is SIGKILLed and the test fails.

Fixtures are defined in this file (no conftest.py).
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

# The child runs with cwd = repo root so `from src import ...` resolves.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# --- the byte-level contract -------------------------------------------------

HALF_BLOCK = b"\xe2\x96\x80"  # ▀, utf-8
TRUECOLOR_FG = b"\x1b[38;2;"
TRUECOLOR_BG = b"\x1b[48;2;"
ALT_SCREEN_ENTER = b"\x1b[?1049h"
ALT_SCREEN_EXIT = b"\x1b[?1049l"
CURSOR_SHOW = b"\x1b[?25h"
FRAME_HOME = b"\x1b[H"

INITIAL_SIZE = (80, 24)  # cols, rows
RESIZED_SIZE = (60, 12)

# Read budgets (seconds). Every read is bounded; nothing here can hang.
FIRST_READ = 1.5
PRE_RESIZE_READ = 0.8
RESIZE_READ = 0.5
EXIT_READ = 2.0
REAP_TIMEOUT = 5.0

READ_CHUNK = 65536


# --- PTY harness --------------------------------------------------------------


def _set_winsize(fd, cols, rows):
    """TIOCSWINSZ on a PTY fd; the kernel signals SIGWINCH to the child."""
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


def _spawn_fire(cols, rows):
    """Spawn `python3 src/fire_main.py` under a fresh PTY -> (pid, master_fd).

    The slave becomes the child's stdin/stdout/stderr and its controlling
    terminal (setsid + TIOCSCTTY), so the kernel delivers SIGWINCH to the
    child when the window size changes. COLUMNS/LINES are removed from the
    child env so the program reads its size from the PTY, not the shell.
    """
    master, slave = pty.openpty()
    _set_winsize(slave, cols, rows)

    env = dict(os.environ)
    env["TERM"] = "xterm-256color"
    env.pop("COLUMNS", None)
    env.pop("LINES", None)

    # sys.executable IS the python3 running this suite; the script path is
    # relative because the child chdir's to the repo root.
    argv = [sys.executable, os.path.join("src", "fire_main.py")]

    pid = os.fork()
    if pid == 0:  # child
        try:
            os.close(master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            os.chdir(REPO_ROOT)
            os.execvpe(argv[0], argv, env)
        except BaseException:
            os._exit(127)  # exec failed: the parent sees a dead child
    os.close(slave)  # the parent keeps only the master
    return pid, master


def _read_bounded(master, seconds, sink):
    """Read raw bytes from the master for AT MOST `seconds`. -> bytes read.

    select() bounds every wait by the remaining budget; EIO/EOF (the child is
    gone) ends the read early. Never blocks past the deadline.
    """
    deadline = time.monotonic() + seconds
    total = 0
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return total
        try:
            ready, _, _ = select.select([master], [], [], remaining)
        except InterruptedError:
            continue
        if not ready:
            return total
        try:
            data = os.read(master, READ_CHUNK)
        except OSError as exc:  # EIO: the slave side has gone away
            if exc.errno in (errno.EIO, errno.EBADF):
                return total
            raise
        if not data:
            return total
        sink.extend(data)
        total += len(data)


def _exited_status(pid):
    """Reap the child if it is already dead -> its wait status, else None."""
    try:
        done, status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:  # already reaped
        return None
    return status if done == pid else None


def _assert_alive(pid, what):
    status = _exited_status(pid)
    if status is not None:
        pytest.fail(f"fire_main.py died unexpectedly {what} (status={status:#06x})")


def _reap(pid, timeout=REAP_TIMEOUT):
    """Wait for the child to exit. A child that outlives the budget is
    SIGKILLed and the test FAILS (the harness must never hang)."""
    deadline = time.monotonic() + timeout
    while True:
        status = _exited_status(pid)
        if status is not None:
            return status
        if time.monotonic() >= deadline:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            _, status = os.waitpid(pid, 0)
            pytest.fail(
                "fire_main.py was still alive after SIGINT "
                f"({timeout}s budget) — killed with SIGKILL"
            )
        time.sleep(0.02)


def _interrupt_and_reap(pid, master, sink):
    """SIGINT the child, capture what it writes while tearing down, reap it."""
    os.kill(pid, signal.SIGINT)
    _read_bounded(master, EXIT_READ, sink)
    return _reap(pid)


def _cleanup(pid, master):
    """Last line of defense: no child and no fd survives the test."""
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass
    try:
        os.close(master)
    except OSError:
        pass


def _assert_clean_exit(status):
    assert os.WIFEXITED(status), f"child did not exit normally: status={status:#06x}"
    assert os.WEXITSTATUS(status) == 0, (
        f"child exited with code {os.WEXITSTATUS(status)}, expected 0"
    )


def _assert_terminal_restored(stream):
    """The teardown sequence: cursor shown, alternate screen left."""
    assert CURSOR_SHOW in stream, "no cursor-restore (\\x1b[?25h) in the stream"
    assert ALT_SCREEN_EXIT in stream, "no alt-screen leave (\\x1b[?1049l) in the stream"


def _frame_cell_counts(stream):
    """Half-block cells per frame: a frame starts at HOME, so splitting the
    stream on HOME recovers frame boundaries (the last one may be partial)."""
    return [chunk.count(HALF_BLOCK) for chunk in stream.split(FRAME_HOME)][1:]


# --- 1+2+4: the fire renders, in truecolor, on the alternate screen ----------


def test_fire_renders_half_blocks_in_truecolor_under_a_pty():
    pid, master = _spawn_fire(*INITIAL_SIZE)
    stream = bytearray()
    try:
        _read_bounded(master, FIRST_READ, stream)
        _assert_alive(pid, "during the first read")

        # Half-block rendering is actually happening.
        assert stream.count(HALF_BLOCK) > 0, "no ▀ half-block bytes on the PTY"
        # Truecolor foreground AND background.
        assert stream.count(TRUECOLOR_FG) > 0, "no truecolor fg (\\x1b[38;2;)"
        assert stream.count(TRUECOLOR_BG) > 0, "no truecolor bg (\\x1b[48;2;)"
        # The session opens on the alternate screen.
        assert stream.startswith(ALT_SCREEN_ENTER), (
            f"stream does not start with the alt-screen enter: {bytes(stream[:16])!r}"
        )
        # The initial geometry is in use: 80 cols x 24 terminal rows.
        assert INITIAL_SIZE[0] * INITIAL_SIZE[1] in _frame_cell_counts(stream)

        status = _interrupt_and_reap(pid, master, stream)
    finally:
        _cleanup(pid, master)

    _assert_clean_exit(status)
    _assert_terminal_restored(stream)


# --- 3: a kernel-side resize (SIGWINCH) does not break the loop --------------


def test_fire_survives_a_pty_resize_and_repaints_the_new_geometry():
    pid, master = _spawn_fire(*INITIAL_SIZE)
    stream = bytearray()
    try:
        _read_bounded(master, PRE_RESIZE_READ, stream)
        before = stream.count(HALF_BLOCK)
        assert before > 0, "no frames before the resize"
        _assert_alive(pid, "before the resize")

        # TIOCSWINSZ on the master -> the kernel delivers SIGWINCH to the child.
        _set_winsize(master, *RESIZED_SIZE)
        _read_bounded(master, RESIZE_READ, stream)

        after = stream.count(HALF_BLOCK)
        _assert_alive(pid, "after the resize")
        assert after > before, "the child stopped producing frames after the resize"
        # The new geometry is in use: 60 cols x 12 terminal rows = 720 cells.
        assert RESIZED_SIZE[0] * RESIZED_SIZE[1] in _frame_cell_counts(stream), (
            "no frame in the resized geometry"
        )

        status = _interrupt_and_reap(pid, master, stream)
    finally:
        _cleanup(pid, master)

    _assert_clean_exit(status)
    _assert_terminal_restored(stream)
