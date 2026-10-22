"""Accept fixture — host-authored BOUNDARY oracle (frozen by the contract
lock; the machine must not edit it).

PROVENANCE of every expected literal: SPEC-FIRE-2026-10-22 (SPEC-F),
sections C9, C10, C11. Boundary: the program runs on a REAL PTY (its stdin/
stdout/stderr are the slave) through the trusted judge
tests/fixtures/vt_screen.py, imported by explicit path (no conftest).

Geometry claims (C9) are checked through the judge's invariants: no_scroll,
no_wrap, stable_line_origin, no_residue (with prelude), cursor_restored,
termios_restored. Color claims (C10) are checked on RAW BYTES — the judge
models geometry only. C11 delivers Ctrl+C as a real keystroke through the PTY
line discipline.
"""

import importlib.util
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
FIRE = str(REPO / "src" / "fire.py")

_spec = importlib.util.spec_from_file_location(
    "vt_screen", REPO / "tests" / "fixtures" / "vt_screen.py")
vt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vt)

# SPEC-F C5
PALETTE = " .:-=+*#%@"
# SPEC-F C10 color table: character index -> (R, G, B)
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
_HOT = {COLORS[8], COLORS[9]}
TRIPLE_RE = re.compile(rb"\x1b\[38;2;(\d+);(\d+);(\d+)m")

# Program window: height == PTY rows, so C8b's guaranteed-dark top row is the
# screen's top row; cols > width so wrapping is observable as a defect.
WIDTH, HEIGHT = 24, 12
ROWS, COLS = 12, 40
# C9 no_residue: the terminal showed this BEFORE the program started: every
# cell of the program's row-0 drawing area filled with 'R'. A program that
# homes but then skips painting some cells of a drawn row leaves this residue
# — the judge sees it (C5/C6: every cell of a drawn row IS written, spaces
# included). Beyond WIDTH the window is outside the program's drawing area.
PRELUDE = b"\x1b[H" + b"R" * WIDTH

# Frame-boundary token identical to the judge's (ESC[H, ESC[1;1H or ED).
_BOUNDARY = re.compile(rb"(?:\x1b\[H|\x1b\[1;1H|\x1b\[[0-3]?J)+")


def _argv(*extra):
    return [sys.executable, FIRE,
            "--width", str(WIDTH), "--height", str(HEIGHT), *extra]


def _last_boundary(raw: bytes) -> int:
    last = None
    for m in _BOUNDARY.finditer(raw):
        last = m
    assert last is not None, "C9: program must home before every frame"
    return last.start()


def _first_boundary(raw: bytes) -> int:
    m = _BOUNDARY.search(raw)
    assert m is not None, "C9: program must home before the first frame"
    return m.start()


def _assert_clean(result):
    bad = {name: msg for name, msg in vt.check_all(result).items()
           if msg is not None}
    assert not bad, f"C9: judge invariants failed: {bad}"


def _assert_cleanup_order(raw: bytes, label: str):
    reset = raw.find(b"\x1b[0m")
    show = raw.find(b"\x1b[?25h")
    assert 0 <= reset, f"{label}: no ESC[0m before exit"
    assert 0 <= show, f"{label}: no ESC[?25h before exit"
    assert reset < show, f"{label}: cleanup order must be ESC[0m then ESC[?25h"


# ------------------------------------------------ C9/C10 natural interactive run
def test_interactive_geometry_color_and_clean_exit():
    res = vt.run_pty(_argv("--frames", "3", "--seed", "7"),
                     rows=ROWS, cols=COLS, timeout=20, prelude=PRELUDE)
    # C9: every judge invariant passes, including exit rc=0 and no timeout.
    _assert_clean(res)
    raw = res.raw

    # C9: cursor hidden at start, before the first frame's home.
    hide = raw.find(b"\x1b[?25l")
    assert 0 <= hide < _first_boundary(raw), (
        "C9: cursor must be hidden before the first frame")
    # C10: natural exit emits ESC[0m then ESC[?25h.
    _assert_cleanup_order(raw, "C10")

    # C10: every truecolor triple in the stream is from the table; at least
    # one hot-class (index 8/9) triple is present.
    triples = [tuple(map(int, m.groups())) for m in TRIPLE_RE.finditer(raw)]
    table = {tuple(v) for v in COLORS.values()}
    assert triples, "C10: colored run must emit truecolor triples"
    off_table = [t for t in triples if t not in table]
    assert not off_table, f"C10: colors outside the SPEC-F table: {off_table[:3]}"
    assert any(t in _HOT for t in triples), "C10: no hot-class color present"

    # C10: every drawn non-space character carries exactly its table color.
    # Parse the final frame region (from the last frame boundary).
    cur = None
    drawn = 0
    i = _last_boundary(raw)
    while i < len(raw):
        m = TRIPLE_RE.match(raw, i)
        if m:
            cur = tuple(map(int, m.groups()))
            i = m.end()
            continue
        ch = raw[i:i + 1]
        if ch != b" " and ch.decode("latin-1") in PALETTE:
            idx = PALETTE.index(ch.decode("latin-1"))
            assert cur == COLORS[idx], (
                f"C10: char {ch!r} (index {idx}) drawn with color {cur}")
            drawn += 1
        i += 1
    # The final frame must actually be painted: at least the seeded rows
    # (every frame's bottom rows are hot by C4/C7).
    assert drawn >= HEIGHT * WIDTH // 2, (
        f"C9: final frame painted only {drawn} characters")

    # C9 final screen satisfies C5/C7/C8b at the grid level: bottom row hot,
    # top row dark (the same guarantee as C8b: height 12).
    screen = res.screen.render()
    bottom = screen[ROWS - 1]
    assert any(ch in "%@" for ch in bottom), (
        f"C9/C7: bottom screen row not hot: {bottom!r}")
    assert screen[0] == " " * COLS, (
        f"C9/C8b: top screen row not dark: {screen[0]!r}")


# ------------------------------------------------------------- C10 --no-color
def test_no_color_emits_no_truecolor():
    res = vt.run_pty(_argv("--frames", "3", "--seed", "9", "--no-color"),
                     rows=ROWS, cols=COLS, timeout=20, prelude=PRELUDE)
    _assert_clean(res)
    assert b"\x1b[38;2;" not in res.raw, (
        "C10: --no-color interactive run must contain no truecolor triples")
    assert b"\x1b[?25l" in res.raw, "C9: cursor hidden even with --no-color"
    _assert_cleanup_order(res.raw, "C10/--no-color")


# ---------------------------------------------------------------- C11 Ctrl+C
def test_ctrl_c_stops_with_cleanup():
    # A real Ctrl+C through the PTY line discipline at t=0.8s; the program
    # would otherwise run ~4s (40 frames at 10 fps).
    res = vt.run_pty(_argv("--frames", "40", "--fps", "10", "--seed", "11"),
                     feed=[(0.8, b"\x03")],
                     rows=ROWS, cols=COLS, timeout=20, prelude=PRELUDE)
    assert not res.timed_out, "C11: program must stop on Ctrl+C, not run on"
    assert res.rc in (0, 130), (
        f"C11: SIGINT exit must be 0 or 130, got {res.rc}")
    # Geometry invariants must hold up to the interruption.
    vt.assert_no_scroll(res.screen)
    vt.assert_no_wrap(res.screen)
    vt.assert_stable_line_origin(res.screen)
    vt.assert_termios_restored(res)
    vt.assert_cursor_restored(res.screen)
    _assert_cleanup_order(res.raw, "C11")
