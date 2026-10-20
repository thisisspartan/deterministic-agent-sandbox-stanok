"""CC-307 minesweeper render tests — R1..R3 with negatives.

Expected frames are hand-derived literals from the pinned R1 format (quoted
in the ticket), never captured from the render under test. States are built
ONLY through src/minesweeper_engine; fixture seeds were found offline and
pinned literally:
  3x3/4 mines {(1,1),(1,2),(1,3),(2,1)} -> seed 179 (adj ((2,2,1),(3,4,1),(1,2,0)):
    (3,3) is a zero cell, its flood opens {(3,3),(2,2),(3,2),(2,3)} with a
    numeric border 4/1/2 — numbers, zero-space and closed '#' in one frame).
  3x3/1 mine at CENTER (2,2) -> seed 5 (same fixture as the engine tests).
Rulers/prefixes are layout-independent on a fresh board, so the full frames
for 10x10/10, 9x9/9 and 5x10/3 initial states are pinned byte-exactly.
"""

import ast
import pathlib

import pytest

try:
    from src import minesweeper_engine as eng
    from src import minesweeper_render as rnd
except ImportError:
    import minesweeper_engine as eng
    import minesweeper_render as rnd

RENDER_SRC = pathlib.Path(__file__).resolve().parents[1] / "src/minesweeper_render.py"

SEED_3X3_4 = 179  # mines {(1,1),(1,2),(1,3),(2,1)}
SEED_3X3_CENTER = 5  # single mine at (2,2)


# ---------- local helpers (independent of the render under test)

def snapshot(s):
    return (s.seed, s.width, s.height, s.mines_total, s.mines, s.adj,
            s.opened, s.flagged, s.status, s.first_done)


@pytest.fixture()
def board34():
    return eng.new_game(SEED_3X3_4, 3, 3, 4)


# ---------- R1: byte-exact frames (3x3/4: numbers, zero flood, flag, closed #)

def test_initial_frame_bytes_3x3_4mines(board34):
    assert rnd.render(board34) == (
        "mines 4/4  open 0/5  playing",
        "",
        "  123",  # width<=9: units ruler only, prefix Hh+1 = 2
        "1 ###",
        "2 ###",
        "3 ###",
    )


def test_frame_with_numbers_zero_space_flag_and_closed(board34):
    s = eng.open_cell(board34, 3, 3)  # zero cell: floods (3,3) + border (2,2),(3,2),(2,3)
    s = eng.toggle_flag(s, 1, 1)  # flag on a mine
    assert s.status == "playing"
    assert rnd.render(s) == (
        "mines 3/4  open 4/5  playing",  # R1: flag decrements the remaining count
        "",
        "  123",
        "1 F##",  # flagged -> F; closed mine and closed safe cell -> #
        "2 #41",  # opened cells show adj digits 4 and 1
        "3 #2 ",  # opened zero cell (3,3) renders as a space
    )


# ---------- R1: counters

def test_mines_counter_decreases_with_flags(board34):
    one = eng.toggle_flag(board34, 1, 1)
    two = eng.toggle_flag(one, 2, 1)
    assert rnd.render(board34)[0] == "mines 4/4  open 0/5  playing"
    assert rnd.render(one)[0] == "mines 3/4  open 0/5  playing"
    assert rnd.render(two)[0] == "mines 2/4  open 0/5  playing"
    off = eng.toggle_flag(two, 1, 1)  # unflag restores the count
    assert rnd.render(off)[0] == "mines 3/4  open 0/5  playing"


def test_open_counter_counts_opened_only_never_mines(board34):
    s = eng.open_cell(board34, 3, 3)
    lost = eng.open_cell(s, 2, 1)  # step on a mine: it is NOT opened
    assert lost.status == "lost"
    assert len(lost.opened) == 4 and (2, 1) not in lost.opened
    assert rnd.render(lost)[0] == "mines 4/4  open 4/5  lost"  # open counts opened only


# ---------- R1: rulers and row prefixes

def test_tens_ruler_present_and_aligned_at_width_10():
    frame = rnd.render(eng.new_game(1, 10, 10, 10))
    # Hh = len(str(10)) = 2 -> ruler prefix is 3 chars; tens digit of column 10
    # sits at index 12; a fresh board is all-closed, so the whole frame is pinned.
    assert frame == (
        "mines 10/10  open 0/90  playing",
        "",
        " " * 3 + " " * 9 + "1",  # tens ruler: blank for x<10, "1" at x=10
        " " * 3 + "1234567890",  # units ruler
        " 1 " + "#" * 10,
        " 2 " + "#" * 10,
        " 3 " + "#" * 10,
        " 4 " + "#" * 10,
        " 5 " + "#" * 10,
        " 6 " + "#" * 10,
        " 7 " + "#" * 10,
        " 8 " + "#" * 10,
        " 9 " + "#" * 10,
        "10 " + "#" * 10,
    )


def test_no_tens_ruler_at_width_9():
    frame = rnd.render(eng.new_game(1, 9, 9, 9))
    assert frame == (
        "mines 9/9  open 0/72  playing",
        "",
        " " * 2 + "123456789",  # units ruler only: 1 + 9 lines, no tens ruler
        "1 " + "#" * 9,
        "2 " + "#" * 9,
        "3 " + "#" * 9,
        "4 " + "#" * 9,
        "5 " + "#" * 9,
        "6 " + "#" * 9,
        "7 " + "#" * 9,
        "8 " + "#" * 9,
        "9 " + "#" * 9,
    )


def test_row_prefix_pads_single_digits_at_height_10():
    frame = rnd.render(eng.new_game(2, 5, 10, 3))
    # Hh = len(str(10)) = 2 -> rows 1..9 are right-aligned to 2 digits
    assert frame == (
        "mines 3/3  open 0/47  playing",
        "",
        " " * 3 + "12345",  # width 5: no tens ruler, prefix 3 chars
        " 1 " + "#" * 5,
        " 2 " + "#" * 5,
        " 3 " + "#" * 5,
        " 4 " + "#" * 5,
        " 5 " + "#" * 5,
        " 6 " + "#" * 5,
        " 7 " + "#" * 5,
        " 8 " + "#" * 5,
        " 9 " + "#" * 5,
        "10 " + "#" * 5,
    )


# ---------- R2: purity & determinism

def test_render_never_mutates_state(board34):
    s = eng.toggle_flag(board34, 1, 1)
    s = eng.open_cell(s, 3, 3)
    before = snapshot(s)
    rnd.render(s)
    assert snapshot(s) == before  # deep-snapshot identical


def test_render_is_deterministic_and_returns_tuple_of_str(board34):
    s = eng.open_cell(board34, 3, 3)
    a = rnd.render(s)
    b = rnd.render(s)
    assert isinstance(a, tuple) and all(isinstance(line, str) for line in a)
    assert a == b  # byte-identical frame on repeated calls


# ---------- R3: full reveal after game over

def test_lost_frame_shows_all_mines_and_keeps_flags(board34):
    s = eng.toggle_flag(board34, 3, 1)  # flag on a SAFE cell
    s = eng.open_cell(s, 3, 3)
    s = eng.open_cell(s, 2, 1)  # step on an unflagged mine -> lost
    assert s.status == "lost"
    frame = rnd.render(s)
    assert frame == (
        "mines 3/4  open 4/5  lost",
        "",
        "  123",
        "1 **F",  # every mine is '*' after loss; the flag stays 'F' where it stood
        "2 *41",
        "3 *2 ",
    )
    revealed = {(x, y) for y in range(1, 4) for x in range(1, 4)
                if frame[2 + y][2 + x - 1] == "*"}  # row y is at index 2+y (width 3: no tens ruler)
    assert revealed == s.mines  # ALL mines shown, none missed


def test_lost_frame_center_mine_seed5():
    s = eng.open_cell(eng.new_game(SEED_3X3_CENTER, 3, 3, 1), 1, 1)
    out = eng.open_cell(s, 2, 2)  # second action lands on the mine
    assert out.status == "lost"
    assert rnd.render(out) == (
        "mines 1/1  open 1/8  lost",
        "",
        "  123",
        "1 1##",
        "2 #*#",
        "3 ###",
    )


def test_won_frame_shows_all_mines_and_preserves_flags(board34):
    s = eng.toggle_flag(board34, 1, 1)  # flag on a mine
    s = eng.open_cell(s, 3, 3)  # zero flood opens (2,2),(3,2),(2,3) too
    s = eng.open_cell(s, 3, 1)  # last safe cell -> won
    assert s.status == "won"
    assert s.flagged == frozenset({(1, 1)})  # the flag is preserved in the state
    assert rnd.render(s) == (
        "mines 3/4  open 5/5  won",
        "",
        "  123",
        "1 **1",  # all mines '*' after win (flagged mine included, '*' outranks 'F')
        "2 *41",
        "3 *2 ",
    )


# ---------- R1: the module imports nothing (AST scan of the real source)

def test_render_module_has_no_imports():
    tree = ast.parse(RENDER_SRC.read_text(encoding="utf-8"))
    bad = [n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not bad, f"render must import nothing, found: {bad}"
