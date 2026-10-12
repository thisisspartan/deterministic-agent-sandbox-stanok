"""Reference tests for TASK-STANOK-CC-250 (FIRE2-03): src/fire_main.py — the
runnable main loop: FPS timing, resize-safe geometry, guaranteed teardown.

The loop is driven entirely through injected fakes (sink / clock / size_fn):
no real TTY is touched. Two subprocess tests exercise the real program
(`python3 src/fire_main.py`) end to end.
"""

import os
import signal
import subprocess
import sys
import time

import pytest

import fire_main
from fire_main import FireApp
from fire_render import ENTER, EXIT

HOME = "\x1b[H"
RESET = "\x1b[0m"
CELL = "▀"  # U+2580 UPPER HALF BLOCK

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRE_MAIN_SRC = os.path.join(REPO_ROOT, "src", "fire_main.py")
HANDLED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGWINCH)


# --- fakes ------------------------------------------------------------------


class FakeSink:
    """Output sink: records every write. out.write must receive a str."""

    def __init__(self):
        self.writes = []

    def write(self, text):
        assert isinstance(text, str), f"out.write must receive a str, got {text!r}"
        self.writes.append(text)


class FakeClock:
    """Injected clock.

    perf_counter() advances by `work` seconds per call — `work` models the CPU
    time spent in step/render, so the app's measured delta is exactly `work`
    per frame. sleep() records the requested duration and advances the clock
    by it. hook_after_sleep(n, fn) runs fn right after the n-th sleep, which
    is the test's handle on "between frames".
    """

    def __init__(self, work=0.0):
        self.work = work
        self.now = 0.0
        self.sleeps = []
        self._hooks = {}

    def perf_counter(self):
        self.now += self.work
        return self.now

    def sleep(self, seconds):
        assert seconds > 0, f"sleep must be called only with a positive budget, got {seconds!r}"
        self.sleeps.append(seconds)
        self.now += seconds
        hook = self._hooks.get(len(self.sleeps))
        if hook is not None:
            hook()

    def hook_after_sleep(self, n, fn):
        self._hooks[n] = fn


class FakeSize:
    """Callable size_fn returning the current (cols, rows)."""

    def __init__(self, size):
        self.size = size

    def __call__(self):
        return self.size

    def set(self, size):
        self.size = size


def make_app(size=(8, 3), work=0.0, wind=0):
    sink = FakeSink()
    clock = FakeClock(work=work)
    size_fn = FakeSize(size)
    app = FireApp(out=sink, clock=clock, size_fn=size_fn, wind=wind)
    return app, sink, clock, size_fn


def frames_of(sink):
    """The frame writes of a completed run: ENTER, then frames, then EXIT."""
    writes = sink.writes
    assert writes, "a run must write something"
    assert writes[0] == ENTER, "the first write must be ENTER"
    assert writes[-1] == EXIT, "the last write must be EXIT"
    frames = writes[1:-1]
    for frame in frames:
        assert ENTER not in frame and EXIT not in frame, "a frame contains no ENTER/EXIT"
    return frames


def frame_geometry(frame):
    """(width, terminal_rows) of a rendered frame, checking its structure."""
    assert frame.startswith(HOME), "a frame starts with cursor home"
    assert frame.endswith(RESET), "a frame ends with the SGR reset"
    body = frame[len(HOME):len(frame) - len(RESET)]
    rows = body.split("\n")
    widths = {row.count(CELL) for row in rows}
    assert len(widths) == 1, f"all rows of a frame have the same width: {widths}"
    return widths.pop(), len(rows)


def current_handlers():
    return {sig: signal.getsignal(sig) for sig in HANDLED_SIGNALS}


def raise_sigwinch_after_resize(size_fn, new_size):
    def hook():
        size_fn.set(new_size)
        os.kill(os.getpid(), signal.SIGWINCH)
    return hook


# --- the loop: writes, ENTER/EXIT, one write per frame ----------------------


def test_bounded_run_writes_enter_once_and_exit_once():
    app, sink, clock, size_fn = make_app()
    app.run(fps=30, max_frames=3)
    assert sink.writes.count(ENTER) == 1
    assert sink.writes.count(EXIT) == 1
    assert sink.writes[0] == ENTER
    assert sink.writes[-1] == EXIT
    assert len(sink.writes) == 1 + 3 + 1


def test_exactly_one_write_per_frame():
    app, sink, clock, size_fn = make_app(size=(6, 2))
    for max_frames in (1, 2, 5):
        app2, sink2, _, _ = make_app(size=(6, 2))
        app2.run(fps=30, max_frames=max_frames)
        frames = frames_of(sink2)
        assert len(frames) == max_frames
        for frame in frames:
            assert frame_geometry(frame) == (6, 2)


def test_frames_are_complete_rendered_frames_at_the_requested_geometry():
    app, sink, clock, size_fn = make_app(size=(4, 3))
    app.run(fps=30, max_frames=4)
    frames = frames_of(sink)
    assert len(frames) == 4
    for frame in frames:
        assert frame_geometry(frame) == (4, 3)
        assert "\x1b[2J" not in frame  # no clear-screen: the renderer repaints


def test_field_is_cols_by_twice_the_rows():
    app, sink, clock, size_fn = make_app(size=(6, 4))
    app.run(fps=30, max_frames=1)
    assert app.field.width == 6
    assert app.field.height == 8  # half-block: rows * 2
    assert len(app.field.buffer) == 6 * 8
    assert app.field.buffer[-6:] == [36] * 6  # the source row is seeded


def test_max_frames_none_is_not_exercised_without_a_stop_request():
    # A bounded run is the testable contract; an unbounded one is stopped by
    # the signal path (covered below via os.kill).
    app, sink, clock, size_fn = make_app()
    clock.hook_after_sleep(1, lambda: os.kill(os.getpid(), signal.SIGTERM))
    app.run(fps=30)  # max_frames=None: the loop ends only on the stop request
    assert len(frames_of(sink)) == 1


# --- teardown: guaranteed and idempotent -------------------------------------


def test_teardown_is_idempotent_after_a_run():
    app, sink, clock, size_fn = make_app()
    app.run(fps=30, max_frames=2)
    app.teardown()
    app.teardown()
    app.teardown()
    assert sink.writes.count(EXIT) == 1
    assert sink.writes[-1] == EXIT


def test_teardown_without_a_run_writes_nothing():
    app, sink, clock, size_fn = make_app()
    app.teardown()
    app.teardown()
    assert sink.writes == []


def test_teardown_runs_even_when_the_loop_body_raises():
    class BoomField:
        def __init__(self, width, height):
            self.width = width
            self.height = height
            self.buffer = [0] * (width * height)

        def step(self, wind=0):
            raise RuntimeError("boom in step")

    monkeypatched = fire_main.FireField
    fire_main.FireField = BoomField
    try:
        app, sink, clock, size_fn = make_app()
        with pytest.raises(RuntimeError, match="boom in step"):
            app.run(fps=30, max_frames=5)
        # ENTER + exactly one EXIT, no frame: the teardown is guaranteed.
        assert sink.writes == [ENTER, EXIT]
        app.teardown()
        assert sink.writes.count(EXIT) == 1
    finally:
        fire_main.FireField = monkeypatched


def test_sigint_handler_path_stops_the_loop_and_writes_exit_once():
    app, sink, clock, size_fn = make_app()
    clock.hook_after_sleep(2, lambda: os.kill(os.getpid(), signal.SIGINT))
    app.run(fps=30, max_frames=50)  # the stop request, not max_frames, ends it
    frames = frames_of(sink)
    assert len(frames) == 2
    assert sink.writes.count(EXIT) == 1
    app.teardown()
    assert sink.writes.count(EXIT) == 1


def test_sigterm_handler_path_stops_the_loop_and_writes_exit_once():
    app, sink, clock, size_fn = make_app()
    clock.hook_after_sleep(3, lambda: os.kill(os.getpid(), signal.SIGTERM))
    app.run(fps=30, max_frames=50)
    frames = frames_of(sink)
    assert len(frames) == 3
    assert sink.writes.count(EXIT) == 1
    app.teardown()
    assert sink.writes.count(EXIT) == 1


def test_signal_handlers_are_installed_during_the_run_and_restored_after():
    original = current_handlers()
    app, sink, clock, size_fn = make_app()
    installed = {}
    clock.hook_after_sleep(1, lambda: installed.update(current_handlers()))
    app.run(fps=30, max_frames=2)
    assert installed[signal.SIGINT] == app.handle_stop
    assert installed[signal.SIGTERM] == app.handle_stop
    assert installed[signal.SIGWINCH] == app.handle_winch
    # No handler leaks past the run.
    assert current_handlers() == original


# --- resize: flag only in the handler, geometry rebuilt at tick start --------


def test_winch_handler_sets_a_flag_only_and_touches_no_buffers():
    app, sink, clock, size_fn = make_app(size=(5, 2))
    app.run(fps=30, max_frames=1)
    field = app.field
    before = list(field.buffer)
    app.handle_winch(signal.SIGWINCH, None)
    assert app.field is field, "the handler must not rebuild the field"
    assert app.field.buffer == before, "the handler must not touch the buffer"
    assert (app.field.width, app.field.height) == (5, 4)


def test_resize_is_applied_at_the_next_tick_start_with_no_index_error():
    app, sink, clock, size_fn = make_app(size=(10, 5))
    clock.hook_after_sleep(2, raise_sigwinch_after_resize(size_fn, (4, 3)))
    app.run(fps=30, max_frames=4)  # the frame count is preserved across a resize
    frames = frames_of(sink)
    assert len(frames) == 4
    assert [frame_geometry(f) for f in frames] == [(10, 5), (10, 5), (4, 3), (4, 3)]
    assert app.field.width == 4 and app.field.height == 6


def test_a_size_change_before_the_run_is_used_from_the_first_frame():
    app, sink, clock, size_fn = make_app(size=(9, 4))
    app.handle_winch(signal.SIGWINCH, None)  # a stale flag must not cost a frame
    size_fn.set((3, 2))
    app.run(fps=30, max_frames=2)
    frames = frames_of(sink)
    assert [frame_geometry(f) for f in frames] == [(3, 2), (3, 2)]


def test_repeated_resize_signals_between_frames_are_applied_once_each():
    app, sink, clock, size_fn = make_app(size=(6, 3))
    clock.hook_after_sleep(1, lambda: os.kill(os.getpid(), signal.SIGWINCH))
    clock.hook_after_sleep(2, raise_sigwinch_after_resize(size_fn, (2, 2)))
    clock.hook_after_sleep(3, lambda: os.kill(os.getpid(), signal.SIGWINCH))
    app.run(fps=30, max_frames=4)
    frames = frames_of(sink)
    assert [frame_geometry(f) for f in frames] == [(6, 3), (6, 3), (2, 2), (2, 2)]


# --- delta-time compensation -------------------------------------------------


def test_sleeps_compensate_the_whole_frame_budget_when_work_is_free():
    app, sink, clock, size_fn = make_app(work=0.0)
    app.run(fps=30, max_frames=4)
    assert clock.sleeps == [1 / 30] * 4


def test_sleeps_compensate_only_the_remaining_budget_when_work_is_measured():
    work = 0.01
    app, sink, clock, size_fn = make_app(work=work)
    app.run(fps=30, max_frames=4)
    assert clock.sleeps == pytest.approx([1 / 30 - work] * 4, abs=1e-9)


def test_a_frame_that_overruns_its_budget_is_not_sleeped_on():
    app, sink, clock, size_fn = make_app(work=0.1)  # 0.1 s > 1/30 s budget
    app.run(fps=60, max_frames=3)
    assert clock.sleeps == []
    assert len(frames_of(sink)) == 3


def test_fps_sets_the_frame_budget():
    for fps, expected in ((10, 1 / 10), (60, 1 / 60)):
        app, sink, clock, size_fn = make_app()
        app.run(fps=fps, max_frames=2)
        assert clock.sleeps == [expected] * 2


def test_non_positive_fps_is_rejected_before_anything_is_written():
    app, sink, clock, size_fn = make_app()
    with pytest.raises(ValueError):
        app.run(fps=0, max_frames=1)
    with pytest.raises(ValueError):
        app.run(fps=-5, max_frames=1)
    assert sink.writes == []


# --- the real program: python3 src/fire_main.py ------------------------------


def run_real_program(args, sig):
    env = dict(os.environ, COLUMNS="12", LINES="4", PYTHONIOENCODING="utf-8")
    proc = subprocess.Popen(
        [sys.executable, FIRE_MAIN_SRC] + list(args),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        env=env,
    )
    time.sleep(0.4)  # let it enter the alternate screen and paint some frames
    proc.send_signal(sig)
    out, err = proc.communicate(timeout=15)
    return proc.returncode, out.decode("utf-8", "replace"), err


def test_real_program_exits_cleanly_and_writes_exit_once_on_sigint_and_sigterm():
    for sig in (signal.SIGINT, signal.SIGTERM):
        code, out, err = run_real_program(["--fps", "60"], sig)
        assert code == 0, f"{sig.name}: graceful exit expected, got rc={code} err={err!r}"
        assert out.startswith(ENTER), f"{sig.name}: the alternate screen must be entered"
        assert out.endswith(EXIT), f"{sig.name}: the terminal must be restored"
        assert out.count(EXIT) == 1
        assert out.count(ENTER) == 1


def test_real_program_rejects_a_non_integer_fps():
    code, out, err = run_real_program(["--fps", "not-a-number"], signal.SIGTERM)
    assert code == 2
    assert out == ""
