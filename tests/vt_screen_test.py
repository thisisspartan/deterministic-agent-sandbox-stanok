"""vt_screen self-tests: the judge must be falsifiable.

Part A — the Screen model against raw byte streams (no PTY): the model's
semantics are pinned directly.
Part B — the calibration matrix under a real PTY: seven toy programs, each
violating EXACTLY ONE invariant, and every toy must be caught by exactly its
own invariant (all other invariants pass). A judge that catches everything,
or catches the wrong thing, is useless — this matrix is what makes a PASS
mean something.

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
    s = _frames(b"\x1b[2Jab\r\n")
    assert s.line_origins == [0]


# ---------------------------------------------------------------------------
# Part B: calibration matrix under a real PTY
# ---------------------------------------------------------------------------

_PY = sys.executable

# Each toy violates exactly one invariant. bare_lf/mixed disable OPOST the
# way a raw-mode CLI does, then RESTORE it — so termios_restored passes and
# only the alignment defect remains (exactly the tetris_cli defect shape).
TOYS = {
    "good": ('import sys; sys.stdout.write("ab\\r\\ncd\\r\\nef\\r\\n")',
             None),
    "bare_lf": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a); b[1]&=~termios.OPOST\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ab\\ncd\\nef\\n")\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,a)\n',
        "stable_line_origin"),
    "mixed": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a); b[1]&=~termios.OPOST\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ab\\ncd\\r\\nef\\r\\n")\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,a)\n',
        "stable_line_origin"),
    # streams past the bottom without homing: caught by no_scroll only
    "no_home": ('import sys; sys.stdout.write("x\\r\\n" * 40)',
                "no_scroll"),
    "no_restore": (
        'import sys,termios\n'
        'a=termios.tcgetattr(1); b=list(a)\n'
        'b[3]&=~(termios.ECHO|termios.ICANON)\n'
        'termios.tcsetattr(1,termios.TCSADRAIN,b)\n'
        'sys.stdout.write("ok\\r\\n")\n',
        "termios_restored"),
    "wide": ('import sys; sys.stdout.write("w" * 100 + "\\r\\n")',
             "no_wrap"),
    "cursor_hidden": ('import sys; sys.stdout.write("\\x1b[?25lok\\r\\n")',
                      "cursor_restored"),
}


def _run(code, timeout=10.0):
    return vt.run_pty([_PY, "-c", code], timeout=timeout)


@pytest.mark.parametrize("name", sorted(TOYS))
def test_mutant_matrix_each_toy_is_caught_by_exactly_its_invariant(name):
    code, expected_failure = TOYS[name]
    result = _run(code)
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
