"""CC-289 boundary acceptance (host-side, pre-existing protected contract).

`python -m src.fire_cli` under a REAL terminal via the judge
(tests/fixtures/vt_screen.py). Two consumer-visible scenarios:

  1. bounded mode (--frames 4) under a real PTY behind a 10-line shell
     prompt (prelude): frames redraw in place, the program terminates by
     itself, exit leaves no residue — the tail-residue defect of the
     previous wave is exactly what this test is built to catch;
  2. interactive mode: a real user types `q` at t=2.0s -> clean exit rc 0.

Judge invariants: exit, stable_line_origin, no_scroll, no_wrap,
no_residue, termios_restored, cursor_restored — plus non-vacuity guards
(colour frames actually reached the terminal, at least two of them, and
the program marks frame starts: without a boundary no_residue is NOT a
pass — accumulation is no_scroll's job).

Calibration (2026-10-18, before first use, per the new acceptance policy):
  - live tree WITHOUT src/fire_cli.py: RED — both tests fail assert_exit
    (rc 1, "No module named src.fire_cli");
  - with the reference CLI (/tmp/fire-accept-ref, removed after calibration):
    GREEN.
Flame aesthetics are not tested; terminal invariants are.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "fixtures"))
import vt_screen as vt  # noqa: E402

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PY = sys.executable

# The state a terminal is really in when a program starts: ten rows of
# shell prompt. The judge models it as the initial Screen; the program
# never sees it (it is not written to the PTY).
_PRELUDE = b"".join(b"prompt-line-%d\r\n" % i for i in range(1, 11))

_ROWS, _COLS = 24, 80
_WIDTH, _HEIGHT = 20, 8


def _cli_args(seed):
    return [_PY, "-m", "src.fire_cli", "--seed", str(seed),
            "--width", str(_WIDTH), "--height", str(_HEIGHT)]


def _assert_terminal_contract(result):
    vt.assert_exit(result)
    assert not result.timed_out, "the program did not terminate"
    # Non-vacuity: a real frame must have reached the terminal, and at
    # least TWO full frames (a frame is _HEIGHT screen lines), and the
    # program must mark its frame starts (home runs).
    assert b"\x1b[48;2;" in result.raw, "no colour frame reached the terminal"
    assert result.screen.line_origins, "the CLI drew no frame at all"
    assert len(result.screen.line_origins) >= 2 * _HEIGHT, (
        "fewer than two frames reached the terminal (screen-level "
        "invariants would be vacuous)")
    assert vt._last_frame_start(result.raw) is not None, (
        "the program never marks a frame start — no_residue is inapplicable")
    vt.assert_stable_line_origin(result.screen)
    vt.assert_no_scroll(result.screen)
    vt.assert_no_wrap(result.screen)
    vt.assert_no_residue(result)
    vt.assert_termios_restored(result)
    vt.assert_cursor_restored(result.screen)


def test_bounded_fire_under_a_real_terminal_homes_and_leaves_no_residue():
    result = vt.run_pty(
        _cli_args(3) + ["--frames", "4", "--fps", "50"],
        rows=_ROWS, cols=_COLS, timeout=30.0, cwd=_REPO,
        prelude=_PRELUDE,
    )
    _assert_terminal_contract(result)


def test_interactive_fire_exits_cleanly_on_q_typed_by_a_real_user():
    result = vt.run_pty(
        _cli_args(1) + ["--fps", "8"],
        feed=[(2.0, b"q\n")],
        rows=_ROWS, cols=_COLS, timeout=30.0, cwd=_REPO,
        prelude=_PRELUDE,
    )
    _assert_terminal_contract(result)
