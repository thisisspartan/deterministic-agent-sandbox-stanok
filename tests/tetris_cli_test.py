"""CC-304 — tetris_cli reference tests (contract: docs/tetris_cli.md).

The CLI boundary over the pinned engine+render: main(argv) -> int,
`python -m src.tetris_cli`, and run_loop(stdin, stdout, *, ...) as the
single frame-output point with injectable sleep/monotonic hooks.

Bands:
  - C1 argv rc-contract: subprocess (bad flags/values -> rc 2 with usage
    on stderr and empty stdout; --help -> rc 0; valid args -> rc 0);
  - C2 bounded pipe mode: subprocess — byte-determinism, frames equal an
    independent engine+render replay, R2/R3 wire format via regex, no
    ESC[H ever (pipe stdout AND a real TTY stdout), q stops before the
    ticks, DEVNULL stdin, exactly N frames;
  - C3/C4 interactive: real PTY via os.forkpty + select (termios restored,
    ESC[H before every frame including the first, SIGINT -> rc 0) and
    pipe-EOF termination in finite time; game over -> final frame only;
  - C5 run_loop seam: in-process with StringIO streams and a fake clock.
"""

import io
import inspect
import os
import pty
import re
import select
import signal
import subprocess
import sys
import termios
import time

import pytest

try:  # namespace-package form (repo root on sys.path via `python -m pytest`)
    from src import tetris_cli as cli
    from src import tetris_engine as engine
    from src import tetris_render as render
except ImportError:  # bare form: PYTHONPATH=src
    import tetris_cli as cli
    import tetris_engine as engine
    import tetris_render as render

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOD = "src.tetris_cli"
HOME = b"\x1b[H"
RESET = b"\x1b[0m"

# R3 wire format: W segments (fg SGR + bg SGR + U+2580) then one reset.
SEG = rb"\x1b\[38;2;\d+;\d+;\d+m\x1b\[48;2;\d+;\d+;\d+m\xe2\x96\x80"
LINE = rb"(?:" + SEG + rb")+\x1b\[0m"
NL = rb"(?:\r\n|\n)"  # a real PTY translates "\n" -> "\r\n" (OPOST ONLCR)


# ---------------------------------------------------------------------------
# Subprocess harness
# ---------------------------------------------------------------------------

def run_cli(args, stdin=b"", devnull=False, timeout=15):
    """Run `python -m src.tetris_cli <args>` from the repo root."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    kwargs = dict(cwd=REPO, env=env, capture_output=True, timeout=timeout)
    if devnull:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = stdin
    try:
        proc = subprocess.run([sys.executable, "-m", MOD, *args], **kwargs)
    except subprocess.TimeoutExpired:
        pytest.fail(f"CLI did not terminate in {timeout}s: {args}")
    return proc.returncode, proc.stdout, proc.stderr


# ---------------------------------------------------------------------------
# Independent expected output: the tree's own engine + render, replayed
# ---------------------------------------------------------------------------

def _active(state):
    if state.piece is None:
        return None
    return (state.piece, state.x, state.y, state.piece_id)


def _apply(state, cmd):
    if cmd == "a":
        return engine.try_move(state, -1)
    if cmd == "d":
        return engine.try_move(state, 1)
    if cmd == "w":
        return engine.try_rotate(state, 1)
    if cmd == "s":
        return engine.soft_drop(state)
    if cmd == " ":
        return engine.hard_drop(state)
    return None


def replay(seed, width, height, cmds, ticks):
    """Expected bounded stdout bytes, derived from engine+render only:
    commands in order (game over after a command -> final frame, stop),
    then exactly N ticks with one frame after each (stop at game over)."""
    state = engine.new_game(seed, width, height)
    frames = []
    for cmd in cmds:
        new = _apply(state, cmd)
        if new is not None:
            state = new
        if engine.is_game_over(state):
            frames.append(render.render_board(state.board, _active(state)))
            return "".join(f + "\n" for f in frames).encode("utf-8")
    for _ in range(ticks):
        state = engine.tick(state)
        frames.append(render.render_board(state.board, _active(state)))
        if engine.is_game_over(state):
            break
    return "".join(f + "\n" for f in frames).encode("utf-8")


# ---------------------------------------------------------------------------
# Stream validators (R2/R3)
# ---------------------------------------------------------------------------

def parse_frame_stream(out, width, height):
    """Decompose bytes into frames: the whole stream is frame + "\\n"
    repeated; every line is exactly `width` R3 segments + one reset.
    Returns the frame count (0 for an empty stream)."""
    if out == b"":
        return 0
    assert out.endswith(b"\n"), "stream does not end with '\\n'"
    lines = out[:-1].split(b"\n")
    per_frame = height // 2 + 2
    assert len(lines) % per_frame == 0, "stream is not a whole number of frames"
    row = rb"(?:" + SEG + rb"){" + str(width).encode() + rb"}\x1b\[0m"
    for ln in lines:
        assert re.fullmatch(row, ln), f"line is not a valid R3 row: {ln[:80]!r}"
    return len(lines) // per_frame


# ---------------------------------------------------------------------------
# C1 — argv rc-contract
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["--fps", "0"],
    ["--fps", "-1"],
    ["--fps", "abc"],
    ["--height", "19"],      # odd
    ["--height", "1"],       # < 2
    ["--height", "0"],
    ["--ticks", "0"],        # < 1
    ["--ticks", "-3"],
    ["--width", "1"],        # < 2
    ["--width", "0"],
    ["--no-such-flag"],      # unknown flag
])
def test_bad_flags_and_values_rc2_usage_on_stderr_empty_stdout(args):
    rc, out, err = run_cli(args, devnull=True)
    assert rc == 2, (args, rc, out)
    assert out == b"", f"stdout must stay empty for {args}"
    assert err, f"usage must be printed to stderr for {args}"


def test_help_rc0_with_help_text_on_stdout():
    rc, out, _err = run_cli(["--help"], devnull=True)
    assert rc == 0
    assert out, "--help must print usage/help text"


def test_valid_args_rc0():
    rc, _out, _err = run_cli(["--seed", "5", "--width", "10", "--height", "20",
                              "--fps", "30", "--ticks", "1"])
    assert rc == 0


# ---------------------------------------------------------------------------
# C2 — bounded pipe mode
# ---------------------------------------------------------------------------

def test_bounded_is_byte_deterministic_and_frame_valid():
    args = ["--seed", "3", "--ticks", "3"]
    stdin = b"a\nd\n \n"
    rc1, out1, _ = run_cli(args, stdin=stdin)
    rc2, out2, _ = run_cli(args, stdin=stdin)
    assert rc1 == 0 and rc2 == 0
    assert out1 == out2, "identical argv+stdin must give byte-identical stdout"
    assert out1 and out1.endswith(b"\n")
    assert HOME not in out1, "bounded mode must never emit cursor-home"
    assert parse_frame_stream(out1, 10, 20) == 3


def test_bounded_frames_equal_independent_engine_render_replay():
    rc, out, _ = run_cli(["--seed", "3", "--ticks", "3"], stdin=b"a\nd\n \n")
    assert rc == 0
    assert out == replay(3, 10, 20, ["a", "d", " "], 3)


def test_bounded_devnull_stdin_emits_exactly_n_frames():
    rc, out, _ = run_cli(["--seed", "42", "--ticks", "2"], devnull=True)
    assert rc == 0
    assert parse_frame_stream(out, 10, 20) == 2
    assert HOME not in out


def test_bounded_commands_change_the_trace():
    args = ["--seed", "3", "--ticks", "2"]
    rc0, out0, _ = run_cli(args, stdin=b"")
    rc1, out1, _ = run_cli(args, stdin=b"d\n")
    assert rc0 == 0 and rc1 == 0
    assert out1 != out0, "'d' in stdin must change the frames"
    assert out1 == replay(3, 10, 20, ["d"], 2)


def test_bounded_q_mid_stdin_stops_before_ticks():
    rc, out, _ = run_cli(["--seed", "3", "--ticks", "5"], stdin=b"a\nq\n")
    assert rc == 0
    assert out == b"", "q must stop with rc 0 and fewer than N frames (zero)"


def test_bounded_ignores_junk_lines():
    rc, out, _ = run_cli(["--seed", "8", "--ticks", "1"],
                         stdin=b"hello\n\nab\n")
    assert rc == 0
    assert parse_frame_stream(out, 10, 20) == 1, "junk lines must not add frames"


def test_bounded_never_home_even_when_stdout_is_a_tty():
    mfd, sfd = pty.openpty()
    proc = subprocess.Popen(
        [sys.executable, "-m", MOD, "--seed", "3", "--ticks", "2",
         "--width", "8", "--height", "4"],
        stdin=subprocess.DEVNULL, stdout=sfd, stderr=subprocess.PIPE, cwd=REPO)
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
            break  # EIO: the slave closed on child exit
        if not chunk:
            break
        out += chunk
    try:
        rc = proc.wait(timeout=10)
    finally:
        os.close(mfd)
    assert rc == 0
    assert HOME not in out, "bounded mode emitted cursor-home on a TTY stdout"
    # frames survive the PTY's CR translation: count resets, not newlines
    assert out.count(RESET) == 2 * (4 // 2 + 2)


# ---------------------------------------------------------------------------
# C3 — interactive mode under a real PTY (os.forkpty + select)
# ---------------------------------------------------------------------------

def _kill_child(pid):
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    os.waitpid(pid, 0)


def _drain_pty(fd, pid, initial):
    """Read the master until the child is gone and the buffer is drained."""
    out = initial
    code = None
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        r, _, _ = select.select([fd], [], [], 0.2)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if chunk:
                out += chunk
                continue
            if code is None:  # EIO/EOF: the child closed the slave
                _, status = os.waitpid(pid, 0)
                code = os.waitstatus_to_exitcode(status)
            break
        if code is None:
            wid, status = os.waitpid(pid, os.WNOHANG)
            if wid:
                code = os.waitstatus_to_exitcode(status)
    if code is None:
        _kill_child(pid)
        pytest.fail("the CLI child did not exit within the deadline")
    return code, out


def _pty_cli(argv, trigger, frame_lines):
    """Run main(argv) in a forked child attached to a real pty. The child
    compares termios attributes before/after main() (exit 9 if not restored)
    and exits with main()'s rc. The parent waits for one COMPLETE frame,
    asserts it is home-led, calls trigger(fd, pid), then drains everything."""
    pid, fd = os.forkpty()
    if pid == 0:
        try:
            # forkpty attached fds 0/1/2 to the slave, but the inherited
            # Python-level sys.* streams point at pytest's capture file —
            # rebind them to the real pty fds.
            sys.stdin = open(0, "r", encoding="utf-8", closefd=False)
            sys.stdout = open(1, "w", encoding="utf-8", buffering=1,
                              closefd=False)
            sys.stderr = open(2, "w", encoding="utf-8", buffering=1,
                              closefd=False)
            before = termios.tcgetattr(0)
            rc = cli.main(argv)
            after = termios.tcgetattr(0)
            if rc != 0:
                os._exit(7)
            os._exit(0 if before == after else 9)
        except BaseException:
            os._exit(8)
    out = b""
    deadline = time.monotonic() + 15
    try:
        while out.count(RESET) < frame_lines and time.monotonic() < deadline:
            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
        if out.count(RESET) < frame_lines:
            _kill_child(pid)
            pytest.fail(f"no complete frame reached the pty: {out[:80]!r}")
        assert out.startswith(HOME), f"first bytes are not cursor-home: {out[:16]!r}"
        assert b"\x1b[?25" not in out, "the cursor was hidden"
        try:
            trigger(fd, pid)
        except OSError:
            pass  # the child already exited on its own
        code, out = _drain_pty(fd, pid, out)
        assert code == 0, f"child exit {code} (9=termios not restored, 7=rc!=0, 8=exception)"
        return out
    finally:
        os.close(fd)


def _assert_home_prefixed_frames(out, width, height):
    """The whole PTY stream is (ESC[H + frame) repeated — every frame,
    including the first, is home-led; only a trailing frame cut by a signal
    may be incomplete. At least one complete frame is required."""
    per_frame = height // 2 + 2
    frame = rb"(?:" + LINE + NL + rb"){" + str(per_frame).encode() + rb"}"
    complete = rb"(?:\x1b\[H" + frame + rb")*"
    # Any prefix of a frame line: whole segments, then a cut at any byte
    # position (right after the reset, mid-SGR, fg-complete + partial bg,
    # or mid-glyph).
    partial_line = (rb"(?:" + SEG + rb")*"
                    rb"(?:\x1b\[0m"
                    rb"|\x1b\[[0-9;]*"
                    rb"|\x1b\[38;2;\d+;\d+;\d*m\x1b\[[0-9;]*"
                    rb"|\x1b\[38;2;\d+;\d+;\d*m\x1b\[48;2;\d+;\d+;\d*m(?:\xe2\x96?)?"
                    rb")?")
    tail = (rb"(?:\x1b\[H(?:" + LINE + NL + rb"){0,"
            + str(per_frame - 1).encode() + rb"}" + partial_line + rb")?")
    assert re.fullmatch(complete + tail, out), f"stream is not (HOME+frame)*: {out[:120]!r}"
    assert out.startswith(HOME), "the first frame is not home-led"
    assert out.count(RESET) >= per_frame, "no complete frame reached the terminal"


def test_pty_termios_restored_home_before_every_frame_and_q_clean_quit():
    def trigger(fd, pid):
        os.write(fd, b"q")  # quit after the first complete frame was home-led

    out = _pty_cli(["--seed", "7", "--fps", "2"], trigger, 20 // 2 + 2)
    assert HOME in out
    _assert_home_prefixed_frames(out, 10, 20)


def test_pty_sigint_clean_quit_termios_restored():
    def trigger(fd, pid):
        os.kill(pid, signal.SIGINT)

    out = _pty_cli(["--seed", "7", "--fps", "2"], trigger, 20 // 2 + 2)
    assert b"\x1b[?25" not in out, "the cursor must never be hidden"
    _assert_home_prefixed_frames(out, 10, 20)


# ---------------------------------------------------------------------------
# C4 — interactive pipe mode: EOF terminates; game over -> final frame only
# ---------------------------------------------------------------------------

def test_interactive_pipe_commands_then_eof_terminates_finite():
    rc, out, _ = run_cli(["--seed", "11"], stdin=b"a\nd\n")  # timeout guard
    assert rc == 0
    assert HOME not in out, "pipe stdout must never get cursor-home"
    count = parse_frame_stream(out, 10, 20)
    assert count >= 0


def test_interactive_pipe_devnull_eof_clean_exit():
    rc, out, _ = run_cli(["--seed", "11"], devnull=True)
    assert rc == 0
    assert HOME not in out
    parse_frame_stream(out, 10, 20)  # must be zero or more complete frames


def test_interactive_pipe_q_clean_exit():
    rc, out, _ = run_cli(["--seed", "11"], stdin=b"a\nq\n")
    assert rc == 0
    assert HOME not in out


def test_bounded_stops_at_game_over_final_frame_only():
    # seed 1 at 4x4 reaches game over at tick 4 (verified against the engine)
    rc, out, _ = run_cli(["--seed", "1", "--width", "4", "--height", "4",
                          "--ticks", "50"], devnull=True)
    assert rc == 0
    count = parse_frame_stream(out, 4, 4)
    assert 0 < count < 50, "game over must have stopped the tick loop"
    assert out == replay(1, 4, 4, [], 50), "no frames after the game-over frame"


# ---------------------------------------------------------------------------
# C5 — run_loop seam: single output point, injectable sleep/monotonic
# ---------------------------------------------------------------------------

def test_run_loop_signature_and_signal_exception():
    params = inspect.signature(cli.run_loop).parameters
    for name in ("seed", "width", "height", "fps", "ticks", "sleep", "monotonic"):
        assert name in params, name
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY, name
    assert issubclass(cli._SignalQuit, BaseException)


def _run_inprocess(stdin_text, seed, ticks, width=10, height=20):
    out = io.StringIO()
    rc = cli.run_loop(io.StringIO(stdin_text), out, seed=seed, width=width,
                      height=height, fps=100, ticks=ticks,
                      sleep=lambda s: None, monotonic=lambda: 0.0)
    return rc, out.getvalue()


def test_run_loop_bounded_inprocess_deterministic_and_matches_replay():
    rc1, o1 = _run_inprocess("a\nd\n \n", 3, 3)
    rc2, o2 = _run_inprocess("a\nd\n \n", 3, 3)
    assert rc1 == 0 and rc2 == 0
    assert o1 == o2 and o1
    assert o1.encode("utf-8") == replay(3, 10, 20, ["a", "d", " "], 3)
    assert parse_frame_stream(o1.encode("utf-8"), 10, 20) == 3
    assert "\x1b[H" not in o1


def test_run_loop_bounded_applies_commands():
    rc, plain = _run_inprocess("", 3, 2)
    rc2, moved = _run_inprocess("d\n", 3, 2)
    assert rc == 0 and rc2 == 0
    assert moved != plain, "commands must be applied to the engine state"
    assert moved.encode("utf-8") == replay(3, 10, 20, ["d"], 2)


def test_run_loop_bounded_q_emits_no_frames():
    rc, out = _run_inprocess("a\nq\n", 3, 5)
    assert rc == 0
    assert out == ""


def test_run_loop_interactive_pipe_eof_inprocess_no_home():
    rc, out = _run_inprocess("a\n", 11, None)
    assert rc == 0
    assert "\x1b[H" not in out
    parse_frame_stream(out.encode("utf-8"), 10, 20)  # zero or more valid frames
