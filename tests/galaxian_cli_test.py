"""CC-295 — galaxian_cli reference tests (contract: docs/galaxian_cli.md).

The CLI boundary: main(argv) -> int, `python -m src.galaxian_cli`, and
run_loop(stdin, stdout, ...) as the single frame-output point with
injectable sleep/monotonic hooks.

Two execution modes are tested:
  - bounded (--ticks N) through a real subprocess (`python -m src.galaxian_cli`
    with pipe/DEVNULL stdin) — frames must equal an independent
    engine+render simulation, byte for byte;
  - interactive through run_loop with fake streams (isatty() implemented,
    no real PTY) and injected sleep/monotonic.

Note on test 7 (game over): the pinned engine structurally cannot reach
game over at height 8 — a bomb is dropped at y >= 6 + 2 = 8 while the
player row is height-2 = 6, so no bomb can ever hit the player. The
smallest even height where the default seed reaches game over is 12
(tick 498), so the game-over scenario runs `--width 12 --height 12`.
"""

import os
import re
import subprocess
import sys

import pytest

import galaxian_cli as bare  # noqa: F401  (pythonpath=src form)
from src import galaxian_cli
from src import galaxian_engine as engine
from src import galaxian_render as render

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOME = "\x1b[H"

_SGR = (
    r"\x1b\[38;2;\d{1,3};\d{1,3};\d{1,3}m"
    r"\x1b\[48;2;\d{1,3};\d{1,3};\d{1,3}m"
)


# ---------------------------------------------------------------------------
# Subprocess harness (bounded mode)
# ---------------------------------------------------------------------------

def run_cli(args, stdin_bytes=None, devnull=False):
    """Run `python -m src.galaxian_cli <args>` from the repo root."""
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    if devnull:
        proc = subprocess.run(
            [sys.executable, "-m", "src.galaxian_cli", *args],
            cwd=REPO, env=env, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=60,
        )
    else:
        proc = subprocess.run(
            [sys.executable, "-m", "src.galaxian_cli", *args],
            cwd=REPO, env=env,
            input=stdin_bytes if stdin_bytes is not None else b"",
            capture_output=True, timeout=60,
        )
    return proc.returncode, proc.stdout, proc.stderr


def expected_bounded(seed, width, height, ticks, keys=b""):
    """Independent simulation of the bounded contract -> expected stdout bytes
    (None when a quit command is present: rc 0 with NO frames)."""
    state = engine.new_game(seed, width, height)
    for command in galaxian_cli.parse_keys(keys):
        if command is galaxian_cli._QUIT:
            return None
        if command[0] == "move":
            state = engine.move(state, command[1])
        else:
            state = engine.fire(state)
    out = b""
    for _ in range(ticks):
        state = engine.tick(state)
        out += (render.render_frame(state) + "\n").encode("utf-8")
        if engine.is_game_over(state):
            break
    return out


# ---------------------------------------------------------------------------
# Frame/stream validators (test 9)
# ---------------------------------------------------------------------------

def assert_valid_frame(lines, width, height):
    """One frame: exactly height//2+2 lines — border, half-block rows, status."""
    count = height // 2 + 2
    assert len(lines) == count, f"frame has {len(lines)} lines, expected {count}"
    border = r"(?:\x1b\[38;2;60;60;90m\x1b\[48;2;60;60;90m ){%d}\x1b\[0m" % width
    assert re.fullmatch(border, lines[0]), "line 0 is not the border"
    row = r"(?:%s[▀▄ ]){%d}\x1b\[0m" % (_SGR, width)
    for line in lines[1:-1]:
        assert re.fullmatch(row, line), "half-block row malformed"
    status = r"\x1b\[38;2;220;220;220m\x1b\[48;2;0;0;0m.{%d}\x1b\[0m" % width
    assert re.fullmatch(status, lines[-1]), "status line malformed"
    # The status text is truncated/padded to exactly `width`; width >= 12
    # always shows the "SC " head of "SC <score>  LV <wave>  LIVES <lives>".
    text = lines[-1][len("\x1b[38;2;220;220;220m\x1b[48;2;0;0;0m"):-len("\x1b[0m")]
    assert text.startswith("SC "), "status line does not start with 'SC '"


def parse_stream(text, width, height):
    """Strict decomposition: the whole stream is a concatenation of
    (optional HOME) + frame + "\\n" — no foreign bytes. Returns the frames
    (each a list of lines) and whether each was home-prefixed."""
    count = height // 2 + 2
    assert text.endswith("\n"), "stream does not end with '\\n'"
    lines = text[:-1].split("\n")
    assert len(lines) % count == 0, "stream is not a whole number of frames"
    frames, homed = [], []
    for k in range(len(lines) // count):
        group = lines[k * count:(k + 1) * count]
        is_home = group[0].startswith(HOME)
        if is_home:
            group[0] = group[0][len(HOME):]
        assert_valid_frame(group, width, height)
        frames.append(group)
        homed.append(is_home)
    # HOME may appear ONLY as a frame prefix (render never emits it).
    assert text.count(HOME) == sum(homed), "HOME found outside a frame prefix"
    return frames, homed


# ---------------------------------------------------------------------------
# Fake streams / clock (interactive mode — no real PTY)
# ---------------------------------------------------------------------------

class FakeStdin:
    """Duck-typed stdin: isatty() implemented; each drain (the CLI calls
    read(1) until it returns b"") yields exactly the next scripted chunk."""

    def __init__(self, chunks, tty=True):
        self._chunks = list(chunks)
        self._tty = tty
        self._drained = False

    def isatty(self):
        return self._tty

    def read(self, size=-1):
        if self._drained:
            self._drained = False
            return b""
        if not self._chunks:
            return b""
        self._drained = True
        return self._chunks.pop(0)


class FakeStdout:
    def __init__(self, tty=True):
        self.parts = []
        self._tty = tty

    def isatty(self):
        return self._tty

    def write(self, s):
        self.parts.append(s)

    def flush(self):
        pass

    @property
    def text(self):
        return "".join(self.parts)


class FakeClock:
    """Constant virtual time: every period the loop sleeps (recorded, no-op)."""

    def __init__(self):
        self.sleeps = []

    def monotonic(self):
        return 0.0

    def sleep(self, dt):
        self.sleeps.append(dt)


def run_interactive(chunks, stdin_tty, stdout_tty, seed=5, width=12, height=8,
                    fps=1000.0):
    clock = FakeClock()
    stdin = FakeStdin(chunks, tty=stdin_tty)
    stdout = FakeStdout(tty=stdout_tty)
    rc = galaxian_cli.run_loop(
        stdin, stdout, seed, width, height, fps,
        sleep=clock.sleep, monotonic=clock.monotonic,
    )
    return rc, stdout.text


def expected_interactive(chunks, seed, width, height, home):
    """Independent simulation of the interactive contract."""
    state = engine.new_game(seed, width, height)
    out = ""
    for chunk in chunks:
        commands = galaxian_cli.parse_keys(chunk)
        if any(c is galaxian_cli._QUIT for c in commands):
            return out
        for command in commands:
            if command[0] == "move":
                state = engine.move(state, command[1])
            else:
                state = engine.fire(state)
        state = engine.tick(state)
        out += (HOME if home else "") + render.render_frame(state) + "\n"
        if engine.is_game_over(state):
            return out
    return out


# ---------------------------------------------------------------------------
# 1. Bounded subprocess: exactly N frames, no home/clear/cursor sequences
# ---------------------------------------------------------------------------

def test_bounded_emits_exactly_n_frames_no_escape_control():
    args = ["--ticks", "3", "--seed", "7", "--width", "12", "--height", "8"]
    rc, out, _err = run_cli(args, devnull=True)
    assert rc == 0
    assert b"\x1b[H" not in out
    assert b"\x1b[2J" not in out
    assert b"\x1b[?25" not in out
    expected = expected_bounded(7, 12, 8, 3)
    assert out == expected  # byte-exact against an independent simulation
    text = out.decode("utf-8")
    frames, homed = parse_stream(text, 12, 8)
    assert len(frames) == 3
    assert not any(homed), "bounded mode must never home"
    for frame in frames:
        assert len(frame) == 8 // 2 + 2  # 5 lines per frame


# ---------------------------------------------------------------------------
# 2. Bounded determinism: identical runs byte-identical; commands change bytes
# ---------------------------------------------------------------------------

def test_bounded_is_deterministic_and_commands_change_the_output():
    args = ["--ticks", "2", "--seed", "3", "--width", "12", "--height", "8"]
    rc1, out1, _ = run_cli(args, stdin_bytes=b"")
    rc2, out2, _ = run_cli(args, stdin_bytes=b"")
    assert (rc1, rc2) == (0, 0)
    assert out1 == out2, "identical argv+stdin must be byte-identical"

    rc3, out3, _ = run_cli(args, stdin_bytes=b"d\n")
    rc4, out4, _ = run_cli(args, stdin_bytes=b"d\n")
    assert rc3 == 0
    assert out3 == out4, "a run with commands must also be self-identical"
    assert out3 != out1, "'d' in stdin must change the frames"
    assert out3 == expected_bounded(3, 12, 8, 2, keys=b"d\n")


# ---------------------------------------------------------------------------
# 3. Quit in bounded stdin -> rc 0, empty stdout
# ---------------------------------------------------------------------------

def test_quit_in_bounded_stdin_prints_no_frames():
    args = ["--ticks", "3", "--seed", "7", "--width", "12", "--height", "8"]
    rc, out, _err = run_cli(args, stdin_bytes=b"d\nq")
    assert rc == 0
    assert out == b""


# ---------------------------------------------------------------------------
# 4. Flag validation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["--height", "7"],            # odd
    ["--height", "6"],           # < 8
    ["--width", "11"],           # < 12
    ["--fps", "0"],              # <= 0
    ["--ticks", "0"],            # < 1
    ["--no-such-flag"],          # unknown
])
def test_invalid_flags_exit_rc2_with_empty_stdout(args):
    rc, out, _err = run_cli(args, devnull=True)
    assert rc == 2
    assert out == b""


def test_help_exits_zero():
    rc, _out, _err = run_cli(["--help"], devnull=True)
    assert rc == 0


# ---------------------------------------------------------------------------
# 5. Interactive fake-TTY: every frame (incl. the first) homed; quit -> rc 0
# ---------------------------------------------------------------------------

INTERACTIVE_CHUNKS = [b"a", b"d", b" ", b"q"]

def test_interactive_tty_stdout_homes_every_frame():
    rc, out = run_interactive(INTERACTIVE_CHUNKS, stdin_tty=True, stdout_tty=True)
    assert rc == 0
    assert b"\x1b[2J" not in out.encode("utf-8")
    assert b"\x1b[?25" not in out.encode("utf-8")
    frames, homed = parse_stream(out, 12, 8)
    assert len(frames) >= 2, "expected at least two frames before quit"
    assert all(homed), "every frame INCLUDING the first must be home-prefixed"
    assert out == expected_interactive(INTERACTIVE_CHUNKS, 5, 12, 8, home=True)


# ---------------------------------------------------------------------------
# 6. Same scenario, non-TTY stdout: no homes, byte-identical without prefixes
# ---------------------------------------------------------------------------

def test_interactive_non_tty_stdout_has_no_homes():
    rc_tty, out_tty = run_interactive(INTERACTIVE_CHUNKS, True, True)
    rc, out = run_interactive(INTERACTIVE_CHUNKS, False, False)
    assert rc == 0
    assert HOME not in out
    frames, homed = parse_stream(out, 12, 8)
    assert not any(homed)
    assert out == out_tty.replace(HOME, "")
    assert out == expected_interactive(INTERACTIVE_CHUNKS, 5, 12, 8, home=False)


# ---------------------------------------------------------------------------
# 7. Game over in bounded mode: loop stops early, final frame is last
# ---------------------------------------------------------------------------

def test_bounded_stops_at_game_over():
    # height 12: the smallest even height where the default seed reaches
    # game over (the engine cannot ever hit the player at height 8 — see
    # module docstring). Default seed 1.
    args = ["--ticks", "3000", "--width", "12", "--height", "12"]
    rc, out, _err = run_cli(args, devnull=True)
    assert rc == 0
    text = out.decode("utf-8")
    frames, _homed = parse_stream(text, 12, 12)
    assert 0 < len(frames) < 3000, "game over must have stopped the loop"
    # the last frame is a valid frame and nothing follows it
    assert text.endswith("\n")
    assert_valid_frame(frames[-1], 12, 12)
    expected = expected_bounded(1, 12, 12, 3000)
    assert out == expected
    state = engine.new_game(1, 12, 12)
    for _ in range(len(frames)):
        state = engine.tick(state)
    assert engine.is_game_over(state), "the stream must end at the game-over frame"


# ---------------------------------------------------------------------------
# 8. \x03 in interactive stdin -> rc 0, no frames after it
# ---------------------------------------------------------------------------

def test_ctrl_c_byte_quits_with_no_frames_after():
    chunks = [b"a", b"\x03"]
    rc, out = run_interactive(chunks, stdin_tty=True, stdout_tty=True)
    assert rc == 0
    frames, homed = parse_stream(out, 12, 8)
    assert len(frames) == 1, "exactly the frames before \\x03 may be printed"
    assert all(homed)
    assert out == expected_interactive(chunks, 5, 12, 8, home=True)


# ---------------------------------------------------------------------------
# 9. Sole output point: bounded and fake-TTY streams decompose exactly into
#    (optional HOME) + render_frame + "\n" — no foreign bytes
# ---------------------------------------------------------------------------

def test_every_byte_belongs_to_a_frame():
    # bounded stream
    rc, out, _ = run_cli(
        ["--ticks", "2", "--seed", "7", "--width", "12", "--height", "8"],
        devnull=True)
    assert rc == 0
    frames, homed = parse_stream(out.decode("utf-8"), 12, 8)
    assert len(frames) == 2 and not any(homed)
    expected = expected_bounded(7, 12, 8, 2).decode("utf-8")
    rebuilt = "".join(frame + "\n" for frame in expected.split("\n")[:-1])
    assert out.decode("utf-8") == rebuilt

    # fake-TTY interactive stream
    rc, out = run_interactive(INTERACTIVE_CHUNKS, True, True)
    assert rc == 0
    frames, homed = parse_stream(out, 12, 8)
    assert all(homed)
    # rebuilding the stream from the parsed frames reproduces it byte-for-byte
    rebuilt = "".join(HOME + "\n".join(frame) + "\n" for frame in frames)
    assert out == rebuilt
