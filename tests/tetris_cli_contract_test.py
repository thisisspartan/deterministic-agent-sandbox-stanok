"""Calibrated contract oracle for src/tetris_cli.py (SPEC-TETRIS-CONSOLE C1..C5).

Independence policy: expected frame bytes are re-derived from the tree's own
pinned engine+render (whose own oracles pin them), never captured from CLI
output; PTY/usage/EOF bands observe the real boundary (subprocess, real pty
via os.forkpty / openpty). Mutants CM1..CM5 (see specs/STATUS.md).
GREEN on reference, RED on each targeted mutant.
"""
import io
import inspect
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

try:
    from src import tetris_cli as cli
    from src import tetris_engine as eng
    from src import tetris_render as rnd
except ImportError:
    import tetris_cli as cli
    import tetris_engine as eng
    import tetris_render as rnd

ROOT = Path(__file__).resolve().parents[1]
MOD = "src.tetris_cli"
RESET = b"\x1b[0m"
HOME = b"\x1b[H"
FRAME_LINES = 12          # default --width 10 --height 20 -> 20/2 + 2 lines


def _run_cli(args, stdin=b"", timeout=15):
    try:
        return subprocess.run([sys.executable, "-m", MOD, *args], input=stdin,
                              capture_output=True, timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail(f"CLI did not terminate in {timeout}s: {args}")


def _active(st):
    if st.piece is None:
        return None
    return (st.piece, st.x, st.y, st.piece_id)


def _replay(seed, w, h, cmds, ticks):
    """Independent expected bounded output via the tree's own engine+render."""
    st = eng.new_game(seed, w, h)
    out = []
    for cmd in cmds:
        s = {"a": lambda: eng.try_move(st, -1), "d": lambda: eng.try_move(st, 1),
             "w": lambda: eng.try_rotate(st, 1), "s": lambda: eng.soft_drop(st),
             " ": lambda: eng.hard_drop(st)}.get(cmd, lambda: None)()
        if s is not None:
            st = s
        if eng.is_game_over(st):
            out.append(rnd.render_board(st.board, _active(st)))
            return out
    for _ in range(ticks):
        st = eng.tick(st)
        out.append(rnd.render_board(st.board, _active(st)))
        if eng.is_game_over(st):
            return out
    return "".join(f + "\n" for f in out).encode()


def _frame_lines(out):
    lines = [l for l in out.split(b"\n") if l]
    import re
    pat = re.compile(rb"(?:\x1b\[38;2;\d+;\d+;\d+m\x1b\[48;2;\d+;\d+;\d+m\xe2\x96\x80)+\x1b\[0m")
    for ln in lines:
        assert pat.fullmatch(ln), ln[:80]
    return lines


def _frame_bytes_ok(out, nframes):
    assert out, "no frames"
    lines = _frame_lines(out)
    assert len(lines) == nframes * FRAME_LINES
    assert out.count(RESET) == nframes * FRAME_LINES


def _frames_valid_whole(output_bytes):
    """Loose pipe-interactive check: output is zero or more complete frames
    (frame count per period tick is not a pinned contract; validity is)."""
    lines = _frame_lines(output_bytes)
    assert len(lines) % FRAME_LINES == 0


# ---- C1: argv rc-contract -------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["--fps", "0"], ["--fps", "-1"], ["--fps", "abc"],
    ["--height", "19"], ["--height", "1"], ["--height", "0"],
    ["--ticks", "0"], ["--ticks", "-3"],
    ["--width", "1"], ["--width", "0"],
])
def test_bad_flags_rc2(args):
    p = _run_cli(args)
    assert p.returncode == 2, (args, p.returncode, p.stdout)
    assert p.stdout == b""
    assert p.stderr


def test_help_rc0():
    p = _run_cli(["--help"])
    assert p.returncode == 0
    assert p.stdout  # help text present


def test_valid_args_rc0():
    p = _run_cli(["--seed", "5", "--width", "10", "--height", "20",
                  "--fps", "30", "--ticks", "1"])
    assert p.returncode == 0


# ---- C2: bounded pipe mode -------------------------------------------------------

def test_bounded_byte_determinism_and_frames():
    args = ["--seed", "3", "--ticks", "3"]
    stdin = b"a\nd\n \n"
    a = _run_cli(args, stdin=stdin)
    b = _run_cli(args, stdin=stdin)
    assert a.returncode == 0 and b.returncode == 0
    assert a.stdout == b.stdout and a.stdout
    assert a.stdout.endswith(b"\n")
    assert HOME not in a.stdout
    _frame_bytes_ok(a.stdout, 3)


def test_bounded_matches_engine_render_replay():
    p = _run_cli(["--seed", "3", "--ticks", "3"], stdin=b"a\nd\n \n")
    assert p.returncode == 0
    assert p.stdout == _replay(3, 10, 20, ["a", "d", " "], 3)


def test_bounded_devnull_stdin_exactly_n_frames():
    p = _run_cli(["--seed", "42", "--ticks", "2"], stdin=b"")
    assert p.returncode == 0
    _frame_bytes_ok(p.stdout, 2)
    assert HOME not in p.stdout


def test_bounded_ignores_junk_lines():
    p = _run_cli(["--seed",  "8", "--ticks", "1"], stdin=b"hello\n\nab\n")
    assert p.returncode == 0
    _frame_bytes_ok(p.stdout, 1)


def test_q_stops_before_ticks():
    p = _run_cli(["--seed", "3", "--ticks", "5"], stdin=b"a\nq\n")
    assert p.returncode == 0
    assert p.stdout == b""


def test_bounded_never_home_even_when_stdout_is_tty():
    mfd, sfd = pty.openpty()
    proc = subprocess.Popen([sys.executable, "-m", MOD, "--seed", "3",
                            "--ticks", "2", "--height", "4", "--width", "8"],
                            stdin=subprocess.DEVNULL, stdout=sfd,
                            stderr=subprocess.PIPE, cwd=str(ROOT))
    os.close(sfd)
    out = b""
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        r, _, _ = select.select([mfd], [], [], 1.0)
        if not r:
            if proc.poll() is not None:
                break
            continue
        try:
            chunk = os.read(mfd, 4096)
        except OSError:
            break                      # EIO: slave closed on child exit
        if not chunk:
            break
        out += chunk
    try:
        rc = proc.wait(timeout=10)
    finally:
        os.close(mfd)
    assert rc == 0
    assert HOME not in out, "bounded mode emitted cursor-home on a TTY stdout"
    # frames survive CR translation: count resets, not newlines
    assert out.count(RESET) == 2 * (4 // 2 + 2)


# ---- C3/C4: interactive PTY via forkpty -------------------------------------------

def _pty_cli_session(argv, on_home):
    """Run the CLI in a forked child attached to a real pty. Child verifies
    termios attributes are identical before/after main() (exit 9 if not) and
    exits with main()'s rc. Parent calls on_home(fd) once cursor-home seen."""
    pid, fd = os.forkpty()
    if pid == 0:
        try:
            # forkpty attached fds 0/1/2 to the slave, but under pytest the
            # inherited Python-level sys.* streams are capture objects whose
            # fileno() points at pytest's tmpfile — rebind to the real pty fds.
            sys.stdin = open(0, "r", closefd=False)
            sys.stdout = open(1, "w", buffering=1, closefd=False)
            sys.stderr = open(2, "w", buffering=1, closefd=False)
            before = termios.tcgetattr(0)
            rc = cli.main(argv)
            after = termios.tcgetattr(0)
            if rc != 0:
                os._exit(7)
            os._exit(0 if before == after else 9)
        except BaseException:
            os._exit(8)
    buf = b""
    deadline = time.monotonic() + 15
    while b"\x1b[H" not in buf and time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.5)
        if not r:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buf += chunk
    try:
        assert buf.startswith(HOME), f"first bytes not cursor-home: {buf[:16]!r}"
        assert b"\x1b[?25" not in buf, "cursor was hidden"
        on_home(fd, pid)
        _, status = os.waitpid(pid, 0)
        code = os.waitstatus_to_exitcode(status)
        assert code == 0, f"child exit {code} (9=termios not restored)"
        # drain the rest of the pty (bounded time) to check the final frame
        tail = buf
        d2 = time.monotonic() + 5
        while time.monotonic() < d2:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                break
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            tail += chunk
        assert RESET in tail, "no frame content after cursor-home"
    finally:
        os.close(fd)


def test_interactive_tty_home_before_first_frame_and_q_clean_quit():
    def on_home(fd, child_pid):
        os.write(fd, b"q")            # quit after the first frame was home-led

    _pty_cli_session(["--seed", "7", "--fps", "60"], on_home)


def test_interactive_tty_sigint_clean_quit_and_termios_restored():
    def on_home(fd, child_pid):
        os.kill(child_pid, signal.SIGINT)

    _pty_cli_session(["--seed", "7", "--fps", "60"], on_home)


# ---- C4: interactive pipe mode — EOF must terminate, not hang -------------------

def test_interactive_pipe_eof_clean_exit_no_home():
    # anti-A4 (AUDIT-TETRIS2): EOF must terminate, not hang; rc 0; no HOME on pipe
    p = _run_cli(["--seed", "11"])      # no --ticks, stdin DEVNULL (EOF at once)
    assert p.returncode == 0
    assert HOME not in p.stdout
    _frames_valid_whole(p.stdout)


def test_interactive_pipe_commands_then_eof_finite():
    p = _run_cli(["--seed", "11"], stdin=b"a\nd\n")
    assert p.returncode == 0
    assert HOME not in p.stdout
    _frames_valid_whole(p.stdout)


def test_interactive_pipe_q_clean_exit():
    p = _run_cli(["--seed", "11"], stdin=b"a\nq\n")
    assert p.returncode == 0
    assert HOME not in p.stdout


# ---- C5: run_loop seam (single output point, injectables) ------------------------

def test_run_loop_signature():
    sig = inspect.signature(cli.run_loop)
    params = sig.parameters
    for name in ("seed", "width", "height", "fps", "ticks", "sleep", "monotonic"):
        assert name in params, name
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert issubclass(cli._SignalQuit, BaseException)


def test_run_loop_bounded_inprocess_deterministic():
    def run():
        out = io.StringIO()
        rc = cli.run_loop(io.StringIO("a\nd\n \n"), out, seed=3, width=10,
                          height=20, fps=100, ticks=3, sleep=lambda s: None,
                          monotonic=lambda: 0.0)
        return rc, out.getvalue()

    rc1, o1 = run()
    rc2, o2 = run()
    assert rc1 == 0 and rc2 == 0
    assert o1 == o2
    assert o1.encode() == _replay(3, 10, 20, ["a", "d", " "], 3)


def test_run_loop_bounded_q_immediate():
    out = io.StringIO()
    rc = cli.run_loop(io.StringIO("a\nq\n"), out, seed=3, width=10, height=20,
                      fps=100, ticks=5, sleep=lambda s: None,
                      monotonic=lambda: 0.0)
    assert rc == 0
    assert out.getvalue() == ""


def test_run_loop_pipe_eof_inprocess_no_home():
    out = io.StringIO()
    rc = cli.run_loop(io.StringIO("a\n"), out, seed=11, width=10, height=20,
                      fps=100, ticks=None, sleep=lambda s: None,
                      monotonic=lambda: 0.0)
    assert rc == 0
    assert "\x1b[H" not in out.getvalue()
    _frames_valid_whole(out.getvalue().encode())
