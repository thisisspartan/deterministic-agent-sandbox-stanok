"""tetris_terminal_test — the boundary acceptance for CC-292 (src/tetris_cli.py).

Host-authored trusted check (the agent cannot author its own boundary accept;
policy CC-286). Runs the CLI under a real PTY with a modelled initial state
(10-line shell prompt) and asserts the SPEC-TETRIS3 A3 invariants through the
judge fixture (tests/fixtures/vt_screen.py). Do not edit or delete from a
ticket: this file is the wave's acceptance boundary.

Calibration record (host, 2026-10-18, before first use):
  - RED on the live tree without src/tetris_cli.py: exit rc=1 (module
    missing) — recorded before the ticket launch.
  - RED on the tail-defect mutant (interactive CLI that homes only AFTER
    the first frame): no_residue FAILS — "residue beyond the last frame:
    rows [10, 11, 12, 13, 14, 15, 16] (window 24x80)" — the exact defect
    pinned by SPEC-TETRIS3 R3 ("ESC[H before EVERY frame including the
    first, under the isatty gate").
  - GREEN on the /tmp/tetris-ref reference (engine+render from the tree +
    reference CLI with first frame homed): all invariants pass.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
import vt_screen as vt  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The state a terminal is actually in when a program starts: the shell prompt
# filled ten rows. The judge models it as the initial Screen; the program
# never sees it (it is not written to the PTY).
_WIDTH = 6
_HEIGHT = 10
_FRAME_LINES = _HEIGHT // 2 + 2  # half-block frame: 7 terminal lines
_PRELUDE = b"".join(b"prompt-line-%d\r\n" % i for i in range(1, 11))


def test_tetris_cli_leaves_clean_terminal_state():
    result = vt.run_pty(
        [sys.executable, "-m", "src.tetris_cli",
         "--seed", "1", "--width", str(_WIDTH), "--height", str(_HEIGHT)],
        feed=[(2.0, b"q\n")], rows=24, cols=80, timeout=20.0, cwd=_REPO,
        prelude=_PRELUDE,
    )
    vt.assert_exit(result)

    # Non-vacuity: a real frame must have reached the terminal, and at least
    # TWO full frames (each = _HEIGHT//2+2 half-block lines, every drawn
    # line counts as one line-origin) so the screen-level invariants are
    # not vacuous.
    assert b"\xe2\x96\x80" in result.raw, "no half-block frame reached the terminal"
    assert result.screen.line_origins, "the CLI drew no frame at all"
    assert len(result.screen.line_origins) >= 2 * _FRAME_LINES, (
        "fewer than two frames reached the terminal (screen-level invariants "
        "would be vacuous)")
    # Non-vacuity of no_residue: applicable only when the program marks its
    # frame starts (home before every frame). Without a boundary it is NOT
    # a pass.
    assert vt._last_frame_start(result.raw) is not None, (
        "the program never marks a frame start — no_residue is inapplicable")

    # The contract invariants (SPEC-TETRIS3 A3): the full judge set.
    vt.assert_stable_line_origin(result.screen)
    vt.assert_no_scroll(result.screen)
    vt.assert_no_wrap(result.screen)
    vt.assert_no_residue(result)
    vt.assert_termios_restored(result)
    vt.assert_cursor_restored(result.screen)
