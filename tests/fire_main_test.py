"""Acceptance tests for src/fire_main.py (TASK-STANOK-CC-242 / FIRE-03).

Contract under test (the runnable main loop, driven WITHOUT a real terminal):
- FireApp(out, clock, size_fn): injectable sink / clock / size source;
  field height = rows * 2 (half-block geometry).
- run(fps, max_frames): ENTER once at start; per frame exactly one
  out.write(render_frame(...)); resize flag applied AT TICK START only;
  delta-time compensation via the injected clock; max_frames bounds the loop.
- Teardown GUARANTEED and IDEMPOTENT: EXIT exactly once total via finally +
  atexit + SIGINT/SIGTERM handlers that request stop; a second teardown is a
  no-op. SIGWINCH handler only sets a flag.
- parse_fps: --fps N, default 30.

All fakes are pinned and deterministic: a fake clock with a fixed per-call
overhead, a fake sink recording writes, a fake size_fn.
"""

import os
import signal

import pytest

from src import fire_render
from src.fire_main import FireApp, parse_fps


class FakeSink:
    def __init__(self):
        self.writes = []

    def write(self, s):
        self.writes.append(s)


class FakeClock:
    """perf_counter returns the current virtual time, then advances it by
    `overhead` (simulating the work between two clock reads); sleep advances
    the virtual time and records the requested delay."""

    def __init__(self, start=0.0, overhead=0.0):
        self.t = start
        self.overhead = overhead
        self.sleeps = []
        self.on_sleep = None  # optional callable(n_sleeps_done)

    def perf_counter(self):
        v = self.t
        self.t += self.overhead
        return v

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


class FakeSize:
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows

    def __call__(self):
        return (self.cols, self.rows)


def make_app(size=(8, 4), overhead=0.0):
    sink = FakeSink()
    clock = FakeClock(overhead=overhead)
    size_fn = FakeSize(*size)
    app = FireApp(out=sink, clock=clock, size_fn=size_fn)
    return app, sink, clock, size_fn


def frames_of(sink):
    """The frame writes of a run: everything between ENTER and EXIT."""
    return sink.writes[1:-1]


def half_blocks(frame):
    return frame.count("▀")


# --- geometry ---------------------------------------------------------------

def test_field_height_is_rows_times_two():
    app, _sink, _clock, _size = make_app(size=(10, 5))
    assert app.field.width == 10
    assert app.field.height == 10  # rows * 2, half-block pairing


# --- normal bounded run -----------------------------------------------------

def test_bounded_run_writes_enter_once_and_exit_once():
    app, sink, _clock, _size = make_app()
    app.run(fps=30, max_frames=3)
    assert sink.writes[0] == fire_render.ENTER
    assert sink.writes[-1] == fire_render.EXIT
    assert sum(w == fire_render.ENTER for w in sink.writes) == 1
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1
    assert len(frames_of(sink)) == 3


def test_exactly_one_write_per_frame_and_frames_are_render_frames():
    app, sink, _clock, _size = make_app(size=(6, 3))
    app.run(fps=30, max_frames=4)
    frames = frames_of(sink)
    assert len(frames) == 4
    for frame in frames:
        assert frame.startswith(fire_render.HOME)
        assert frame.endswith(fire_render.RESET)
        # 6 columns x (3*2 rows / 2 terminal rows) = 18 half-block cells.
        assert half_blocks(frame) == 6 * 3


def test_run_returns_cleanly_and_stops_at_max_frames():
    app, sink, _clock, _size = make_app()
    result = app.run(fps=30, max_frames=2)
    assert result is None
    assert len(frames_of(sink)) == 2


# --- teardown idempotency ---------------------------------------------------

def test_teardown_is_idempotent_explicit_calls():
    app, sink, _clock, _size = make_app()
    app.run(fps=30, max_frames=1)
    app.teardown()
    app.teardown()
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


def test_teardown_writes_exit_even_without_run():
    app, sink, _clock, _size = make_app()
    app.teardown()
    app.teardown()
    assert sink.writes == [fire_render.EXIT]


def test_sigint_handler_path_stops_loop_and_exits_exactly_once():
    app, sink, clock, _size = make_app()
    pid = os.getpid()

    def on_sleep(n):
        if n == 2:
            os.kill(pid, signal.SIGINT)

    clock.on_sleep = on_sleep
    app.run(fps=30, max_frames=None)  # unbounded: only the signal stops it
    assert len(frames_of(sink)) == 2
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1
    assert sum(w == fire_render.ENTER for w in sink.writes) == 1


def test_sigterm_handler_path_stops_loop_and_exits_exactly_once():
    app, sink, clock, _size = make_app()
    pid = os.getpid()

    def on_sleep(n):
        if n == 1:
            os.kill(pid, signal.SIGTERM)

    clock.on_sleep = on_sleep
    app.run(fps=30, max_frames=None)
    assert len(frames_of(sink)) == 1
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


def test_exception_in_step_still_tears_down_exactly_once():
    class BoomField:
        def __init__(self, width, height):
            self.width = width
            self.height = height
            self.buffer = [0] * (width * height)
            self.steps = 0

        def step(self, wind=0):
            self.steps += 1
            if self.steps == 3:
                raise RuntimeError("boom")

    class BoomApp(FireApp):
        def _new_field(self, width, height):
            return BoomField(width, height)

    sink = FakeSink()
    app = BoomApp(out=sink, clock=FakeClock(), size_fn=FakeSize(4, 2))
    with pytest.raises(RuntimeError):
        app.run(fps=30, max_frames=10)
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1
    assert sink.writes[0] == fire_render.ENTER
    assert len(frames_of(sink)) == 2  # frames 1-2 rendered, frame 3 raised


# --- resize -----------------------------------------------------------------

def test_resize_flag_applies_new_geometry_at_next_tick_start():
    app, sink, clock, size_fn = make_app(size=(8, 4))
    pid = os.getpid()

    def on_sleep(n):
        if n == 2:
            size_fn.cols, size_fn.rows = 12, 6
            os.kill(pid, signal.SIGWINCH)

    clock.on_sleep = on_sleep
    app.run(fps=30, max_frames=4)  # old frame count preserved

    frames = frames_of(sink)
    assert len(frames) == 4
    # Frames 1-2 use the old geometry: 8 cols x 4 terminal rows.
    assert half_blocks(frames[0]) == 8 * 4
    assert half_blocks(frames[1]) == 8 * 4
    # Frames 3-4 use the new geometry: 12 cols x 6 terminal rows.
    assert half_blocks(frames[2]) == 12 * 6
    assert half_blocks(frames[3]) == 12 * 6
    assert app.field.width == 12
    assert app.field.height == 12
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


def test_winch_handler_only_sets_a_flag_no_buffer_work():
    app, _sink, _clock, size_fn = make_app(size=(5, 2))
    old_field = app.field
    size_fn.cols, size_fn.rows = 9, 3
    app._on_winch(signal.SIGWINCH, None)
    assert app.field is old_field  # no geometry work happened in the handler
    assert app._resized is True


# --- delta-time compensation ------------------------------------------------

def test_sleeps_compensate_the_frame_budget_for_a_pinned_clock():
    # fps=30 -> budget 1/30; each perf_counter read advances the virtual
    # clock by 0.01, so every sleep must be exactly budget - overhead.
    budget = 1.0 / 30.0
    overhead = 0.01
    app, _sink, clock, _size = make_app(overhead=overhead)
    app.run(fps=30, max_frames=3)
    assert len(clock.sleeps) == 3
    for s in clock.sleeps:
        assert s == pytest.approx(budget - overhead)


def test_no_sleep_when_the_frame_is_already_behind_budget():
    app, _sink, clock, _size = make_app(overhead=0.05)  # 0.05 > 1/30
    app.run(fps=30, max_frames=3)
    assert clock.sleeps == []


def test_custom_fps_changes_the_budget():
    budget = 1.0 / 10.0
    overhead = 0.01
    app, _sink, clock, _size = make_app(overhead=overhead)
    app.run(fps=10, max_frames=2)
    assert len(clock.sleeps) == 2
    for s in clock.sleeps:
        assert s == pytest.approx(budget - overhead)


# --- argv parsing ------------------------------------------------------------

def test_parse_fps_defaults_to_30():
    assert parse_fps([]) == 30


def test_parse_fps_reads_the_flag():
    assert parse_fps(["--fps", "60"]) == 60
