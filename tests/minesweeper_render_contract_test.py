"""Calibrated contract oracle for src/minesweeper_render.py (SPEC-MINESWEEPER-CONSOLE R1..R3).

Independence policy: expected frames are host-authored literals (provenance:
SPEC R1 byte format, quoted here) or re-derived from an independent
reference implementation of the pinned format written in this file — never
captured from the render under test. States are built ONLY through
src/minesweeper_engine (already pinned by its own oracle). Mutants RM1..RM6
(see specs/STATUS.md) each turn at least one test RED. Host-authored; the
machine must not edit.
"""
import ast
import pathlib
import random

import pytest

try:
    from src import minesweeper_engine as eng
    from src import minesweeper_render as rnd
except ImportError:
    import minesweeper_engine as eng
    import minesweeper_render as rnd

RENDER_SRC = pathlib.Path(__file__).resolve().parents[1] / "src/minesweeper_render.py"


# ---------- independent reference of the pinned frame format (SPEC R1)

def ref_frame(state):
    w, h = state.width, state.height
    safe_total = w * h - state.mines_total
    word = {"playing": "playing", "won": "won", "lost": "lost"}[state.status]
    lines = ["mines {}/{}  open {}/{}  {}".format(
        state.mines_total - len(state.flagged), state.mines_total,
        len(state.opened), safe_total, word), ""]
    hh = len(str(h))
    if w > 9:
        lines.append(" " * (hh + 1) + "".join(
            str(x // 10) if x >= 10 else " " for x in range(1, w + 1)))
    lines.append(" " * (hh + 1) + "".join(str(x % 10) for x in range(1, w + 1)))
    for y in range(1, h + 1):
        cells = []
        for x in range(1, w + 1):
            c = (x, y)
            if state.status != "playing" and c in state.mines:
                ch = "*"
            elif c in state.flagged:
                ch = "F"
            elif c in state.opened:
                ch = " " if state.adj[y - 1][x - 1] == 0 else str(state.adj[y - 1][x - 1])
            else:
                ch = "#"
            cells.append(ch)
        lines.append(f"{y:>{hh}} " + "".join(cells))
    return tuple(lines)


def ref_mines(seed, w, h, n):
    return frozenset(random.Random(seed).sample(
        [(x, y) for y in range(1, h + 1) for x in range(1, w + 1)], n))


def center_mine_seed():
    return next(sd for sd in range(1, 10000) if ref_mines(sd, 3, 3, 1) == {(2, 2)})


SEED_CENTER = None  # resolved at first use


# ---------- R1: hard-pinned byte-exact frames (provenance: SPEC R1 layout,
# 3x3/1 mine at center (2,2) -> no zero cells; every literal below derived
# by hand from the pinned format)

@pytest.fixture()
def center3():
    global SEED_CENTER
    if SEED_CENTER is None:
        SEED_CENTER = center_mine_seed()
    return eng.new_game(SEED_CENTER, 3, 3, 1)


def test_initial_frame_bytes(center3):
    assert rnd.render(center3) == (
        "mines 1/1  open 0/8  playing",
        "",
        "  123",
        "1 ###",
        "2 ###",
        "3 ###",
    )


def test_frame_after_open_and_flag(center3):
    s = eng.open_cell(center3, 1, 1)
    s = eng.toggle_flag(s, 2, 2)
    assert rnd.render(s) == (
        "mines 0/1  open 1/8  playing",  # flag decrements remaining (R1)
        "",
        "  123",
        "1 1##",
        "2 #F#",
        "3 ###",
    )


def test_lost_frame_reveals_all_mines(center3):
    s = eng.open_cell(center3, 1, 1)
    out = eng.open_cell(s, 2, 2)  # stepping on the mine (not first action)
    assert out.status == "lost"
    assert rnd.render(out) == (
        "mines 1/1  open 1/8  lost",
        "",
        "  123",
        "1 1##",
        "2 #*#",  # the mine is shown as '*' after loss (R3)
        "3 ###",
    )


def test_won_frame_bytes(center3):
    cur = center3
    for c in [(1, 1), (2, 1), (3, 1), (1, 2), (3, 2), (1, 3), (2, 3), (3, 3)]:
        if c not in cur.opened:
            cur = eng.open_cell(cur, *c)
    assert cur.status == "won"
    assert rnd.render(cur) == (
        "mines 1/1  open 8/8  won",
        "",
        "  123",
        "1 111",
        "2 1*1",  # all mines shown after win as well
        "3 111",
    )


# ---------- R1: rulers and row prefixes (dynamic, 10-wide and 10-tall boards)

def test_tens_ruler_present_at_width_10():
    s = eng.new_game(1, 10, 10, 12)
    frame = rnd.render(s)
    # pinned exact ruler lines (provenance: SPEC R1): prefix is len(str(h))+1
    # = 3 chars at height 10, so the tens digit of column 10 sits at index 12
    assert frame[2] == " " * 3 + " " * 9 + "1"
    assert frame[3] == " " * 3 + "1234567890"
    assert frame == ref_frame(s)
    s9 = eng.new_game(1, 9, 9, 10)
    f9 = rnd.render(s9)
    assert f9[1] == "" and f9[2] == " " * 2 + "123456789"  # no tens ruler <=9
    assert f9 == ref_frame(s9)


def test_row_prefix_width_for_height_10():
    s = eng.new_game(2, 5, 10, 3)
    frame = rnd.render(s)
    # R1: Hh = len(str(height)) = 2 -> one-digit rows are right-aligned padded
    row1 = next(ln for ln in frame if ln.startswith(" 1 ") or ln.startswith(" 1#"))
    assert row1 == " 1 #####"
    assert any(ln == "10 #####" for ln in frame)
    assert frame == ref_frame(s)


def test_opened_zero_cell_is_space_and_numbers_are_digits():
    seed = next(sd for sd in range(1, 20000) if ref_mines(sd, 4, 4, 1) == {(4, 4)})
    s = eng.new_game(seed, 4, 4, 1)
    out = eng.open_cell(s, 1, 1)  # zero region floods with numeric border
    frame = rnd.render(out)
    assert frame == ref_frame(out)
    zeros = [c for c in out.opened if out.adj[c[1] - 1][c[0] - 1] == 0]
    assert zeros
    # width 4 -> no tens ruler: lines are counter, blank, units ruler, rows;
    # row prefix at height 4 is "1 " (2 chars) -> cell x sits at index 2+x-1
    row = frame[3]
    assert all((row[2 + i] == " ") == ((i + 1, 1) in zeros) for i in range(4))


# ---------- R2: purity & determinism

def test_render_never_mutates_state_and_is_deterministic(center3):
    s = eng.toggle_flag(center3, 1, 1)
    snap = (s.mines, s.adj, s.opened, s.flagged, s.status, s.first_done)
    a = rnd.render(s)
    b = rnd.render(s)
    assert a == b
    assert isinstance(a, tuple) and all(isinstance(line, str) for line in a)
    assert (s.mines, s.adj, s.opened, s.flagged, s.status, s.first_done) == snap
    assert a == ref_frame(s)


# ---------- R1: module imports nothing (AST scan of the real source)

def test_render_module_has_no_imports():
    tree = ast.parse(RENDER_SRC.read_text(encoding="utf-8"))
    bad = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not bad, f"render must import nothing, found: {bad}"
