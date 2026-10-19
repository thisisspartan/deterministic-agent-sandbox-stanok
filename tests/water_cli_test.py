"""CC-301 — water_cli reference tests (contract: docs/water_cli.md, C1..C5).

Two harnesses, both real:
  - C1/C2/C5 run the CLI as a subprocess (`python -B src/water_cli.py ...`)
    with a pipe stdout: usage/exit codes, and the pipe-mode byte stream
    compared against a direct water_engine+water_render call;
  - C3/C4 run the CLI on a REAL PTY (pty.openpty + os.fork, the DOOMFIRE
    precedent) with a REAL SIGINT/SIGTERM: the alt-buffer open/close and
    cursor hide/show must appear EXACTLY once in the bytes the terminal
    actually received. The CLI prints the protocol itself — nothing here
    re-implements it.

Every spawn passes --width 12 --height 4 --seed 1 explicitly.
"""

import fcntl
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import time
from pathlib import Path

import pytest

import water_cli as cli
import water_engine as engine
import water_render as render

ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = str(ROOT / "src" / "water_cli.py")
PY = sys.executable

# Protocol literals (C3) — the CLI must emit these bytes itself.
ENTER_ALT = "\x1b[?1049h"
HIDE_CURSOR = "\x1b[?25l"
HOME = "\x1b[H"
EXIT_ALT = "\x1b[?1049l"
SHOW_CURSOR = "\x1b[?25h"
NO_TTY_LITERAL = "water: no terminal and no --frames"

WIDTH, HEIGHT, SEED = 12, 4, 1
BASE = ["--seed", str(SEED), "--width", str(WIDTH), "--height", str(HEIGHT)]


# ---------------------------------------------------------------------------
# Harnesses
# ---------------------------------------------------------------------------

def _run(args):
    """Run the CLI with a pipe stdout (never a TTY)."""
    return subprocess.run(
        [PY, "-B", CLI_PATH] + args,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
    )


def _expected_frames(seed, width, height, count):
    """Direct engine+render reference: frames t = 0..count-1."""
    params = engine.make_params(seed)
    return [
        render.render_frame(engine.frame_state(params, t, width), width, height)
        for t in range(count)
    ]


def _pty_run(args, sig=None, sig_after=1.0, timeout=20.0):
    """Spawn the CLI on a REAL PTY; optionally deliver `sig` after sig_after.

    -> (bytes the terminal received with ONLCR undone, exit code).
    """
    master, slave = pty.openpty()
    pid = os.fork()
    if pid == 0:  # child: new session, PTY slave as 0/1/2
        try:
            os.close(master)
            os.setsid()
            try:
                fcntl.ioctl(slave, termios.TIOCSCTTY, 1)
            except OSError:
                pass
            for fd in (0, 1, 2):
                os.dup2(slave, fd)
            if slave > 2:
                os.close(slave)
            os.execv(PY, [PY, "-B", CLI_PATH] + args)
        except BaseException:
            os._exit(127)
    os.close(slave)
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    data = b""
    t0 = time.monotonic()
    sent = False
    while True:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(master, 65536)
            except BlockingIOError:
                chunk = None
            except OSError:  # EIO once the child's side is gone
                chunk = b""
            if chunk is None:
                pass
            elif not chunk:
                break
            else:
                data += chunk
        if sig is not None and not sent and time.monotonic() - t0 > sig_after:
            os.kill(pid, sig)
            sent = True
        if time.monotonic() - t0 > timeout:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            break
    try:
        os.close(master)
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    return data.replace(b"\r\n", b"\n"), os.waitstatus_to_exitcode(status)


def _assert_protocol(text, frames):
    """C3 byte protocol: open/hide once, home before EVERY frame, close/show
    once at the very end, and each payload equal to the render output."""
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) == len(frames)
    assert text.find(ENTER_ALT) < text.find(HOME)
    assert text.find(EXIT_ALT) > text.rfind(HOME)
    tail = text.rsplit(EXIT_ALT, 1)[1]
    assert tail.count(SHOW_CURSOR) == 1
    assert tail.replace(SHOW_CURSOR, "").strip() == ""
    segments = text.split(HOME)
    payloads = segments[1:-1] + [segments[-1].rsplit(EXIT_ALT, 1)[0]]
    assert len(payloads) == len(frames)
    for payload, expected in zip(payloads, frames):
        assert payload.rstrip("\r\n") == expected


class _FakeStream:
    def __init__(self, isatty=False):
        self.buf = []
        self._isatty = isatty

    def isatty(self):
        return self._isatty

    def write(self, s):
        self.buf.append(s)
        return len(s)

    def flush(self):
        pass

    def text(self):
        return "".join(self.buf)


class _Clock:
    """Virtual clock; raises water_cli._SignalQuit from monotonic() at a
    pinned call index (galaxian precedent)."""

    def __init__(self, raise_at=None):
        self.now = 0.0
        self.calls = 0
        self.raise_at = raise_at

    def monotonic(self):
        self.calls += 1
        if self.raise_at is not None and self.calls >= self.raise_at:
            raise cli._SignalQuit()
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------
# C1 — options, usage, exit codes
# ---------------------------------------------------------------------------

USAGE_CASES = [
    ["--width", "11"],
    ["--width", "201"],
    ["--height", "3"],
    ["--height", "61"],
    ["--seed", "-1"],
    ["--frames", "0"],
    ["--fps", "0"],
    ["--fps", "61"],
    ["--not-an-option", "1"],
    ["--width", "abc"],
]


@pytest.mark.parametrize("bad", USAGE_CASES)
def test_C1_out_of_range_or_unknown_is_usage_rc2(bad):
    proc = _run(BASE + ["--frames", "1"] + bad)
    assert proc.returncode == 2, bad
    assert proc.stdout == b"", bad
    assert b"usage" in proc.stderr.lower(), bad


def test_C1_help_is_usage_on_stdout_rc0():
    proc = _run(["--help"])
    assert proc.returncode == 0
    assert b"usage" in proc.stdout.lower()
    assert proc.stderr == b""


def test_C1_defaults_are_in_range():
    """No width/height/fps given (pipe stdout -> no terminal size): the
    defaults 80x24/fps 24 are accepted, not rejected as usage."""
    proc = _run(["--seed", "1", "--frames", "1"])
    assert proc.returncode == 0
    assert proc.stdout.decode("utf-8").count("\n") == 24


# ---------------------------------------------------------------------------
# C2 — pipe mode: exactly the render bytes
# ---------------------------------------------------------------------------

PIPE_ARGS = BASE + ["--frames", "3"]


def test_C2_pipe_mode_is_render_bytes():
    proc = _run(PIPE_ARGS)
    assert proc.returncode == 0
    out = proc.stdout.decode("utf-8")
    assert out.endswith("\n")
    lines = out.split("\n")[:-1]  # a trailing newline is not a line
    assert len(lines) == 3 * HEIGHT
    for line in lines:
        assert "38;2;" in line
    assert "1049" not in out
    assert "25l" not in out and "25h" not in out
    assert HOME not in out
    expected = "\n".join(_expected_frames(SEED, WIDTH, HEIGHT, 3)) + "\n"
    assert out == expected


def test_C2_same_argv_same_bytes():
    a = _run(PIPE_ARGS)
    b = _run(PIPE_ARGS)
    assert a.returncode == b.returncode == 0
    assert a.stdout == b.stdout


def test_C2_single_frame():
    proc = _run(BASE + ["--frames", "1"])
    assert proc.returncode == 0
    assert proc.stdout.decode("utf-8") == (
        "\n".join(_expected_frames(SEED, WIDTH, HEIGHT, 1)) + "\n"
    )


# ---------------------------------------------------------------------------
# C5 — no terminal and no --frames
# ---------------------------------------------------------------------------

def test_C5_no_terminal_and_no_frames_is_rc3():
    proc = _run(BASE)
    assert proc.returncode == 3
    assert NO_TTY_LITERAL in proc.stderr.decode("utf-8")
    assert proc.stdout == b""


# ---------------------------------------------------------------------------
# C3 — TTY mode on a REAL PTY: bounded run, teardown exactly once
# ---------------------------------------------------------------------------

def test_C3_tty_bounded_protocol_exactly_once():
    data, code = _pty_run(BASE + ["--frames", "2", "--fps", "30"])
    assert code == 0
    text = data.decode("utf-8", errors="replace")
    _assert_protocol(text, _expected_frames(SEED, WIDTH, HEIGHT, 2))
    assert data.count(HOME.encode()) == 2


def test_C3_tty_frame_payloads_are_truecolor():
    data, code = _pty_run(BASE + ["--frames", "2", "--fps", "30"])
    assert code == 0
    text = data.decode("utf-8", errors="replace")
    for payload in text.split(HOME)[1:]:
        assert "38;2;" in payload


# ---------------------------------------------------------------------------
# C4 — SIGINT / SIGTERM: graceful rc 0, teardown exactly once
# ---------------------------------------------------------------------------

def test_C4_sigint_exits_zero_with_teardown_once():
    data, code = _pty_run(BASE + ["--fps", "30"], sig=signal.SIGINT)
    assert code == 0
    text = data.decode("utf-8", errors="replace")
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) >= 1
    assert text.find(ENTER_ALT) < text.find(HOME)
    assert text.find(EXIT_ALT) > text.rfind(HOME)
    tail = text.rsplit(EXIT_ALT, 1)[1]
    assert tail.count(SHOW_CURSOR) == 1
    assert tail.replace(SHOW_CURSOR, "").strip() == ""


def test_C4_sigterm_exits_zero_with_teardown_once():
    data, code = _pty_run(BASE + ["--fps", "30"], sig=signal.SIGTERM)
    assert code == 0
    text = data.decode("utf-8", errors="replace")
    assert text.count(ENTER_ALT) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) >= 1
    assert text.find(EXIT_ALT) > text.rfind(HOME)


# ---------------------------------------------------------------------------
# API — run_loop with injected sleep/monotonic (deterministic counts)
# ---------------------------------------------------------------------------

def test_API_run_loop_finite_frames_protocol():
    out = _FakeStream(isatty=True)
    clock = _Clock()
    rc = cli.run_loop(_FakeStream(), out, seed=SEED, width=WIDTH, height=HEIGHT,
                      frames=2, fps=30, sleep=clock.sleep, monotonic=clock.monotonic)
    assert rc == 0
    _assert_protocol(out.text(), _expected_frames(SEED, WIDTH, HEIGHT, 2))


def test_API_run_loop_signal_quit_is_once_and_zero():
    out = _FakeStream(isatty=True)
    clock = _Clock(raise_at=2)  # raised while waiting after the first frame
    rc = cli.run_loop(_FakeStream(), out, seed=SEED, width=WIDTH, height=HEIGHT,
                      frames=None, fps=30, sleep=clock.sleep, monotonic=clock.monotonic)
    assert rc == 0
    text = out.text()
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) >= 1
    assert text.find(EXIT_ALT) > text.rfind(HOME)


def test_API_run_loop_pipe_mode_has_no_protocol_bytes():
    out = _FakeStream(isatty=False)
    clock = _Clock()
    rc = cli.run_loop(_FakeStream(), out, seed=SEED, width=WIDTH, height=HEIGHT,
                      frames=2, fps=30, sleep=clock.sleep, monotonic=clock.monotonic)
    assert rc == 0
    text = out.text()
    assert text == "\n".join(_expected_frames(SEED, WIDTH, HEIGHT, 2)) + "\n"
    assert "1049" not in text and HOME not in text and "25l" not in text
