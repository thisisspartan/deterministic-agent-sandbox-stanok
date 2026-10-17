"""Terminal-contract acceptance (G4, host-authored): tetris_cli under a real
PTY. Accepts CC-280 (staircase/termios) and CC-281 (in-place redraw).

Consumer-view contract: the interactive CLI on a real terminal must draw a
screen a terminal user would read as correct — checked as SCREEN-LEVEL
INVARIANTS through the trusted judge (tests/fixtures/vt_screen.py), not as
byte sequences. The judge's own calibration (tests/vt_screen_test.py) is
what makes a PASS here mean something.

Contract choice (SPEC-TETRIS-TERMINAL): stable_line_origin, no_scroll,
no_wrap, termios_restored, cursor_restored, exit. no_scroll IS asserted
(operator decision 2026-10-17, CC-281): the interactive game must redraw
the frame in place, not stream frames down the screen. The contract picks
which invariants apply; the judge never imposes all.

Red history: (CC-280) the CLI turned OPOST off in raw mode and emitted
bare LF -> staircase -> stable_line_origin failed; fixed in CC-280.
(CC-281) the CLI streams full frames with bare LF and never homes, so the
screen scrolls -> no_scroll fails until the CLI redraws in place.
The 12 pipe tests cannot see any of this: a pipe has no terminal semantics.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
import vt_screen as vt  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_interactive_cli_under_a_real_terminal_draws_a_stable_screen():
    # A small board keeps ONE frame inside the 24-row window; the defect is
    # independent of board size. "q" is fed DELAYED (1.5 s > two frame
    # periods at the default 2 fps): the user types after the game has drawn
    # several frames — the only way no_scroll can be non-vacuous. A
    # single-shot feed is consumed in the first poll and the CLI draws one
    # frame (measured 2026-10-17: no_scroll passed vacuously with feed=b"q").
    result = vt.run_pty(
        [sys.executable, "-m", "src.tetris_cli",
         "--seed", "1", "--width", "6", "--height", "10"],
        feed=[(2.0, b"q\n")], rows=24, cols=80, timeout=20.0, cwd=_REPO,
    )
    vt.assert_exit(result)
    # Non-vacuity: a real tetris frame must have reached the terminal.
    assert b"\xe2\x96\x80" in result.raw, "no half-block frame reached the terminal"
    assert result.screen.line_origins, "the CLI drew no frame at all"
    # Non-vacuity of no_scroll: at least TWO full frames must have reached
    # the terminal (a frame is height+2 lines; --height 10 -> 12). True for
    # a streaming CLI and for an in-place redraw (the judge records draw
    # events per frame); false only if the CLI drew a single frame.
    assert len(result.screen.line_origins) >= 2 * (10 + 2), (
        "fewer than two frames reached the terminal (no_scroll would be "
        "vacuous)")
    # The contract invariants (see module docstring for the choice).
    vt.assert_stable_line_origin(result.screen)
    vt.assert_no_scroll(result.screen)
    vt.assert_no_wrap(result.screen)
    vt.assert_termios_restored(result)
    vt.assert_cursor_restored(result.screen)
