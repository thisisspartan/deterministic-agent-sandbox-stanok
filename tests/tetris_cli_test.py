"""CC-292 — tetris_cli reference tests: the pinned contract of the terminal
boundary layer (interactive + --ticks pipe-tool) over tetris_engine and
tetris_render.

No real PTY here: bounded paths run through subprocess (`python -m
src.tetris_cli`, pipe/DEVNULL stdin); interactive paths call run_loop/main
with duck-typed streams (isatty() implemented) and injected sleep/monotonic
hooks, so no wall-clock is involved. The boundary accept
(tests/tetris_terminal_test.py) is host-authored and not part of this file.
"""

import os
import subprocess
import sys

import pytest

import tetris_cli as cli
import tetris_engine as eng
import tetris_render as rnd

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HOME = "\x1b[H"


# ---------------------------------------------------------------------------
# duck-typed streams and clock (fixtures defined inside the test file)
# ---------------------------------------------------------------------------

class FakeStdin:
    """Non-TTY stdin yielding the given chunks on successive reads."""

    def __init__(self, chunks):
        self._chunks = list(chunks)

    def isatty(self):
        return False

    def read(self, *_args):
        if self._chunks:
            return self._chunks.pop(0)
        return b""


class FakeStdout:
    def __init__(self, tty=False):
        self.data = ""
        self._tty = tty

    def isatty(self):
        return self._tty

    def write(self, text):
        self.data += text

    def flush(self):
        pass


class FakeClock:
    """Injected monotonic/sleep: time advances only through sleep()."""

    def __init__(self):
        self.now = 0.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


# ---------------------------------------------------------------------------
# helpers: an independent re-implementation of the pinned CLI semantics
# ---------------------------------------------------------------------------

def _run_cli(args, stdin_bytes=None):
    """Run the CLI as a subprocess from the repo root (python -m src.tetris_cli)."""
    if stdin_bytes is None:
        return subprocess.run(
            [sys.executable, "-m", "src.tetris_cli", *args],
            cwd=_REPO, capture_output=True,
            stdin=subprocess.DEVNULL, timeout=30,
        )
    return subprocess.run(
        [sys.executable, "-m", "src.tetris_cli", *args],
        cwd=_REPO, capture_output=True,
        input=stdin_bytes, timeout=30,
    )


def _tokens(data):
    """Split input text into command tokens; arrow escape sequences map to
    their letter equivalents."""
    arrows = {"A": "w", "B": "s", "C": "d", "D": "a"}
    i = 0
    while i < len(data):
        if data[i] == "\x1b" and data[i:i + 3] in ("\x1b[A", "\x1b[B", "\x1b[C", "\x1b[D"):
            yield arrows[data[i + 2]]
            i += 3
        else:
            yield data[i]
            i += 1


def _apply(ch, state):
    if ch == "a":
        return eng.try_move(state, -1)
    if ch == "d":
        return eng.try_move(state, 1)
    if ch == "w":
        return eng.try_rotate(state, 1)
    if ch == "s":
        return eng.soft_drop(state)
    if ch == " ":
        return eng.hard_drop(state)
    return None


def _render_state(state):
    active = None
    if state.piece is not None:
        shape = [[state.piece_id if cell else 0 for cell in row] for row in state.piece]
        active = (shape, state.x, state.y)
    return rnd.render_board(state.board, active)


def _sim_bounded(seed, width, height, commands, ticks):
    """Expected bounded frames: apply commands in order (q/\\x03 quits before
    any tick or frame), then exactly one frame per tick, stopping after the
    tick that ends the game."""
    state = eng.new_game(seed, width, height)
    for ch in _tokens(commands):
        if ch in ("q", "\x03"):
            return []
        moved = _apply(ch, state)
        if moved is not None:
            state = moved
    frames = []
    for _ in range(ticks):
        state = eng.tick(state)
        frames.append(_render_state(state))
        if eng.is_game_over(state):
            break
    return frames


def _sim_interactive(seed, width, height, polls):
    """Expected interactive frames: each poll applies its commands (q/\\x03
    quits before any frame), then one tick and one frame; stops on game over."""
    state = eng.new_game(seed, width, height)
    frames = []
    for poll in polls:
        quit_ = False
        for ch in _tokens(poll):
            if ch in ("q", "\x03"):
                quit_ = True
                break
            moved = _apply(ch, state)
            if moved is not None:
                state = moved
        if quit_:
            break
        state = eng.tick(state)
        frames.append(_render_state(state))
        if eng.is_game_over(state):
            break
    return frames


def _interactive(chunks, out_tty, seed=7, width=10, height=20, fps=1.0):
    stdin = FakeStdin(chunks)
    stdout = FakeStdout(tty=out_tty)
    clock = FakeClock()
    rc = cli.run_loop(stdin, stdout, seed=seed, width=width, height=height,
                      fps=fps, sleep=clock.sleep, monotonic=clock.monotonic)
    return rc, stdout.data


def _split_homed(data):
    """Split a homed interactive stream: every frame (including the first)
    must be prefixed by the exact HOME bytes."""
    parts = data.split(HOME)
    assert parts[0] == "", "the first frame is not homed"
    return parts[1:]


def _assert_frame(frame_text, width, height):
    assert frame_text.endswith("\n")
    lines = frame_text[:-1].split("\n")
    n = height // 2 + 2
    assert len(lines) == n
    assert lines[0] == lines[-1]  # top and bottom borders are identical
    for line in lines:
        assert "▀" in line


# ---------------------------------------------------------------------------
# 1. bounded mode through subprocess: exactly N frames, no home/clear/cursor
# ---------------------------------------------------------------------------

def test_bounded_ticks_subprocess_emits_exactly_n_frames():
    proc = _run_cli(["--ticks", "3", "--seed", "7", "--width", "10", "--height", "20"])
    assert proc.returncode == 0
    out = proc.stdout
    assert out, "bounded mode must emit frames"
    assert b"\x1b[H" not in out
    assert b"\x1b[2J" not in out
    assert b"\x1b[?25" not in out
    assert out.endswith(b"\n")
    lines = out.decode("utf-8").split("\n")
    assert lines[-1] == ""
    n = 20 // 2 + 2  # 12 lines per frame
    assert len(lines) == 3 * n + 1, "exactly three frames"
    for k in range(3):
        frame = lines[k * n:(k + 1) * n]
        assert frame[0] == frame[-1]
        assert all("▀" in line for line in frame)


# ---------------------------------------------------------------------------
# 2. bounded determinism; commands from stdin are applied
# ---------------------------------------------------------------------------

def test_bounded_is_deterministic_and_applies_stdin_commands():
    args = ["--ticks", "3", "--seed", "7", "--width", "10", "--height", "20"]
    a1 = _run_cli(args).stdout
    a2 = _run_cli(args).stdout
    assert a1 == a2 and a1
    c1 = _run_cli(args, b"a\n").stdout
    c2 = _run_cli(args, b"a\n").stdout
    assert c1 == c2 and c1
    assert c1 != a1, "the 'a' command (spawn is central, left is valid) must change the stream"


# ---------------------------------------------------------------------------
# 3. q in bounded stdin: rc 0, no ticks, no frames
# ---------------------------------------------------------------------------

def test_quit_in_bounded_stdin_runs_no_ticks_and_no_frames():
    proc = _run_cli(["--ticks", "3", "--seed", "7"], stdin_bytes=b"a\nq")
    assert proc.returncode == 0
    assert proc.stdout == b""


# ---------------------------------------------------------------------------
# 4. flag validation: rc 2 with empty stdout; --help rc 0
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["--height", "5"],
    ["--height", "0"],
    ["--height", "1"],
    ["--width", "1"],
    ["--width", "0"],
    ["--fps", "0"],
    ["--fps", "-2.5"],
    ["--ticks", "0"],
    ["--ticks", "-1"],
    ["--unknown"],
    ["--seed"],
    ["positional"],
])
def test_invalid_flag_or_value_rejects_with_rc_2_and_empty_stdout(args):
    proc = _run_cli(args)
    assert proc.returncode == 2
    assert proc.stdout == b""


def test_help_exits_zero():
    proc = _run_cli(["--help"])
    assert proc.returncode == 0


# ---------------------------------------------------------------------------
# 5. interactive with fake TTY stdout: every frame (incl. the first) homed
# ---------------------------------------------------------------------------

def test_interactive_tty_stdout_homes_every_frame_including_the_first():
    rc, out = _interactive([b"", b"a", b"", b"q"], out_tty=True)
    assert rc == 0
    frames = _split_homed(out)
    assert len(frames) >= 2, "at least two frames before quit"
    for frame in frames:
        _assert_frame(frame, 10, 20)
    assert "\x1b[2J" not in out
    assert "\x1b[?25" not in out


# ---------------------------------------------------------------------------
# 6. same scenario with non-TTY stdout: no homes, otherwise byte-identical
# ---------------------------------------------------------------------------

def test_interactive_non_tty_stdout_has_no_homes_and_is_otherwise_identical():
    polls = [b"", b"a", b"", b"q"]
    rc_tty, out_tty = _interactive(polls, out_tty=True)
    rc, out = _interactive(polls, out_tty=False)
    assert rc_tty == 0 and rc == 0
    assert HOME not in out
    assert out == out_tty.replace(HOME, "")


# ---------------------------------------------------------------------------
# 7. game over: final frame printed, then no new frames
# ---------------------------------------------------------------------------

def test_game_over_prints_final_frame_and_emits_nothing_after():
    rc, out = _interactive([b""], out_tty=True, seed=14, width=4, height=2)
    assert rc == 0
    frames = _split_homed(out)
    state = eng.new_game(14, 4, 2)
    expected = []
    while True:
        state = eng.tick(state)
        expected.append(_render_state(state))
        if eng.is_game_over(state):
            break
    assert len(expected) >= 2
    assert len(frames) == len(expected), "no frames after game over"
    for got, want in zip(frames, expected):
        assert got == want + "\n"


# ---------------------------------------------------------------------------
# 8. \\x03 in stdin: rc 0, no frames after it
# ---------------------------------------------------------------------------

def test_ctrl_c_byte_quits_the_loop_with_no_frame_after():
    rc, out = _interactive([b"", b"\x03"], out_tty=True)
    assert rc == 0
    frames = _split_homed(out)
    assert len(frames) == 1, "the loop must stop at the \\x03 poll"


# ---------------------------------------------------------------------------
# 9. sole output point: main()'s bounded and interactive paths print exactly
#    render_board frames and nothing else
# ---------------------------------------------------------------------------

def test_main_bounded_output_is_exactly_render_frames():
    args = ["--ticks", "2", "--seed", "7", "--width", "10", "--height", "20"]
    proc = _run_cli(args, stdin_bytes=b"a\n")
    assert proc.returncode == 0
    expected = _sim_bounded(7, 10, 20, "a\n", 2)
    assert len(expected) == 2
    assert proc.stdout.decode("utf-8") == "".join(frame + "\n" for frame in expected)


def test_main_interactive_output_is_exactly_homed_render_frames(monkeypatch):
    stdin = FakeStdin([b"", b"\x1b[D", b"q"])  # arrow-left must act as 'a'
    stdout = FakeStdout(tty=True)
    monkeypatch.setattr(sys, "stdin", stdin)
    monkeypatch.setattr(sys, "stdout", stdout)
    rc = cli.main(["--seed", "7", "--width", "10", "--height", "20", "--fps", "1000"])
    assert rc == 0
    frames = _split_homed(stdout.data)
    expected = _sim_interactive(7, 10, 20, ["", "\x1b[D", "q"])
    assert len(frames) == len(expected) == 2
    for got, want in zip(frames, expected):
        assert got == want + "\n"


# ---------------------------------------------------------------------------
# 10. characters outside the pinned key map are ignored
# ---------------------------------------------------------------------------

def test_unlisted_characters_are_ignored():
    _, out_junk = _interactive([b"xyz;123\t", b"", b"q"], out_tty=False)
    _, out_plain = _interactive([b"", b"", b"q"], out_tty=False)
    assert out_junk == out_plain
