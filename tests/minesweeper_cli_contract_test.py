"""Calibrated contract oracle for src/minesweeper_cli.py (SPEC-MINESWEEPER-CONSOLE C1..C5).

Independence policy: the real boundary is observed via real subprocess pipe
(sys.executable -m src.minesweeper_cli, cwd = tree root). Expected bytes are
re-derived here by an independent CLI model written from the SPEC text,
replaying through the tree's own engine+render (both already pinned by their
own oracles) — never captured from CLI output. Mutants CM1..CM6
(see specs/STATUS.md): GREEN on the reference CLI, RED on each mutant.
Host-authored; the machine must not edit.
"""
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
MOD = "src.minesweeper_cli"

# pinned verbatim (provenance: SPEC C2 banner, quoted)
BANNER = ("commands: open X Y | flag X Y | new | difficulty beginner|medium|expert"
          " | custom W H MINES | help | quit")
# pinned presets (provenance: SPEC C3)
PRESETS = {"beginner": (9, 9, 10), "medium": (16, 16, 40), "expert": (30, 16, 99)}


# ---------- independent reference helpers (placement search only; frames are
# produced by the tree's own render, whose format is pinned by R1's oracle)

def ref_mines(seed, w, h, n):
    return frozenset(random.Random(seed).sample(
        [(x, y) for y in range(1, h + 1) for x in range(1, w + 1)], n))


def _center3_seed():
    return next(sd for sd in range(1, 10000)
                if ref_mines(sd, 3, 3, 1) == {(2, 2)})


CENTER3_SEED = _center3_seed()  # 3x3/1 with mine at center: no zero cells


def _ints(tokens):
    try:
        return [int(t) for t in tokens]
    except ValueError:
        return None


def _run(args, stdin_text, timeout=20):
    try:
        p = subprocess.run([sys.executable, "-m", MOD, *args],
                          input=stdin_text.encode(), capture_output=True,
                          timeout=timeout, cwd=str(ROOT))
    except subprocess.TimeoutExpired:
        pytest.fail("CLI did not terminate in %ss: %r" % (timeout, args))
    return p.returncode, p.stdout.decode(), p.stderr.decode()


# ---------- independent expected-output model of the CLI per SPEC C2..C4.
# Seed semantics pinned from SPEC C3 text ("seed = seed + games_played,
# games_played++" — value used, then incremented; initial frame uses games_played=0).

def _replay(seed0, cmds):
    out = [BANNER]
    gp = 0
    cfg = (9, 9, 10)

    def game(w, h, n):
        return eng.new_game(seed0 + gp, w, h, n)

    st = game(*cfg)
    out.extend(rnd.render(st))
    for raw in cmds:
        toks = raw.split()
        if not toks:
            continue
        cmd = toks[0]
        if cmd == "quit":
            break
        if cmd == "help":
            out.append(BANNER)
        elif cmd == "new":
            st = game(*cfg)
            gp += 1
            out.extend(rnd.render(st))
        elif cmd == "difficulty":
            if len(toks) != 2:
                out.append("rejected: bad arguments")
            elif toks[1] not in PRESETS:
                out.append("rejected: unknown difficulty")
            else:
                cfg = PRESETS[toks[1]]
                st = game(*cfg)
                gp += 1
                out.extend(rnd.render(st))
        elif cmd == "custom":
            vals = _ints(toks[1:]) if len(toks) == 4 else None
            if vals is None:
                out.append("rejected: bad arguments")
            else:
                try:
                    ns = game(*vals)
                except ValueError:
                    out.append("rejected: invalid size")
                else:
                    cfg = vals
                    st = ns
                    gp += 1
                    out.extend(rnd.render(st))
        elif cmd in ("open", "flag"):
            xy = _ints(toks[1:]) if len(toks) == 3 else None
            if xy is None:
                out.append("rejected: bad arguments")
            elif st.status != "playing":
                out.append("rejected: game over")
            elif not (1 <= xy[0] <= st.width and 1 <= xy[1] <= st.height):
                out.append("rejected: out of range")
            elif cmd == "open":
                if (xy[0], xy[1]) in st.opened:
                    out.append("rejected: already open")
                elif (xy[0], xy[1]) in st.flagged:
                    out.append("rejected: cell is flagged")
                else:
                    st = eng.open_cell(st, *xy)
                    out.extend(rnd.render(st))
            elif (xy[0], xy[1]) in st.opened:
                out.append("rejected: cell is open")
            else:
                st = eng.toggle_flag(st, *xy)
                out.extend(rnd.render(st))
        else:
            out.append("rejected: unknown command")
    return "\n".join(out) + "\n"


# ---------- C1: usage / exit codes on the real boundary

@pytest.mark.parametrize("args", [
    ["--nope"], ["--seed"], ["--seed", "abc"], ["extra"], ["--seed", "1", "extra"],
])
def test_bad_invocation_usage_rc2(args):
    rc, out, err = _run(args, "")
    assert rc == 2
    assert "usage" in err.lower(), err
    assert out == ""


def test_seed_flag_is_honored_default_is_zero():
    rc0, out0, _ = _run([], "")
    assert rc0 == 0
    assert out0 == _replay(0, [])
    rc42, out42, _ = _run(["--seed", "42"], "")
    assert rc42 == 0
    assert out42 == _replay(42, [])
    # the seed is observable only through play: closed boards are seed-invariant,
    # opening a cell must expose the layout of the --seed honored by the CLI
    _, o0, _ = _run([], "open 1 1\n")
    _, o42, _ = _run(["--seed", "42"], "open 1 1\n")
    assert o0 == _replay(0, ["open 1 1"])
    assert o42 == _replay(42, ["open 1 1"])
    assert o0 != o42


# ---------- C2: banner, initial frame, quit, EOF

def test_banner_is_first_line_and_initial_frame_follows():
    _, out, _ = _run(["--seed", "7"], "")
    lines = out.split("\n")
    assert lines[0] == BANNER
    assert out == _replay(7, [])


def test_quit_terminates_immediately_rc0():
    rc, out, _ = _run(["--seed", "7"], "quit\nopen 1 1\n")
    assert rc == 0
    assert out == _replay(7, ["quit"])


def test_eof_terminates_rc0():
    rc, out, _ = _run(["--seed", "7"], "")
    assert rc == 0
    assert out == _replay(7, [])


# ---------- C3/C4: full win and loss transcripts, seeded, byte-exact

def test_win_transcript_custom_3x3_center_mine():
    cmds = ["custom 3 3 1"]
    for c in [(1, 1), (2, 1), (3, 1), (1, 2), (3, 2), (1, 3), (2, 3), (3, 3)]:
        cmds.append("open %d %d" % c)
    rc, out, _ = _run(["--seed", str(CENTER3_SEED)], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(CENTER3_SEED, cmds)
    final = out.split("\n")[-2]  # last board row of the final frame
    assert out.count("*") == 1 and final == "3 111"  # won frame shows the mine


def test_loss_transcript_final_board_and_game_over_rejections():
    cmds = ["custom 3 3 1", "open 1 1", "open 2 2", "open 3 3", "flag 1 1"]
    rc, out, _ = _run(["--seed", str(CENTER3_SEED)], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(CENTER3_SEED, cmds)
    assert out.count("rejected: game over") == 2  # open 3 3 and flag 1 1 after loss
    assert out.count("*") == 1  # the mine revealed exactly once on the lost board


# ---------- C3: every pinned rejection string; field never mutated

def test_rejection_strings_verbatim_field_untouched():
    cmds = ["foo", "open a b", "open 1", "open 0 5", "open 5 99",
            "flag 0 0", "flag 10 1", "difficulty", "difficulty nope",
            "custom 1 1", "custom a b c", "custom 0 0 0", "custom 100 1 1",
            "custom 3 3 9", "custom 1 33 1"]
    rc, out, _ = _run([], "\n".join(cmds) + "\n")
    assert rc == 0
    # expected frames: only the initial one; every command yields exactly its line
    init = rnd.render(eng.new_game(0, 9, 9, 10))
    expect = "\n".join([BANNER] + list(init) + [
        "rejected: unknown command", "rejected: bad arguments",
        "rejected: bad arguments", "rejected: out of range",
        "rejected: out of range", "rejected: out of range",
        "rejected: out of range", "rejected: bad arguments",
        "rejected: unknown difficulty", "rejected: bad arguments",
        "rejected: bad arguments", "rejected: invalid size",
        "rejected: invalid size", "rejected: invalid size",
        "rejected: invalid size",
    ]) + "\n"
    assert out == expect
    # model agrees with the independent replay as well
    assert out == _replay(0, cmds)


def test_flag_open_interactions_on_pinned_3x3():
    cmds = ["custom 3 3 1", "flag 1 1", "open 1 1", "flag 1 1", "open 1 1",
            "flag 1 1"]
    rc, out, _ = _run(["--seed", str(CENTER3_SEED)], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(CENTER3_SEED, cmds)
    assert "rejected: cell is flagged" in out
    assert "rejected: cell is open" in out


# ---------- C3: new/difficulty/custom seed semantics and frame sizes

def test_new_uses_games_played_seed_and_replays_same_difficulty():
    # open after the news exposes the CURRENT game's layout -> the seed the
    # second new actually used is observable in the opened frame
    cmds = ["new", "new", "open 1 1"]
    rc, out, _ = _run(["--seed", "3"], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(3, cmds)
    assert out.count(BANNER) == 1
    # four 9x9 rulers: initial + two new games (seeds 3+0, 3+1 pinned by model)
    # + the opened frame
    assert out.count("  123456789") == 4


def test_difficulty_and_custom_change_field_size_in_frames():
    # final open exposes the custom game's layout: pins which seed the custom
    # used (seed + games_played at that point, per the model contract)
    cmds = ["difficulty medium", "difficulty nope", "difficulty expert",
            "custom 6 6 4", "open 1 1"]
    rc, out, _ = _run(["--seed", "3"], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(3, cmds)
    assert "mines 40/40" in out  # medium frame counter line
    assert "mines 99/99" in out  # expert frame
    assert "mines 4/4" in out    # custom 6x6/4 frame


# ---------- C4: help prints banner; blank lines ignored; no ANSI, no prompt

def test_help_and_blank_lines():
    cmds = ["", "   ", "help", ""]
    rc, out, _ = _run(["--seed", "11"], "\n".join(cmds) + "\n")
    assert rc == 0
    assert out == _replay(11, cmds)
    assert out.count(BANNER) == 2  # startup + help


def test_no_ansi_and_no_prompt_strings():
    cmds = ["foo", "open 1 1", "flag 2 2", "help", "custom 4 4 3", "quit"]
    rc, out, _ = _run(["--seed", "11"], "\n".join(cmds) + "\n")
    assert rc == 0
    assert "\x1b" not in out
    assert not any(ln.startswith("> ") for ln in out.split("\n"))
    assert out == _replay(11, cmds)


# ---------- determinism: two identical pipe runs are byte-identical

def test_two_identical_runs_are_byte_identical():
    a = _run(["--seed", "13"], "open 1 1\nflag 2 2\n")
    b = _run(["--seed", "13"], "open 1 1\nflag 2 2\n")
    assert a == b
