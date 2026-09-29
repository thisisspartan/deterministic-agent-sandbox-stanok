"""Reference tests for the headless CLI entry point (TASK-FIRE-09).

Contract:
- ``fire.cli.main(argv, stream=buf)`` is callable in-process (no
  subprocess): it parses ``argv`` with ``build_parser()``, constructs a
  ``FireApp`` and renders deterministically.
- ``--frame N``: advance N frames, write exactly the rendered frame N to
  ``stream``, return 0. Same seed + same size => identical output.
- ``--seed``: the simulator's PRNG seed; a different seed yields a
  different frame.
- ``--frames N``: write N frames (0..N-1), each followed by ``\\n``,
  return 0.
- No ``--frame``/``--frames`` and stdin is not a TTY (headless): write
  exactly one frame (frame 0), return 0.
- ``--width``/``--height`` override the terminal size: a frame contains
  exactly ``width * height`` half-blocks (U+2580).
"""

import io

from fire.cli import main


def test_frame_n_deterministic():
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    rc1 = main(
        ["--seed", "42", "--frame", "5", "--width", "20", "--height", "10"],
        stream=buf1,
    )
    rc2 = main(
        ["--seed", "42", "--frame", "5", "--width", "20", "--height", "10"],
        stream=buf2,
    )
    assert rc1 == 0
    assert rc2 == 0
    out1 = buf1.getvalue()
    out2 = buf2.getvalue()
    assert out1 == out2
    assert out1 != ""


def test_seed_changes_frame():
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    main(
        ["--seed", "42", "--frame", "5", "--width", "20", "--height", "10"],
        stream=buf1,
    )
    main(
        ["--seed", "43", "--frame", "5", "--width", "20", "--height", "10"],
        stream=buf2,
    )
    assert buf1.getvalue() != buf2.getvalue()


def test_frames_n_exits_zero():
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frames", "3", "--width", "20", "--height", "10"],
        stream=buf,
    )
    assert rc == 0
    assert buf.getvalue().count("\u2580") == 3 * 20 * 10


def test_headless_one_frame():
    # No --frame/--frames; pytest runs without a TTY -> headless branch.
    buf = io.StringIO()
    rc = main(["--seed", "42", "--width", "20", "--height", "10"], stream=buf)
    assert rc == 0
    assert buf.getvalue().count("\u2580") == 20 * 10


def test_width_height_respected():
    buf1 = io.StringIO()
    buf2 = io.StringIO()
    main(["--frame", "0", "--width", "20", "--height", "10"], stream=buf1)
    main(["--frame", "0", "--width", "20", "--height", "20"], stream=buf2)
    assert buf1.getvalue().count("\u2580") == 200
    assert buf2.getvalue().count("\u2580") == 400
