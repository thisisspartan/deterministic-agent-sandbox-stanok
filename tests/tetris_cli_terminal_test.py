"""CC-280 acceptance (G4, host-authored): tetris_cli under a real PTY.

Consumer-view contract: the interactive CLI on a real terminal must draw a
screen a terminal user would read as correct — checked as SCREEN-LEVEL
INVARIANTS through the trusted judge (tests/fixtures/vt_screen.py), not as
byte sequences. The judge's own calibration (tests/vt_screen_test.py) is
what makes a PASS here mean something.

Contract choice (SPEC-TETRIS-TERMINAL): the invariants that apply to a
streaming full-frame CLI are stable_line_origin, no_wrap, termios_restored,
cursor_restored, exit. no_scroll is deliberately NOT asserted: a streaming
CLI may scroll — the contract picks which invariants apply, the judge never
imposes all.

Red before the fix: the CLI turns OPOST off in raw mode and emits bare LF,
so under a real TTY the frames form a staircase -> stable_line_origin fails.
The 12 pipe tests cannot see this: a pipe has no terminal semantics.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
import vt_screen as vt  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_interactive_cli_under_a_real_terminal_draws_a_stable_screen():
    # A small board keeps the frame inside the 24-row window; the defect is
    # independent of board size. feed "q" ends the interactive loop cleanly.
    result = vt.run_pty(
        [sys.executable, "-m", "src.tetris_cli",
         "--seed", "1", "--width", "6", "--height", "10"],
        feed=b"q\n", rows=24, cols=80, timeout=20.0, cwd=_REPO,
    )
    vt.assert_exit(result)
    # Non-vacuity: a real tetris frame must have reached the terminal.
    assert b"\xe2\x96\x80" in result.raw, "no half-block frame reached the terminal"
    assert result.screen.line_origins, "the CLI drew no frame at all"
    # The contract invariants (see module docstring for the choice).
    vt.assert_stable_line_origin(result.screen)
    vt.assert_no_wrap(result.screen)
    vt.assert_termios_restored(result)
    vt.assert_cursor_restored(result.screen)
