"""Calibrated contract oracle for src/water_cli.py (SPEC-WATER-CONSOLE C1..C5).

Independence policy: usage/exit codes, pipe structure, alt-buffer/teardown
byte protocols are checked against SPEC literals/counts. The pipe-mode
byte-equivalence CLI-stdout == render output is the C2 contract claim
itself (cross-module equivalence property), checked against the render
module of the tree. Terminal boundary (C3/C4) is tested on a REAL PTY
(os.forkpty) and a REAL SIGINT/SIGTERM, plus an in-process run_loop check
with injected sleep/monotonic (deterministic exactly-once protocol counts).

Calibration: lab /tmp/oracle-lab-water, mutants MC1..MC6 — see specs/STATUS.md
tables. GREEN on reference, RED on targeted mutants.
"""
import fcntl
import os
import re
import select
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

import water_cli as c
import water_engine as g
import water_render as rr

ROOT = Path(__file__).resolve().parents[1]
CLI = str(ROOT / "src" / "water_cli.py")
PY = sys.executable

ENTER_ALT = "\x1b[?1049h"
HIDE_CURSOR = "\x1b[?25l"
HOME = "\x1b[H"
EXIT_ALT = "\x1b[?1049l"
SHOW_CURSOR = "\x1b[?25h"
NO_TTY_LITERAL = "water: no terminal and no --frames"
SEG_RE = re.compile(
    r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m(.)", re.DOTALL
)


def _run(args):
    return subprocess.run([PY, "-B", CLI] + args, capture_output=True, timeout=60)


def _expected_frames(seed, width, height, count):
    out = []
    p = g.make_params(seed)
    for t in range(count):
        out.append(rr.render_frame(g.frame_state(p, t, width), width, height))
    return out


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
    """Injectable virtual clock; raises water_cli._SignalQuit at a pinned
    monotonic() call index (galaxian precedent)."""

    def __init__(self, raise_at=None):
        self.now = 0.0
        self.n = 0
        self.raise_at = raise_at

    def monotonic(self):
        self.n += 1
        if self.raise_at is not None and self.n >= self.raise_at:
            raise c._SignalQuit()
        return self.now

    def sleep(self, d):
        self.now += d


def _assert_protocol_and_frames(text, expected_frames):
    n = len(expected_frames)
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) == n
    assert text.find(ENTER_ALT) < text.find(HOME)
    assert text.find(EXIT_ALT) > text.rfind(HOME)
    # last protocol token only at the end
    after = text.rsplit(EXIT_ALT, 1)
    tail = after[1]
    assert tail.count(SHOW_CURSOR) == 1
    assert tail.replace(SHOW_CURSOR, "").strip() == ""
    # per-frame payloads
    segs = text.split(HOME)
    payloads = segs[1:-1] + [segs[-1].rsplit(EXIT_ALT, 1)[0]]
    assert len(payloads) == n
    for seg, exp in zip(payloads, expected_frames):
        assert seg.rstrip("\r\n") == exp


# ---------------- C1: usage / exit codes (real subprocess) ----------------

USAGE_CASES = [
    ["--width", "11"], ["--width", "201"], ["--height", "3"], ["--height", "61"],
    ["--seed", "-1"], ["--frames", "0"], ["--fps", "0"], ["--fps", "61"],
    ["--bogus", "1"], ["--width", "abc"],
]


def test_C1_usage_and_exit_codes():
    for args in USAGE_CASES:
        p = _run(["--seed", "1", "--width", "12", "--height", "4"] + args)
        assert p.returncode == 2, args
        assert p.stdout == b"", args
        assert b"usage" in p.stderr.lower(), args


def test_C1_help():
    p = _run(["--help"])
    assert p.returncode == 0
    assert b"usage" in p.stdout.lower()


# ---------------- C2: pipe-mode structure and equivalence ----------------

PIPE_ARGS = ["--seed", "1", "--width", "12", "--height", "4", "--frames", "2"]


def test_C2_pipe_mode_bytes_equal_render():
    p = _run(PIPE_ARGS)
    assert p.returncode == 0
    out = p.stdout.decode()
    assert out.endswith("\n")
    lines = out.split("\n")[:-1]  # 8 content lines; trailing newline not a line
    assert len(lines) == 8
    for line in lines:
        assert "38;2;" in line
    assert "1049" not in out and "25l" not in out and "25h" not in out
    assert HOME not in out
    expected = "\n".join(_expected_frames(1, 12, 4, 2)) + "\n"
    assert out == expected  # C2 equivalence claim: pipe stream == render output


def test_C2_two_runs_identical():
    a = _run(PIPE_ARGS)
    b = _run(PIPE_ARGS)
    assert a.stdout == b.stdout and a.returncode == b.returncode == 0


# ---------------- C5: no terminal, no frames ----------------

def test_C5_no_tty_no_frames():
    p = _run(["--seed", "1", "--width", "12", "--height", "4"])
    assert p.returncode == 3
    assert NO_TTY_LITERAL in p.stderr.decode()


# ---------------- C3/C4 in-process: exactly-once protocol via run_loop ----------------

def test_run_loop_finite_frames_protocol():
    out = _FakeStream(isatty=True)
    clk = _Clock()
    rc = c.run_loop(_FakeStream(), out, seed=1, width=12, height=4, frames=2,
                    fps=30, sleep=clk.sleep, monotonic=clk.monotonic)
    assert rc == 0
    _assert_protocol_and_frames(out.text(), _expected_frames(1, 12, 4, 2))


def test_run_loop_signal_quit_once():
    out = _FakeStream(isatty=True)
    clk = _Clock(raise_at=2)  # raise during the delay wait after frame 1
    rc = c.run_loop(_FakeStream(), out, seed=1, width=12, height=4, frames=None,
                    fps=30, sleep=clk.sleep, monotonic=clk.monotonic)
    assert rc == 0
    text = out.text()
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.count(HOME) >= 1
    assert text.find(EXIT_ALT) > text.rfind(HOME)


# ---------------- C3/C4 on REAL PTY ----------------

def _pty_run(args, sig=None, sig_after=1.2, timeout=25.0):
    pid, master = os.forkpty()
    if pid == 0:
        os.execv(PY, [PY, "-B", CLI] + args)
    fcntl.fcntl(master, fcntl.F_SETFL, os.O_NONBLOCK)
    data = b""
    t0 = time.monotonic()
    sent = False
    while True:
        ready, _, _ = select.select([master], [], [], 0.1)
        if ready:
            try:
                chunk = os.read(master, 65536)
            except OSError:
                chunk = b""
            if not chunk:
                break
            data += chunk
        if sig is not None and not sent and time.monotonic() - t0 > sig_after:
            os.kill(pid, sig)
            sent = True
        if time.monotonic() - t0 > timeout:
            os.kill(pid, signal.SIGKILL)
            break
    try:
        os.close(master)
    except OSError:
        pass
    _, status = os.waitpid(pid, 0)
    code = os.waitstatus_to_exitcode(status)
    # undo terminal output translation (ONLCR inserts \r before \n)
    return data.replace(b"\r\n", b"\n"), code


def _check_pty_protocol(data, min_frames):
    text = data.decode(errors="replace")
    assert text.count(ENTER_ALT) == 1
    assert text.count(HIDE_CURSOR) == 1
    assert text.count(EXIT_ALT) == 1
    assert text.count(SHOW_CURSOR) == 1
    assert text.find(ENTER_ALT) < text.find(HOME)
    assert text.count(HOME) >= min_frames
    assert text.find(EXIT_ALT) > text.rfind(HOME)
    tail = text.rsplit(EXIT_ALT, 1)[1]
    assert tail.count(SHOW_CURSOR) == 1 and tail.replace(SHOW_CURSOR, "").strip() == ""


def test_C3_tty_bounded_teardown_once():
    data, code = _pty_run(["--seed", "1", "--width", "12", "--height", "4",
                           "--frames", "2", "--fps", "30"])
    assert code == 0
    _check_pty_protocol(data, min_frames=2)
    assert data.count(HOME.encode()) == 2


def test_C4_sigint_graceful_once():
    data, code = _pty_run(["--seed", "1", "--width", "12", "--height", "4",
                           "--fps", "30"], sig=signal.SIGINT)
    assert code == 0
    _check_pty_protocol(data, min_frames=1)


def test_C4_sigterm_graceful_once():
    data, code = _pty_run(["--seed", "1", "--width", "12", "--height", "4",
                           "--fps", "30"], sig=signal.SIGTERM)
    assert code == 0
    _check_pty_protocol(data, min_frames=1)
