"""vt_screen self-tests: the judge must be falsifiable.

Part A — the Screen model against raw byte streams (no PTY): the model's
semantics are pinned directly.
Part B — the calibration matrix under a real PTY: a toy program per
invariant violation, each violating EXACTLY ONE invariant, and every toy
must be caught by exactly its own invariant (all other invariants pass);
the green toys (clean screens, with and without a prelude) must stay green.
A judge that catches everything, or catches the wrong thing, is useless —
this matrix is what makes a PASS mean something.

Part B FAILS (never skips) when no PTY is available: the boundary is the
deliverable; an unrun boundary check is not a pass. (PTY in the fresh-Job
Pod was confirmed by the probe 2026-10-17.)
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
import vt_screen as vt  # noqa: E402


def _screen(rows=24, cols=80):
    return vt.Screen(rows, cols)


def _frames(data, rows=24, cols=80):
    s = _screen(rows, cols)
    s.feed(data)
    return s


# ---------------------------------------------------------------------------
# Part A: the model, byte stream in — no PTY
# ---------------------------------------------------------------------------

def test_bare_lf_is_a_staircase():
    # Terminal semantics: LF moves down and KEEPS the column.
    s = _frames(b"AB\nCD\nEF")
    assert s.line_origins == [0, 2, 4]
    with pytest.raises(AssertionError):
        vt.assert_stable_line_origin(s)


def test_crlf_lines_are_stable():
    s = _frames(b"AB\r\nCD\r\nEF\r\n")
    assert s.line_origins == [0, 0, 0]
    vt.assert_stable_line_origin(s)  # must not raise


def test_stable_origin_is_not_column_zero():
    # The invariant is "same column", not "column 0": a consistently
    # non-zero origin is NOT a defect. (A leading space is a character, so
    # byte-level origin is the first character written — the equality
    # semantics of the invariant are pinned directly here.)
    s = _screen()
    s.line_origins = [3, 3, 3]
    vt.assert_stable_line_origin(s)  # must not raise
    s2 = _screen()
    s2.line_origins = [3, 0]
    with pytest.raises(AssertionError):
        vt.assert_stable_line_origin(s2)


def test_wrap_is_counted():
    s = _frames(b"x" * 12, cols=10)
    assert s.wraps == 1
    with pytest.raises(AssertionError):
        vt.assert_no_wrap(s)


def test_scroll_is_counted():
    s = _frames(b"a\r\n" * 5, rows=3)
    # rows=3: the 3rd, 4th and 5th LF each push past the bottom.
    assert s.scrolls == 3
    with pytest.raises(AssertionError):
        vt.assert_no_scroll(s)


def test_sgr_sequences_take_no_columns():
    s = _frames(b"\x1b[38;2;10;200;30m\xe2\x96\x80\x1b[0m\r\nnext")
    assert s.line_origins == [0, 0]
    assert s.col == 4  # "next" — the half-block counted as exactly 1 column


def test_cursor_visibility_is_tracked():
    s = _frames(b"\x1b[?25lhidden\r\n")
    assert s.cursor_visible is False
    with pytest.raises(AssertionError):
        vt.assert_cursor_restored(s)
    s2 = _frames(b"\x1b[?25lhidden\r\n\x1b[?25hshown\r\n")
    assert s2.cursor_visible is True
    vt.assert_cursor_restored(s2)  # must not raise


def test_unmodelled_csi_is_skipped_without_geometry():
    # ESC[5d (CPI) is deliberately unmodelled: the judge must consume the
    # whole sequence and leave geometry, origins and the cursor untouched.
    # SGR and ED ARE modelled and are calibrated by their own tests above;
    # this test is about sequences _csi skips, nothing else.
    s = _frames(b"\x1b[5dab\r\n")
    assert s.line_origins == [0]
    assert s.render()[0].startswith("ab")


def test_home_redraw_does_not_scroll():
    # CUP modelled per the CC-281 incident: a program that homes and redraws
    # overwrites the same rows — no scroll, stable origins; line_origins
    # records draw events (each frame's lines), not the final screen state.
    s = _frames(b"ab\r\ncd\r\n\x1b[Hef\r\ngh\r\n")
    assert s.scrolls == 0
    assert s.line_origins == [0, 0, 0, 0]
    vt.assert_no_scroll(s)
    vt.assert_stable_line_origin(s)


def test_cursor_up_moves_the_row():
    # CUU: up 2 rows from row 2 -> row 0, then draw there.
    s = _frames(b"a\r\nb\r\n\x1b[2Ac\r\n")
    assert s.scrolls == 0
    assert s.line_origins == [0, 0, 0]
    vt.assert_no_scroll(s)


def test_grid_keeps_the_final_screen():
    # The judge now keeps what a user would SEE, not only draw events.
    s = _frames(b"ab\r\ncd", rows=3, cols=10)
    assert s.render() == ["ab        ", "cd        ", "          "]


def test_ed_2j_clears_grid_and_keeps_cursor():
    s = vt.Screen(3, 10, prelude=b"prompt\r\n")  # cursor lands at (1,0)
    s.feed(b"\x1b[2Jz")
    assert s.render() == ["          ", "z         ", "          "]
    assert (s.row, s.col) == (1, 1)  # ED does not home (that is CUP's job)


def test_ed_0j_clears_cursor_to_end_of_screen():
    s = _frames(b"aaaaaaaaa\x1b[4D\x1b[0J", rows=3, cols=9)
    assert s.render()[0] == "aaaaa    "


def test_ed_1j_clears_start_of_screen_to_cursor():
    s = _frames(b"line0xxxx\r\nline1yyyy\x1b[1J", rows=4, cols=9)
    assert s.render() == ["         ", "         ", "         ", "         "]


def test_ed_3j_is_a_full_clear_like_2j():
    s = _frames(b"line0\r\nline1\r\n\x1b[3J", rows=4, cols=9)
    assert all(row == "         " for row in s.render())


def test_el_forms_clear_the_line_only():
    # 0K: cursor -> end; 1K: start -> cursor; 2K: whole line. Rows untouched.
    s = _frames(b"0123456789\x1b[5D\x1b[0K", rows=2, cols=10)
    assert s.render()[0] == "01234     "
    assert s.render()[1] == "          "
    s2 = _frames(b"0123456789\x1b[5D\x1b[1K", rows=2, cols=10)
    assert s2.render()[0] == "      6789"
    s3 = _frames(b"0123456789\x1b[2K", rows=2, cols=10)
    assert s3.render()[0] == "          "


def test_cup_absolute_forms_and_clamp():
    s = _screen(rows=5, cols=10)
    s.feed(b"\x1b[3;5Hz")
    assert s.render()[2] == "    z     "
    s.feed(b"\x1b[1;1Hhome")
    assert s.render()[0].startswith("home")
    s.feed(b"\x1b[99;99Hq")  # clamps into the window, never scrolls
    assert s.render()[4][9] == "q"
    assert s.scrolls == 0


def test_cud_cuf_cub_move_and_clamp():
    s = _screen(rows=5, cols=10)
    s.feed(b"\x1b[2B\x1b[3Cz")
    assert s.render()[2] == "   z      "
    s.feed(b"\x1b[1A\x1b[1Dy")  # col follows the previous put (was 4) -> 3
    assert s.render()[1] == "   y      "
    s.feed(b"\x1b[9B\x1b[9Cx")  # clamped
    assert s.render()[4][9] == "x"
    assert s.scrolls == 0  # cursor movement never scrolls (LF/wrap do)


def test_prelude_initialises_state_without_counting():
    # A shell prompt mid-screen: cursor moves, grid is painted, but the
    # program's counters (line_origins/wraps/scrolls) never see it.
    prelude = b"".join(b"prompt-line-%d\r\n" % i for i in range(1, 11))
    s = vt.Screen(24, 80, prelude=prelude)
    assert s.row == 10 and s.col == 0
    assert s.line_origins == []
    assert s.wraps == 0 and s.scrolls == 0
    assert "".join(s.grid[0]).startswith("prompt-line-1")
    assert s.render()[9].startswith("prompt-line-10")


def test_prelude_overflow_paints_but_never_counts():
    # Prelude long enough to wrap and scroll: the grid stays terminal-correct
    # while every program counter stays zero.
    prelude = b"".join(b"L%d\r\n" % i for i in range(30))
    s = vt.Screen(5, 80, prelude=prelude)
    assert s.scrolls == 0 and s.wraps == 0 and s.line_origins == []
    # the trailing LF of the last prelude line leaves one blank line at the
    # bottom — exactly what a terminal shows; the grid still holds the tail.
    assert s.render()[3].startswith("L29")
    assert s.render()[4] == " " * 80


def _res(rows, cols, prelude, raw):
    s = vt.Screen(rows, cols, prelude=prelude)
    s.feed(raw)
    return vt.Result(raw=raw, rc=0, screen=s, termios_restored=True,
                     timed_out=False, prelude=prelude)


def test_last_frame_start_finds_the_final_boundary_group():
    # Only consecutive home/erase tokens group; text splits groups; the LAST
    # group is the frame start.
    assert vt._last_frame_start(b"abc\x1b[Hdef\x1b[Hghi") == 9
    assert vt._last_frame_start(b"\x1b[2J\x1b[Hx") == 0  # one group
    assert vt._last_frame_start(b"a\x1b[1;1Hb") == 1
    assert vt._last_frame_start(b"\x1b[3;3Hnot a boundary") is None
    assert vt._last_frame_start(b"no boundaries at all") is None


def test_no_residue_flags_a_frame_left_behind():
    r = _res(24, 20, b"prompt\r\n", b"stale\r\n\x1b[Hnew\r\n")
    with pytest.raises(AssertionError) as exc:
        vt.assert_no_residue(r)
    assert "rows [1]" in str(exc.value)


def test_no_residue_passes_when_the_last_frame_covers_everything():
    r = _res(24, 20, b"prompt\r\n",
             b"\x1b[Hnew\r\n" + b"\x1b[Hnew2\r\n")
    vt.assert_no_residue(r)  # must not raise


def test_no_residue_not_applicable_without_a_boundary():
    # An accumulating stream: no frame boundary -> no_residue does not apply
    # (accumulation is no_scroll's job, not this one's).
    r = _res(24, 20, b"", b"accumulated\r\ncontent\r\n")
    vt.assert_no_residue(r)  # must not raise


# ---------------------------------------------------------------------------
# Part B: calibration matrix under a real PTY
# ---------------------------------------------------------------------------

_PY = sys.executable

# Each toy violates exactly one invariant. bare_lf/mixed disable OPOST the
# way a raw-mode CLI does, then RESTORE it — so termios_restored passes and
# only the alignment defect remains. no_residue toys: the terminal starts
# from a non-trivial state (prelude) and/or frames differ in length — the
# defect is what the last frame leaves behind, visible only on the final
# screen.
PRELUDE10 = b"".join(b"prompt-line-%d\r\n" % i for i in range(1, 11))

TOYS = {
    "good": ('import sys; sys.stdout.write("ab\\r\\ncd\\r\\nef\\r\\n")',
             None, b""),
    # RED exit: a nonzero rc. assert_exit's timeout branch is calibrated by
    # test_timeout_is_a_failure_not_a_pass; its rc!=0 branch needs a toy.
    "bad_exit": ('import sys\nsys.stdout.write("ok\\r\\n")\nsys.exit(3)',
                 "exit", b""),
    "bare_lf": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a); b[1]&=~termios.OPOST\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ab\\ncd\\nef\\n")\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,a)\n',
        "stable_line_origin", b""),
    "mixed": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a); b[1]&=~termios.OPOST\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ab\\ncd\\r\\nef\\r\\n")\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,a)\n',
        "stable_line_origin", b""),
    # streams past the bottom without homing: caught by no_scroll only
    "no_home": ('import sys; sys.stdout.write("x\\r\\n" * 40)',
                "no_scroll", b""),
    "no_restore": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a)\n'
        'b[3]&=~(termios.ECHO|termios.ICANON)\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ok\\r\\n")\n',
        "termios_restored", b""),
    # shallow copy shares the cc list: the "restore" writes back the already
    # mutated cc, so VMIN survives.
    # A flags-only comparison would pass this toy; the full-attrs comparison
    # must catch it (CC-280 review, 2026-10-17).
    "cc_alias": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a)\n'
        'b[6][termios.VMIN]=0\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ok\\r\\n")\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,a)\n',
        "termios_restored", b""),
    "wide": ('import sys; sys.stdout.write("w" * 100 + "\\r\\n")',
             "no_wrap", b""),
    "cursor_hidden": ('import sys; sys.stdout.write("\\x1b[?25lok\\r\\n")',
                      "cursor_restored", b""),
    # homes and redraws the same rows: the judge must read this as a CLEAN
    # screen (no_scroll GREEN-on-good) — the shape of the CC-281 fix.
    "home_ok": ('import sys\n'
                'for i in range(3):\n'
                '    sys.stdout.write("\\x1b[H" + "x\\r\\n" * 10)\n',
                None, b""),
    # RED no_residue: homes only after the first frame. The terminal already
    # showed a prompt ending mid-screen, so frame 1 is drawn below it and
    # the later frames — homed to (0,0) — never cover it. The stale first
    # frame survives on the final screen; every other invariant is clean.
    "home_after_first": (
        'import sys\n'
        'sys.stdout.write("first-frame-line\\r\\n" * 3)\n'
        'for i in range(2, 5):\n'
        '    sys.stdout.write("\\x1b[H" + ("frame%d-line\\r\\n" % i) * 3)\n',
        "no_residue", PRELUDE10),
    # RED no_residue: later frames are SHORTER and never erase to end-of-
    # line, so ghost cells of the long first frame survive on the final
    # screen (a shorter replay from the same start would leave them blank).
    "ghost_tail": (
        'import sys\n'
        'sys.stdout.write("aaaaaaaaaa\\r\\n" * 3)\n'
        'sys.stdout.write("\\x1b[H" + "b\\r\\n" * 3)\n',
        "no_residue", b""),
    # GREEN: every frame clears the whole screen first (erase + home), with
    # a prelude in the terminal's initial state — the final screen equals
    # the last frame alone, including the cleared prelude.
    "clear_each": (
        'import sys\n'
        'for i in range(3):\n'
        '    sys.stdout.write("\\x1b[2J\\x1b[H" + ("frame%d\\r\\n" % i) * 5)\n',
        None, PRELUDE10),
    # GREEN: shorter lines ARE erased to end-of-line — no ghosts.
    "ghost_el": (
        'import sys\n'
        'sys.stdout.write("aaaaaaaaaa\\r\\n" * 3)\n'
        'sys.stdout.write("\\x1b[H" + "b\\x1b[K\\r\\n" * 3)\n',
        None, b""),
}


def _run(code, timeout=10.0, prelude=b""):
    return vt.run_pty([_PY, "-c", code], timeout=timeout, prelude=prelude)


@pytest.mark.parametrize("name", sorted(TOYS))
def test_mutant_matrix_each_toy_is_caught_by_exactly_its_invariant(name):
    code, expected_failure, prelude = TOYS[name]
    result = _run(code, prelude=prelude)
    outcomes = vt.check_all(result)
    failed = sorted(k for k, v in outcomes.items() if v is not None)
    expected = [] if expected_failure is None else [expected_failure]
    assert failed == expected, (
        "toy %s: expected exactly %r to fail, got %r" % (name, expected, failed))


def test_child_sees_the_window_size():
    # The judge sets the window on the master; the program sees it via
    # os.get_terminal_size (the runsc-safe read path).
    result = _run('import os,sys\n'
                  'sz=os.get_terminal_size()\n'
                  'sys.stdout.write("%dx%d\\r\\n" % (sz.columns, sz.lines))\n')
    assert b"80x24" in result.raw
    vt.check_all(result)  # sanity: the toy itself is clean
    outcomes = vt.check_all(result)
    assert all(v is None for v in outcomes.values())


def test_feed_reaches_the_program():
    # The judge writes the user's keystrokes to the master; the program reads
    # them from its stdin (the slave). The tty echoes them back (ECHO is on
    # when the feed is written — the child has not had time to change
    # attributes), so the raw stream carries the echo on its own line; the
    # contract is that the program RECEIVES the feed and the screen stays
    # clean (the echo line and the reply share origin 0 — stable).
    result = vt.run_pty(
        [_PY, "-c",
         'import sys\n'
         'ch = sys.stdin.buffer.read(1)\n'
         'sys.stdout.write("got:" + ch.decode() + "\\r\\n")'],
        feed=b"z\n", timeout=10.0)
    assert b"got:z" in result.raw
    outcomes = vt.check_all(result)
    assert all(v is None for v in outcomes.values()), outcomes


def test_delayed_feed_arrives_after_the_delay():
    # A (delay, chunk) schedule simulates a user who types LATER: the toy
    # prints "start", then waits up to 3 s for one byte. The chunk is due at
    # 0.5 s — the program must receive it and reply. The order in the raw
    # stream proves the delay was honoured (start before got).
    result = vt.run_pty(
        [_PY, "-c",
         'import sys,select\n'
         'sys.stdout.write("start\\r\\n"); sys.stdout.flush()\n'
         'sel = select.select([sys.stdin.buffer], [], [], 3.0)\n'
         'ch = sys.stdin.buffer.read(1) if sel[0] else b"-"\n'
         'sys.stdout.write("got:" + ch.decode() + "\\r\\n")'],
        feed=[(0.5, b"z\n")], timeout=10.0)  # \n: canonical mode delivers a line
    assert b"start" in result.raw and b"got:z" in result.raw
    assert result.raw.index(b"start") < result.raw.index(b"got:z")
    vt.assert_exit(result)


def test_feed_due_after_the_child_exits_is_harmless():
    # The child is gone before the chunk is due: the write to the master
    # fails (EIO) and must not crash the judge or change the verdict.
    result = vt.run_pty(
        [_PY, "-c", 'import sys; sys.stdout.write("done\\r\\n")'],
        feed=[(5.0, b"x")], timeout=10.0)
    assert b"done" in result.raw and b"x" not in result.raw
    vt.assert_exit(result)


def test_timeout_is_a_failure_not_a_pass():
    result = _run('import time; time.sleep(30)', timeout=1.0)
    assert result.timed_out is True
    with pytest.raises(AssertionError):
        vt.assert_exit(result)


def test_run_is_deterministic():
    code = TOYS["good"][0]
    r1 = _run(code)
    r2 = _run(code)
    assert r1.raw == r2.raw
    assert r1.screen.line_origins == r2.screen.line_origins
