"""CC-318 self-tests for src/fire.py — interactive mode C9..C11.

In-process by design: the module's interactive-output functions are called
directly and the escape stream is inspected as DATA — no PTY is started here.
The real-terminal boundary (geometry on a live screen, Ctrl+C through the
line discipline) belongs to the frozen accept fixture
tests/fire_terminal_test.py.

PROVENANCE of every expected literal: SPEC-FIRE-2026-10-22 (SPEC-F),
sections C9 (geometry), C10 (truecolor table, cleanup, --no-color), C11
(Ctrl+C). The literals below are written from the spec, not imported from the
implementation — a test that reads its expectations from the code it tests
asserts nothing.
"""

import io
import random
import re
import signal
import sys
import threading

import pytest

# src/ is on sys.path via the registry's pythonpath=src (scripts/stacks/py.toml).
import fire

# ---------------------------------------------------------------------------
# SPEC-F literals
# ---------------------------------------------------------------------------

# C5 palette (unchanged by this ticket).
PALETTE = " .:-=+*#%@"

# C10 truecolor table: palette index -> (R, G, B). Index 0 (space) has none.
COLORS = {
    1: (30, 10, 6),
    2: (58, 14, 8),
    3: (96, 22, 10),
    4: (138, 34, 12),
    5: (186, 56, 14),
    6: (222, 94, 22),
    7: (242, 140, 38),
    8: (250, 186, 66),
    9: (255, 240, 170),
}
HOT = {COLORS[8], COLORS[9]}

# C9/C10 control sequences, spelled out from the spec.
HOME = "\x1b[H"
HOME_ALT = "\x1b[1;1H"
HIDE = "\x1b[?25l"
SHOW = "\x1b[?25h"
RESET = "\x1b[0m"
CRLF = "\r\n"

TRIPLE_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
SGR_RE = re.compile(r"\x1b\[[0-9;]*m")
CSI_RE = re.compile(r"\x1b\[([0-9;?]*)([A-Za-z])")

WIDTH, HEIGHT = 24, 12  # the accept window: height == rows, so C8b's dark row is real


# ---------------------------------------------------------------------------
# helpers (fixtures live in the test file — CLAUDE.md: no conftest.py)
# ---------------------------------------------------------------------------

def _args(*extra):
    return fire.parse_args(
        ["--width", str(WIDTH), "--height", str(HEIGHT), *extra])


def _heats(args, frames):
    """The engine states the interactive branch must render, recomputed here
    with the same seed and the same call order as the module uses (C3/C4)."""
    rng = random.Random(args.seed)
    heat = [[0] * args.width for _ in range(args.height)]
    states = []
    for _ in range(frames):
        fire.step_heat(heat, rng)
        states.append([row[:] for row in heat])
    return states


class FakeTty(io.StringIO):
    """A stand-in for a terminal: isatty() is True, writes are captured."""

    def isatty(self):
        return True

    def getvalue(self):
        return super().getvalue()


def _strip_sgr(text):
    return SGR_RE.sub("", text)


def _frame_body(stream):
    """The bytes of one frame after its home."""
    assert stream.startswith((HOME, HOME_ALT)), "C9: a frame must start with a home"
    return stream[len(HOME):] if stream.startswith(HOME) else stream[len(HOME_ALT):]


def _rows_of(body):
    """Split a frame body into its terminal lines and strip color SGRs."""
    return [_strip_sgr(line) for line in body.split(CRLF)]


def _drawn_colors(body):
    """Walk a frame body: yield (char, palette index, color in force) for every
    non-space palette character, exactly as the accept fixture reads a screen."""
    out = []
    cur = None
    i = 0
    while i < len(body):
        m = TRIPLE_RE.match(body, i)
        if m:
            cur = tuple(int(g) for g in m.groups())
            i = m.end()
            continue
        ch = body[i]
        if ch != " " and ch in PALETTE:
            out.append((ch, PALETTE.index(ch), cur))
        i += 1
    return out


# ---------------------------------------------------------------------------
# C10 — the color table and its mapping
# ---------------------------------------------------------------------------

def test_color_table_is_the_spec_table():
    assert fire.FIRE_COLORS == COLORS, "C10: the truecolor table must be SPEC-F's"
    assert 0 not in fire.FIRE_COLORS, "C10: index 0 (space) has no color in the table"


def test_color_sgr_is_exactly_the_table_triple():
    for idx, (r, g, b) in COLORS.items():
        got = fire.color_sgr(PALETTE[idx])
        want = f"\x1b[38;2;{r};{g};{b}m"
        assert got == want, f"C10: char {PALETTE[idx]!r} (index {idx}) -> {got!r}"
    assert fire.color_sgr(" ") == "", "C10: a space carries no color"


# ---------------------------------------------------------------------------
# C9 — frame geometry
# ---------------------------------------------------------------------------

def test_frame_homes_first_and_paints_the_exact_grid():
    args = _args("--frames", "1", "--seed", "7")
    heat = _heats(args, 1)[0]
    stream = fire.frame_bytes(heat, color=True)

    assert stream.startswith((HOME, HOME_ALT)), "C9: home before the frame"
    body = _frame_body(stream)
    assert not body.endswith("\n"), "C9: no trailing newline after the last row"
    assert body.count("\n") == HEIGHT - 1, (
        "C9: exactly height-1 line advances per frame (no scroll)")

    rows = _rows_of(body)
    assert len(rows) == HEIGHT, f"C9: {len(rows)} lines, expected {HEIGHT}"
    for y, row in enumerate(rows):
        assert len(row) == WIDTH, f"C9: row {y} is {len(row)} cells, expected {WIDTH}"
        assert all(ch in PALETTE for ch in row), f"C9/C5: row {y} outside the palette"
    assert rows[0] == " " * WIDTH, "C9/C8b: the top row of a height-12 frame is dark"
    assert any(ch in "%@" for ch in rows[-1]), "C9/C7: the bottom row must be hot"


def test_every_drawn_character_carries_exactly_its_table_color():
    args = _args("--frames", "1", "--seed", "7")
    body = _frame_body(fire.frame_bytes(_heats(args, 1)[0], color=True))

    drawn = _drawn_colors(body)
    assert drawn, "C10: a frame with a hot bottom row must draw colored cells"
    wrong = [(ch, idx, cur) for ch, idx, cur in drawn if cur != COLORS[idx]]
    assert not wrong, f"C10: characters drawn with the wrong color: {wrong[:3]}"

    triples = [tuple(int(g) for g in m.groups()) for m in TRIPLE_RE.finditer(body)]
    table = {tuple(v) for v in COLORS.values()}
    off_table = [t for t in triples if t not in table]
    assert not off_table, f"C10: truecolor outside the SPEC-F table: {off_table[:3]}"
    assert any(t in HOT for t in triples), "C10: no hot-class (index 8/9) color"


def test_no_color_suppresses_every_truecolor_and_keeps_the_geometry():
    args = _args("--frames", "1", "--seed", "7")
    heat = _heats(args, 1)[0]
    plain = fire.frame_bytes(heat, color=False)

    assert "\x1b[38;2;" not in plain, "C10: --no-color emits no truecolor triple"
    assert _strip_sgr(fire.frame_bytes(heat, color=True)) == plain, (
        "C10: --no-color must not change the geometry")
    assert _rows_of(_frame_body(plain)) == _rows_of(_frame_body(
        fire.frame_bytes(heat, color=True))), "C10: same grid with and without color"
    assert plain.startswith((HOME, HOME_ALT)), "C9: home is not a color, it stays"


def test_stream_uses_only_home_hide_show_and_sgr_no_alt_screen_no_scroll():
    """C9: no alt-screen, no erase, no cursor movement — the only way to draw
    height x width without scrolling is to home and write the grid."""
    args = _args("--frames", "2", "--seed", "7")
    stream = fire.interactive_stream(_heats(args, 2), color=True)

    for params, final in CSI_RE.findall(stream):
        ok = (
            (final in "hl" and params == "?25")
            or (final == "m" and (params == "0"
                                  or re.fullmatch(r"38;2;\d{1,3};\d{1,3};\d{1,3}",
                                                  params)))
            or (final == "H" and params in ("", "1", "1;1"))
        )
        assert ok, f"C9: unexpected control sequence ESC[{params}{final}"
    for forbidden in ("?1049", "?1047", "?47", "J", "A", "B", "C", "D"):
        assert not any(p == forbidden or p.startswith(forbidden)
                       for p, _ in CSI_RE.findall(stream)), (
            f"C9: alt-screen/erase/cursor-move sequence {forbidden!r} in the stream")


# ---------------------------------------------------------------------------
# C9/C10 — the whole interactive stream
# ---------------------------------------------------------------------------

def test_stream_hides_cursor_before_the_first_frame_and_homes_before_every_frame():
    args = _args("--frames", "3", "--seed", "7")
    heats = _heats(args, 3)
    stream = fire.interactive_stream(heats, color=True)

    assert stream.startswith(HIDE), "C9: cursor hidden at the start"
    homes = [m.start() for m in re.finditer(r"\x1b\[(?:1;1)?H", stream)]
    assert homes, "C9: every frame must home"
    assert 0 <= stream.index(HIDE) < min(homes), (
        "C9: cursor must be hidden before the first frame's home")
    assert len(homes) == len(heats), (
        f"C9: {len(homes)} homes for {len(heats)} frames — every frame, "
        "including the first, must home")
    # Each home starts exactly one frame: the segment up to the next home
    # (or to the cleanup) is one grid — height-1 line advances, no more.
    ends = homes[1:] + [stream.index(RESET)]
    for home, end in zip(homes, ends):
        segment = stream[home:end]
        assert segment.startswith((HOME, HOME_ALT))
        assert segment.count("\n") == HEIGHT - 1, (
            "C9: a frame segment must advance exactly height-1 lines")
    assert stream.count("\n") == len(heats) * (HEIGHT - 1), (
        "C9: no line advance beyond the frame grid (no scroll)")


def test_cleanup_is_reset_then_show_exactly_once_at_the_end():
    args = _args("--frames", "2", "--seed", "7")
    stream = fire.interactive_stream(_heats(args, 2), color=True)

    assert fire.CLEANUP == RESET + SHOW, "C10: cleanup bytes are ESC[0m then ESC[?25h"
    assert stream.endswith(RESET + SHOW), "C10: natural exit emits the cleanup"
    assert stream.count(RESET) == 1, "C10: exactly one reset"
    assert stream.count(SHOW) == 1, "C9: exactly one cursor show, at the end"
    assert stream.index(RESET) < stream.index(SHOW), "C10: cleanup order"
    assert stream.index(RESET) == len(stream) - len(RESET + SHOW), (
        "C10: cleanup comes after the last frame, with nothing in between")
    assert not stream[:stream.index(RESET)].endswith("\n"), (
        "C9: no trailing newline after the last frame row")


# ---------------------------------------------------------------------------
# run_interactive — the writer, driven through a stand-in terminal
# ---------------------------------------------------------------------------

def test_run_interactive_writes_exactly_the_pure_stream_and_exits_zero():
    args = _args("--frames", "3", "--seed", "7", "--fps", "60")
    buf = FakeTty()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", buf)
        rc = fire.run_interactive(args)
    stream = buf.getvalue()

    assert rc == 0, "C10: a natural interactive run exits 0"
    assert stream == fire.interactive_stream(_heats(args, 3), color=True), (
        "C9/C10: the writer must emit hide, home+frame per frame, cleanup")
    assert stream.startswith(HIDE) and stream.endswith(RESET + SHOW)


def test_run_interactive_no_color_has_no_truecolor_but_keeps_hide_and_show():
    args = _args("--frames", "2", "--seed", "9", "--fps", "60", "--no-color")
    buf = FakeTty()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", buf)
        rc = fire.run_interactive(args)
    stream = buf.getvalue()

    assert rc == 0
    assert "\x1b[38;2;" not in stream, "C10: --no-color interactive run has no triple"
    assert stream.startswith(HIDE), "C9: cursor hidden even with --no-color"
    assert stream.endswith(RESET + SHOW), "C9: hide/show survive --no-color"
    assert stream == fire.interactive_stream(_heats(args, 2), color=False), (
        "C10: --no-color changes the color only, not the geometry")


def test_main_picks_interactive_only_on_a_tty_and_leaves_batch_untouched():
    argv = ["--width", "12", "--height", "6", "--frames", "2", "--seed", "3"]

    plain = io.StringIO()  # isatty() False -> batch
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", plain)
        assert fire.main(argv) in (0, None)
    batch = plain.getvalue()
    assert "\x1b" not in batch, "C6/Q4: batch output stays uncolored and plain"
    assert batch.endswith("\n") and not batch.endswith("\n\n")

    tty = FakeTty()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", tty)
        assert fire.main(argv) in (0, None)
    interactive = tty.getvalue()
    assert interactive.startswith(HIDE), "C9: a tty stdout takes the interactive branch"
    assert interactive.endswith(RESET + SHOW)
    assert batch != interactive, "C9: the two branches are different renderings"


# ---------------------------------------------------------------------------
# C11 — Ctrl+C (SIGINT) stops the torch and cleans up
# ---------------------------------------------------------------------------

def test_sigint_stops_the_torch_and_emits_reset_then_show():
    args = _args("--frames", "200", "--seed", "11", "--fps", "10")  # ~20 s if uninterrupted
    buf = FakeTty()

    def _interrupt():
        # A real SIGINT to this process — the same signal the PTY line
        # discipline delivers for Ctrl+C (the PTY itself is the accept
        # fixture's job).
        signal.raise_signal(signal.SIGINT)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", buf)
        timer = threading.Timer(0.3, _interrupt)
        timer.start()
        try:
            rc = fire.run_interactive(args)
        finally:
            timer.cancel()
    stream = buf.getvalue()

    assert rc in (0, 130), f"C11: SIGINT exit must be 0 or 130, got {rc}"
    homes = len(re.findall(r"\x1b\[(?:1;1)?H", stream))
    assert 1 <= homes < 200, (
        f"C11: the torch kept drawing ({homes} frames) after Ctrl+C")
    assert stream.endswith(RESET + SHOW), "C11: cleanup before exit"
    assert stream.index(RESET) < stream.index(SHOW), "C11: cleanup order"
    assert stream.count(SHOW) == 1, "C11: the cursor is shown exactly once, at exit"


def test_sigint_handler_is_not_left_installed_for_the_rest_of_the_process():
    """The interactive branch borrows the terminal; it must not leave a private
    SIGINT handler behind (the batch branch and the caller keep default behavior)."""
    before = signal.getsignal(signal.SIGINT)
    args = _args("--frames", "1", "--seed", "1", "--fps", "60")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", FakeTty())
        fire.run_interactive(args)
    assert signal.getsignal(signal.SIGINT) == before, (
        "C11: SIGINT handling must be restored to what the process had")


def test_batch_branch_is_reachable_after_an_interrupted_interactive_run():
    """C11 must not damage the process: a batch render after an interrupted
    interactive run still produces the C6 output."""
    args = _args("--frames", "100", "--seed", "11", "--fps", "10")
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", FakeTty())
        timer = threading.Timer(0.1, lambda: signal.raise_signal(signal.SIGINT))
        timer.start()
        try:
            fire.run_interactive(args)
        finally:
            timer.cancel()

    buf = io.StringIO()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, "stdout", buf)
        fire.run_batch(_args("--width", "10", "--height", "6",
                             "--frames", "2", "--seed", "4"))
    out = buf.getvalue()
    assert "\x1b" not in out, "C6: batch output after an interrupt stays plain"
    assert out.endswith("\n") and not out.endswith("\n\n")
    assert len(out.split("\n")[:-1]) == 2 * 6 + 1, "C6: batch structure intact"
