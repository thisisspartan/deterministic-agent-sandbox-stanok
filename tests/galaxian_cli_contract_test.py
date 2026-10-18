"""Host-authored contract oracle for src/galaxian_cli.py (PLAN-ORACLE-PRACTICE, 2026-10-18).

Independence policy (specs/MEMO-CODE-QUALITY-ORACLES-2026-10-18.md): every
expected value here is a literal transcribed from specs/SPEC-GALAXIAN.md R3 /
docs/galaxian_cli.md — the production module is never used to COMPUTE an
expectation (it only builds inputs or is the subject under test). The
boundary claims (real PTY, real SIGINT, real EOF, termios restore) run the
CLI as a real subprocess on a real pty — no monkeypatched isatty for those.

Calibration (RED on mutants / GREEN on the reference tree) — executed 2026-10-18
in /tmp/oracle-lab (each mutant = a copy of the ref tree with ONE line changed
in src/galaxian_cli.py only; every mutant reddened EXACTLY its target test):
  M9  swap 'a'/'d' in _KEY_COMMANDS       -> RED test_r3_parse_keys_decodes_the_pinned_key_map
  M10 termios restore call removed        -> RED test_r3_quit_wins_bounded_and_real_pty_termios_restored
  M11 interactive home gate removed       -> RED test_r3_interactive_tty_stdout_homes_every_frame
  M12 quit ignored in _apply_commands     -> RED test_r3_quit_wins_bounded_and_real_pty_termios_restored
  M13 SIGINT handler registration removed -> RED test_r3_real_sigint_exits_rc_0
  M14 non-TTY EOF return removed          -> RED test_r3_real_eof_on_non_tty_stdin_exits_rc_0 (hang -> timeout)
Reference tree: 9 passed. Full evidence: STATUS.md PLAN-ORACLE-PRACTICE section.
"""

import os
import pathlib
import select
import signal
import subprocess
import sys
import termios
import time

import galaxian_cli as c  # noqa: E402  (pythonpath=src)

REF_ROOT = pathlib.Path(__file__).resolve().parents[1]

HOME = "\x1b[H"  # pinned by SPEC-GALAXIAN R3 / docs
WIDTH, HEIGHT = 32, 24  # CLI defaults, pinned
FRAME_LINES = 14  # height // 2 + 2 = 24 // 2 + 2 (SPEC-GALAXIAN R2)
NEWLINES_2FR = 2 * FRAME_LINES  # 13 internal + 1 trailing per frame


def _run_cli_interactive(*, stdin_mode, extra_args=()):
    """Spawn the real CLI in interactive mode. stdin_mode: 'pty' | 'pipe'.
    For 'pty' returns (proc, master_fd); for 'pipe' returns (proc, None) with
    stdin closed immediately (EOF)."""
    cmd = [sys.executable, "-m", "galaxian_cli", *extra_args]
    env = dict(os.environ, PYTHONPATH=str(REF_ROOT / "src"))
    if stdin_mode == "pipe":
        return subprocess.run(
            cmd, cwd=REF_ROOT, env=env, capture_output=True, timeout=10, input=b""
        ), None
    master, slave = os.openpty()
    proc = subprocess.Popen(
        cmd, cwd=REF_ROOT, env=env, stdin=slave, stdout=slave, stderr=subprocess.PIPE,
        close_fds=True,
    )
    os.close(slave)
    return proc, master


def _read_until_newlines(master, count, timeout=10.0):
    """Read master bytes until at least `count` newlines arrived."""
    data = b""
    end = time.monotonic() + timeout
    while data.count(b"\n") < count:
        left = end - time.monotonic()
        if left <= 0:
            raise AssertionError(f"timed out; got {data!r}")
        try:
            ready = select.select([master], [], [], left)[0]
            if not ready:
                continue
            chunk = os.read(master, 4096)
        except OSError:  # child gone (EIO on Linux)
            raise AssertionError(f"child closed early; got {data!r}")
        data += chunk
    return data


class _FakeStream:
    """Duck-typed stream for non-boundary tests: scripted drain, capture."""

    def __init__(self, scripts=(), tty=False):
        self._chunks = list(scripts)
        self._buf = b""
        self._tty = tty
        self.out = ""

    def isatty(self):
        return self._tty

    def read(self, n=1):
        while not self._buf and self._chunks:
            self._buf = self._chunks.pop(0)
        if not self._buf:
            return b""
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def write(self, s):
        self.out += s

    def flush(self):
        pass


class _Clock:
    """Injectable monotonic: always-increasing clock; raises _SignalQuit at a
    pinned call index to end the interactive loop deterministically."""

    def __init__(self, raise_at):
        self.n = 0
        self.raise_at = raise_at

    def __call__(self):
        self.n += 1
        if self.n == self.raise_at:
            raise c._SignalQuit()
        return float(self.n)


# --------------------------------------------------------------------------
# T1 — parse_keys: the pinned key map, exact byte -> command literals (M9)
# --------------------------------------------------------------------------

def test_r3_parse_keys_decodes_the_pinned_key_map():
    # single keys -> exact commands (literals from SPEC R3 / docs)
    assert c.parse_keys(b"a") == [("move", -1)]
    assert c.parse_keys(b"d") == [("move", 1)]
    assert c.parse_keys(b" ") == [("fire", None)]
    assert c.parse_keys(b"w") == [("fire", None)]
    assert c.parse_keys(b"q") == [("quit", None)]
    assert c.parse_keys(b"\x03") == [("quit", None)]
    # arrows are the 3-byte CSI sequences, parsed as whole sequences
    assert c.parse_keys(b"\x1b[D") == [("move", -1)]
    assert c.parse_keys(b"\x1b[C") == [("move", 1)]
    assert c.parse_keys(b"\x1b[A") == [("fire", None)]
    # mixed order is preserved, arrows consume 3 bytes
    assert c.parse_keys(b"\x1b[C\x1b[A\x1b[D") == [
        ("move", 1), ("fire", None), ("move", -1)
    ]
    assert c.parse_keys(b"a\x1b[Az") == [("move", -1), ("fire", None)]  # 'z' ignored
    assert c.parse_keys(b"dq\x03") == [("move", 1), ("quit", None), ("quit", None)]
    # negative cases: lone ESC / partial / unmodelled escapes and unknown bytes
    # are skipped byte by byte, never turned into commands
    assert c.parse_keys(b"") == []
    assert c.parse_keys(b"\x1b") == []
    assert c.parse_keys(b"\x1b[") == []
    assert c.parse_keys(b"\x1b[Z") == []
    assert c.parse_keys(b"z\x001") == []


# --------------------------------------------------------------------------
# T2 — bounded mode: exact N frames, NEVER home/clear even on TTY stdout
# --------------------------------------------------------------------------

def test_r3_bounded_mode_emits_exact_frames_and_never_homes_even_on_tty_stdout():
    out = _FakeStream(tty=True)
    rc = c.run_loop(_FakeStream(), out, seed=1, width=WIDTH, height=HEIGHT, ticks=2)
    assert rc == 0
    assert HOME not in out.out  # pinned R3: --ticks NEVER homes, even on a TTY
    assert out.out.count("\n") == NEWLINES_2FR  # exactly 2 complete frames


def test_r3_bounded_mode_under_real_tty_stdout_never_homes():
    """Real boundary: the CLI run with a real pty as stdout. --ticks must not
    home/clear/hide even though stdout.isatty() is true in the child."""
    cmd = [sys.executable, "-m", "galaxian_cli", "--ticks", "2"]
    env = dict(os.environ, PYTHONPATH=str(REF_ROOT / "src"))
    master, slave = os.openpty()
    proc = subprocess.Popen(
        cmd, cwd=REF_ROOT, env=env, stdin=subprocess.DEVNULL, stdout=slave,
        stderr=subprocess.PIPE, close_fds=True,
    )
    os.close(slave)
    try:
        out = _read_until_newlines(master, NEWLINES_2FR)
        _, err = proc.communicate(timeout=10)
        assert proc.returncode == 0, err
        assert b"\x1b[H" not in out, out  # never homes, even on a real TTY
        assert out.count(b"\n") == NEWLINES_2FR  # exactly 2 frames on the wire
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


# --------------------------------------------------------------------------
# T_Q — quit contract: bounded first-quit-wins + REAL PTY q -> rc 0 with
# termios restored (targets M10, M12)
# --------------------------------------------------------------------------

def test_r3_quit_wins_bounded_and_real_pty_termios_restored():
    # bounded: commands apply in order, the FIRST quit ends with rc 0 and NO frames
    out = _FakeStream()
    rc = c.run_loop(
        _FakeStream([b"aqa"]), out, seed=1, width=WIDTH, height=HEIGHT, ticks=1
    )
    assert rc == 0
    assert out.out == ""  # no frame after a quit

    # real boundary: the CLI on a real pty, raw-mode borrowed and restored
    proc, master = _run_cli_interactive(stdin_mode="pty")
    try:
        base = termios.tcgetattr(master)[3]
        assert base & (termios.ICANON | termios.ECHO), "pty must start cooked"
        _read_until_newlines(master, FRAME_LINES)  # first frame proves it runs
        os.write(master, b"q")  # real cooked->raw keypress on a real terminal
        _, err = proc.communicate(timeout=10)
        assert proc.returncode == 0, err
        after = termios.tcgetattr(master)[3]
        # termios must be RESTORED: ICANON and ECHO back on
        assert after & (termios.ICANON | termios.ECHO) == base & (
            termios.ICANON | termios.ECHO
        ), "termios not restored after q quit"
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


# --------------------------------------------------------------------------
# T4 — interactive on TTY stdout: every frame, including the first, is
# prefixed with ESC[H (M11)
# --------------------------------------------------------------------------

def test_r3_interactive_tty_stdout_homes_every_frame():
    out = _FakeStream(tty=True)
    clock = _Clock(raise_at=6)  # exactly 2 frames, then a clean _SignalQuit exit
    rc = c.run_loop(
        _FakeStream(), out, seed=1, width=WIDTH, height=HEIGHT,
        ticks=None, sleep=lambda s: None, monotonic=clock,
    )
    assert rc == 0
    parts = out.out.split(HOME)
    assert parts[0] == ""  # the FIRST frame is home-prefixed too
    assert len(parts) == 3  # exactly one HOME per frame, 2 frames
    for frame in parts[1:]:
        assert frame.endswith("\n")
        assert frame.count("\n") == FRAME_LINES


def test_r3_interactive_non_tty_stdout_emits_no_home():
    out = _FakeStream(tty=False)
    clock = _Clock(raise_at=6)
    rc = c.run_loop(
        _FakeStream(), out, seed=1, width=WIDTH, height=HEIGHT,
        ticks=None, sleep=lambda s: None, monotonic=clock,
    )
    assert rc == 0
    assert HOME not in out.out  # non-TTY stdout: no homes at all
    assert out.out.count("\n") == NEWLINES_2FR


# --------------------------------------------------------------------------
# T7 — REAL SIGINT to the interactive CLI -> rc 0 (M13)
# --------------------------------------------------------------------------

def test_r3_real_sigint_exits_rc_0():
    proc, master = _run_cli_interactive(stdin_mode="pty")
    try:
        _read_until_newlines(master, FRAME_LINES)  # it is running
        os.kill(proc.pid, signal.SIGINT)  # a real signal, not a \x03 byte
        _, err = proc.communicate(timeout=10)
        assert proc.returncode == 0, err
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        os.close(master)


# --------------------------------------------------------------------------
# T8 — EOF on non-TTY stdin: the interactive loop exits rc 0 quickly (M14)
# --------------------------------------------------------------------------

def test_r3_real_eof_on_non_tty_stdin_exits_rc_0():
    proc, _ = _run_cli_interactive(stdin_mode="pipe")  # subprocess.run: rc object
    assert proc.returncode == 0


# --------------------------------------------------------------------------
# T9 — flag contract: invalid flags rc 2 with empty stdout; --help rc 0
# --------------------------------------------------------------------------

def test_r3_invalid_flags_exit_rc_2_with_empty_stdout_and_help_exits_0():
    env = dict(os.environ, PYTHONPATH=str(REF_ROOT / "src"))
    bad_cases = [
        ["--width", "4"],        # width must be >= 12
        ["--height", "7"],       # height must be >= 8 (odd height also invalid)
        ["--height", "9"],       # height must be even
        ["--fps", "0"],          # fps must be > 0
        ["--ticks", "0"],        # ticks must be >= 1
        ["--nope"],              # unknown flag
    ]
    for args in bad_cases:
        r = subprocess.run(
            [sys.executable, "-m", "galaxian_cli", *args],
            cwd=REF_ROOT, env=env, capture_output=True, timeout=10,
            stdin=subprocess.DEVNULL,
        )
        assert r.returncode == 2, (args, r.returncode, r.stderr)
        assert r.stdout == b"", (args, r.stdout)
    r = subprocess.run(
        [sys.executable, "-m", "galaxian_cli", "--help"],
        cwd=REF_ROOT, env=env, capture_output=True, timeout=10,
        stdin=subprocess.DEVNULL,
    )
    assert r.returncode == 0
    assert b"usage" in r.stdout.lower()
