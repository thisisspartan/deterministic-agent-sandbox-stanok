"""CC-308 minesweeper CLI tests — C1..C5 on the real stdin boundary.

The CLI is observed ONLY through real subprocess runs
(sys.executable -m src.minesweeper_cli, cwd = tree root, piped stdin).
Expected bytes are pinned from the ticket contract (banner, presets and
rejection strings quoted verbatim) and re-derived through the tree's own
engine+render — each already pinned by its own oracle — never captured from
the CLI under test. Fixture seeds found offline and pinned literally:
  seed 5 — 3x3/1 with the mine at the center (2,2) (same fixture as the
           engine/render tests);
  seed 1 — beginner 9x9/10 where (1,1) is a zero cell (a full win by opening
           every non-mine cell in row-major order) and (4,6) is a mine.
"""

import ast
import pathlib
import random
import subprocess
import sys

import pytest

try:
    from src import minesweeper_engine as eng
    from src import minesweeper_render as rnd
except ImportError:
    import minesweeper_engine as eng
    import minesweeper_render as rnd

ROOT = pathlib.Path(__file__).resolve().parents[1]
CLI_SRC = ROOT / "src" / "minesweeper_cli.py"
MOD = "src.minesweeper_cli"

# pinned verbatim (provenance: ticket C2 banner, C3 presets)
BANNER = ("commands: open X Y | flag X Y | new | difficulty beginner|medium|expert"
          " | custom W H MINES | help | quit")
PRESETS = {"beginner": (9, 9, 10), "medium": (16, 16, 40), "expert": (30, 16, 99)}

SEED_CENTER3 = 5  # 3x3/1, mine at (2,2)
SEED_WIN = 1  # beginner 9x9/10: (1,1) zero cell, (4,6) mine


# ---------- local helpers (independent of the CLI under test)

def ref_mines(seed, w, h, n):
    """Independent placement model: random.Random(seed).sample over row-major cells."""
    return frozenset(random.Random(seed).sample(
        [(x, y) for y in range(1, h + 1) for x in range(1, w + 1)], n))


def _run(args, stdin_text, timeout=30):
    try:
        p = subprocess.run([sys.executable, "-m", MOD, *args],
                           input=stdin_text.encode(), capture_output=True,
                           timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail("CLI did not terminate in %ss: args=%r" % (timeout, args))
    return p.returncode, p.stdout.decode(), p.stderr.decode()


def _lines(out):
    return out.rstrip("\n").split("\n")


def _frame_count(out):
    return sum(1 for ln in _lines(out) if ln.startswith("mines "))


def _last_frame(out, length):
    """The final frame: from the last counter line, exactly `length` lines
    (2 header + rulers + height rows) — rejection lines after it are excluded."""
    lines = _lines(out)
    start = max(i for i, ln in enumerate(lines) if ln.startswith("mines "))
    return lines[start:start + length]


def _initial_frame(seed, cfg=(9, 9, 10)):
    return tuple(rnd.render(eng.new_game(seed, *cfg)))


# ---------- C1: usage / exit codes on the real boundary

@pytest.mark.parametrize("args", [
    ["--nope"], ["--seed"], ["--seed", "abc"], ["--seed", "1.5"],
    ["extra"], ["--seed", "1", "extra"],
])
def test_bad_invocation_usage_rc2(args):
    rc, out, err = _run(args, "")
    assert rc == 2
    assert "usage" in err.lower(), err
    assert out == ""


def test_default_seed_is_zero_and_seed_flag_is_honored():
    pipe = "custom 3 3 1\nopen 1 1\nopen 2 2\n"
    rc0, out_default, _ = _run([], pipe)
    rcz, out_zero, _ = _run(["--seed", "0"], pipe)
    assert rc0 == 0 and rcz == 0
    assert out_default == out_zero  # default seed is exactly 0
    # seed 5 places the single 3x3 mine at the center (ref model): opening
    # (1,1) shows a '1', then (2,2) steps on the mine -> the center '*' frame
    rc5, out5, _ = _run(["--seed", str(SEED_CENTER3)], pipe)
    assert rc5 == 0
    assert out5 != out_default  # the --seed value reaches the layout
    assert _last_frame(out5, 6) == [
        "mines 1/1  open 1/8  lost",
        "",
        "  123",
        "1 1##",
        "2 #*#",
        "3 ###",
    ]


# ---------- C2: banner, initial frame, quit, EOF

def test_banner_is_first_line_and_initial_beginner_frame_follows():
    rc, out, err = _run(["--seed", "7"], "")
    assert rc == 0  # EOF terminates with rc 0
    assert err == ""
    assert _lines(out)[0] == BANNER
    assert out == "\n".join([BANNER] + list(_initial_frame(7))) + "\n"


def test_quit_terminates_immediately_rc0():
    rc, out, _ = _run(["--seed", "7"], "quit\nopen 1 1\n")
    assert rc == 0
    assert _frame_count(out) == 1  # only the initial frame: nothing runs after quit
    assert "rejected" not in out
    assert out == "\n".join([BANNER] + list(_initial_frame(7))) + "\n"


# ---------- C2/C3: seed arithmetic — every new game uses seed + games_played

def test_initial_game_uses_the_base_seed():
    opened = tuple(rnd.render(eng.open_cell(eng.new_game(1, 9, 9, 10), 1, 1)))
    rc, out, _ = _run(["--seed", "1"], "open 1 1\n")
    assert rc == 0
    assert out.endswith("\n".join(opened) + "\n")


def test_new_uses_the_next_games_played_seed():
    # seed semantics per C2: the value is used, then games_played grows —
    # initial game seed 0+0, first new 0+0, second new 0+1 (same semantics
    # as the provided contract oracle); the final open exposes the layout
    opened = tuple(rnd.render(eng.open_cell(eng.new_game(1, 9, 9, 10), 1, 1)))
    rc, out, _ = _run([], "new\nnew\nopen 1 1\n")
    assert rc == 0
    assert _frame_count(out) == 4  # initial + two new games + the opened frame
    assert out.endswith("\n".join(opened) + "\n")


def test_difficulty_and_custom_advance_games_played():
    # initial seed 2 (gp 0), difficulty medium (seed 2, gp -> 1),
    # custom 6 6 4 (seed 3, gp -> 2): the final open exposes the custom layout
    opened = tuple(rnd.render(eng.open_cell(eng.new_game(3, 6, 6, 4), 1, 1)))
    rc, out, _ = _run(["--seed", "2"], "difficulty medium\ncustom 6 6 4\nopen 1 1\n")
    assert rc == 0
    assert out.endswith("\n".join(opened) + "\n")


# ---------- C3/C4: full win and loss transcripts, seeded, reproducible

def test_full_beginner_win_transcript_seed1():
    mines = ref_mines(SEED_WIN, 9, 9, 10)
    cmds = ["open %d %d" % (x, y)
            for y in range(1, 10) for x in range(1, 10) if (x, y) not in mines]
    rc, out, _ = _run(["--seed", str(SEED_WIN)], "\n".join(cmds) + "\n")
    assert rc == 0
    frame = _last_frame(out, 12)
    assert frame[0] == "mines 10/10  open 71/71  won"
    board = "\n".join(frame)
    assert "#" not in board and "F" not in board  # every safe cell is open in the final frame
    assert board.count("*") == 10  # R3: the won frame shows every mine
    for y in range(1, 10):  # the '*' positions are exactly the seeded mine layout
        for x in range(1, 10):
            if (x, y) in mines:
                assert frame[3 + y - 1][2 + x - 1] == "*"


def test_loss_open_on_mine_shows_final_frame_then_game_over():
    mines = ref_mines(SEED_WIN, 9, 9, 10)
    assert (4, 6) in mines
    rc, out, _ = _run(["--seed", str(SEED_WIN)], "open 1 1\nopen 4 6\nopen 2 2\n")
    assert rc == 0
    frame = _last_frame(out, 12)
    assert frame[0].endswith(" lost")
    assert sum(ln.count("*") for ln in frame) == 10  # all mines revealed on loss
    assert out.count("rejected: game over") == 1  # open 2 2 after the loss
    assert out.count("rejected") == 1


# ---------- C3: every pinned rejection string; the field is never mutated

def test_rejections_verbatim_field_unchanged():
    cmds = ["foo", "open a b", "open 1", "open 1 1 2", "open 0 5", "open 5 99",
            "flag 0 0", "flag 10 1", "", "   ",
            "difficulty", "difficulty nope",
            "custom 1 1", "custom a b c", "custom 0 0 0", "custom 100 1 1",
            "custom 3 3 9", "custom 1 33 1"]
    rc, out, _ = _run([], "\n".join(cmds) + "\n")
    assert rc == 0
    expect = "\n".join([BANNER] + list(_initial_frame(0)) + [
        "rejected: unknown command",
        "rejected: bad arguments", "rejected: bad arguments", "rejected: bad arguments",
        "rejected: out of range", "rejected: out of range",
        "rejected: out of range", "rejected: out of range",
        "rejected: bad arguments", "rejected: unknown difficulty",
        "rejected: bad arguments", "rejected: bad arguments",
        "rejected: invalid size", "rejected: invalid size",
        "rejected: invalid size", "rejected: invalid size",
    ]) + "\n"
    assert out == expect  # byte-exact: blank lines ignored, no frame after the initial one
    assert _frame_count(out) == 1  # bad input never mutates the field


def test_flag_open_interactions_and_game_over_on_pinned_3x3():
    cmds = ["custom 3 3 1", "flag 1 1", "open 1 1", "flag 1 1", "open 1 1",
            "flag 1 1", "open 1 1", "open 2 2", "open 3 3", "flag 3 3"]
    rc, out, _ = _run(["--seed", str(SEED_CENTER3)], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out.count("rejected: cell is flagged") == 1  # open on a flagged cell
    assert out.count("rejected: cell is open") == 1  # flag on an opened cell
    assert out.count("rejected: already open") == 1  # open an opened cell
    assert out.count("rejected: game over") == 2  # open/flag after the loss
    # frames: initial 9x9 + the five accepted commands; rejections print none
    assert _frame_count(out) == 6
    assert _last_frame(out, 6) == [  # the loss frame is printed by the losing command
        "mines 1/1  open 1/8  lost",
        "",
        "  123",
        "1 1##",
        "2 #*#",
        "3 ###",
    ]


# ---------- C3: new/difficulty/custom change the field size (rulers/counters)

def test_difficulty_and_custom_change_field_size_in_frames():
    rc, out, _ = _run(["--seed", "3"], "difficulty medium\ndifficulty expert\ncustom 6 6 4\n")
    assert rc == 0
    assert "mines 40/40  open 0/216  playing" in out  # medium 16x16/40 counter
    assert " 1 " + "#" * 16 in out and "16 " + "#" * 16 in out  # 16 rows of 16
    assert "   1234567890123456" in out  # medium tens+units rulers (width > 9)
    assert "mines 99/99  open 0/381  playing" in out  # expert 30x16/99 counter
    assert " 1 " + "#" * 30 in out and "16 " + "#" * 30 in out  # 16 rows of 30
    assert "   123456789012345678901234567890" in out  # expert 30-wide units ruler
    assert "mines 4/4  open 0/32  playing" in out  # custom 6x6/4 counter
    assert "1 " + "#" * 6 in out and "6 " + "#" * 6 in out  # 6 rows of 6


# ---------- C4: help prints the banner; blank lines ignored; no ANSI, no prompt

def test_help_prints_banner_and_blank_lines_are_ignored():
    rc, out, _ = _run(["--seed", "11"], "\n   \nhelp\n\n")
    assert rc == 0
    assert out.count(BANNER) == 2  # startup + help; the blank lines added nothing
    assert _frame_count(out) == 1  # help/blank lines produced no frames
    assert out.count("rejected") == 0


def test_no_ansi_and_no_prompt_strings():
    rc, out, _ = _run(["--seed", "11"], "foo\nopen 1 1\nflag 2 2\nhelp\nquit\n")
    assert rc == 0
    assert "\x1b" not in out
    assert not any(ln.startswith("> ") for ln in _lines(out))


# ---------- determinism: identical pipe runs are byte-identical

def test_two_identical_runs_are_byte_identical():
    a = _run(["--seed", "13"], "open 1 1\nflag 2 2\ndifficulty medium\nopen 3 3\n")
    b = _run(["--seed", "13"], "open 1 1\nflag 2 2\ndifficulty medium\nopen 3 3\n")
    assert a == b
    assert _frame_count(a[1]) >= 4  # a real multi-frame transcript, not an empty run


# ---------- C5: main is thin — the rules live in the engine, frames in the render

def test_cli_is_thin_and_delegates_rules_to_engine_and_render():
    tree = ast.parse(CLI_SRC.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert {"argparse", "sys"} <= imported
    # no RNG, no queues, no state type of its own: the engine owns the rules
    assert not imported & {"random", "collections", "dataclasses"}
    assert not any(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
    called = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert {"new_game", "open_cell", "toggle_flag"} <= called  # rules via the engine
    assert "render" in called  # frames via the renderer
