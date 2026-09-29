"""Reference tests for the performance budget and small-terminal polish
(TASK-FIRE-12, CC-110).

Contract:
- Performance budget: 300 frames of ``advance(1)`` + ``current_frame()``
  on an 80x24 app (seed 42) must complete in under 5.0 seconds.
- Small terminals: ``main`` with ``--width``/``--height`` overrides must
  render exactly ``width * height`` half-blocks (U+2580) per frame and
  return 0 — including the degenerate 1x1 terminal.
- Determinism: two ``FireApp`` instances with the same seed, size and
  call sequence produce identical frames after 60 frames.
"""

import io
import time

from fire.cli import FireApp, main


def test_perf_300_frames_budget():
    app = FireApp(fps=30, seed=42, width=80, height=24, stream=io.StringIO())
    start = time.perf_counter()
    for _ in range(300):
        app.advance(1)
        app.current_frame()
    elapsed = time.perf_counter() - start
    assert elapsed < 5.0, f"300 frames took {elapsed:.2f}s (budget 5.0s)"


def test_small_terminal_10x5():
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frame", "0", "--width", "10", "--height", "5"],
        stream=buf,
    )
    assert rc == 0
    assert buf.getvalue().count("\u2580") == 50


def test_tiny_terminal_1x1():
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frame", "0", "--width", "1", "--height", "1"],
        stream=buf,
    )
    assert rc == 0
    assert buf.getvalue().count("\u2580") == 1


def test_small_terminal_frames():
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frames", "5", "--width", "10", "--height", "5"],
        stream=buf,
    )
    assert rc == 0
    assert buf.getvalue().count("\u2580") == 250


def test_deterministic_60_frame_run():
    app1 = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    app2 = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    app1.advance(60)
    app2.advance(60)
    assert app1.current_frame() == app2.current_frame()
