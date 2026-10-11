"""Tests for src/fire_input.py and its wiring into src/fire_main.py
(TASK-STANOK-CC-243 / FIRE-04).

Contract under test:
- parse_key(data: bytes) -> action | None: pure parser for the arrow-key
  escape sequences (wind_left / wind_right / intensity_up / intensity_down),
  b"q" and b"\\x03" (quit); anything else -> None.
- KeyReader(fd): raw-mode setup via termios/tty with restore on close;
  read() is NON-BLOCKING (returns None immediately when no data — guarded
  with SIGALRM, no sleep trick) and returns the parsed action for written
  bytes.
- FireApp wiring: optional `keys` (duck-typed .read()); once per tick,
  BEFORE step: wind_left/right adjust app.wind (clamped [-3, 3]),
  intensity_up/down adjust the extra decay applied to field values before
  step (value -= 1 per level, clamped >= 0; source row untouched), "quit"
  requests stop (same path as SIGINT, teardown exactly once). keys=None:
  behavior unchanged.

All fakes are pinned and deterministic: a fake keys queue, a spy field
recording (wind, buffer snapshot) per step, the existing fake clock/sink
pattern.
"""

import os
import pty
import signal
import termios

import pytest

from src import fire_render
from src.fire_input import KeyReader, parse_key
from src.fire_main import FireApp


# --- fakes (same pattern as tests/fire_main_test.py) -------------------------


class FakeSink:
    def __init__(self):
        self.writes = []

    def write(self, s):
        self.writes.append(s)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def perf_counter(self):
        v = self.t
        self.t += 0.0
        return v

    def sleep(self, s):
        self.t += s


class FakeSize:
    def __init__(self, cols, rows):
        self.cols = cols
        self.rows = rows

    def __call__(self):
        return (self.cols, self.rows)


class FakeKeys:
    """read() pops the next queued action, then always returns None."""

    def __init__(self, actions=()):
        self.actions = list(actions)
        self.reads = 0

    def read(self):
        self.reads += 1
        if self.actions:
            return self.actions.pop(0)
        return None


class SpyField:
    """Records (wind, buffer snapshot) at each step; performs no propagation."""

    def __init__(self, width, height, seed_rows=None):
        self.width = width
        self.height = height
        self.buffer = [0] * (width * height)
        base = (height - 1) * width
        for x in range(width):
            self.buffer[base + x] = 36  # source row, like FireField
        if seed_rows is not None:
            for y, row in enumerate(seed_rows):
                self.buffer[y * width:(y + 1) * width] = list(row)
        self.calls = []  # [(wind, buffer copy), ...]

    def step(self, wind=0):
        self.calls.append((wind, list(self.buffer)))


class SpyApp(FireApp):
    field_class = SpyField
    seed_rows = None

    def _new_field(self, width, height):
        return self.field_class(width, height, seed_rows=self.seed_rows)


def make_app(keys=None, size=(4, 1), seed_rows=None):
    sink = FakeSink()
    app = SpyApp(out=sink, clock=FakeClock(), size_fn=FakeSize(*size),
                 keys=keys)
    app.seed_rows = seed_rows
    if seed_rows is not None:
        app.field = SpyApp.field_class(app.field.width, app.field.height,
                                      seed_rows=seed_rows)
    return app, sink


def frames_of(sink):
    return sink.writes[1:-1]


# --- pure parser --------------------------------------------------------------

@pytest.mark.parametrize("data,expected", [
    (b"\x1b[D", "wind_left"),
    (b"\x1b[C", "wind_right"),
    (b"\x1b[A", "intensity_up"),
    (b"\x1b[B", "intensity_down"),
    (b"q", "quit"),
    (b"\x03", "quit"),
])
def test_parse_key_maps_each_sequence_to_its_action(data, expected):
    assert parse_key(data) == expected


@pytest.mark.parametrize("data", [
    b"",
    b"x",
    b"\x1b",
    b"\x1bE",
    b"\x1b[Z",
    b"\x00",
    b"\x04",
    b"hello",
    b"\x1b[C\x1b[D",
    b"\x1b[Cextra",
    b"Q",
])
def test_parse_key_returns_none_for_unknown_and_noise(data):
    assert parse_key(data) is None


# --- KeyReader: non-blocking read on a pipe -----------------------------------

def _call_without_blocking(fn):
    """Call fn(); fail loudly if it blocks (SIGALRM guard — no sleep trick)."""
    def handler(signum, frame):
        raise AssertionError("read() blocked")

    old = signal.signal(signal.SIGALRM, handler)
    signal.alarm(2)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def test_keyreader_read_returns_none_immediately_when_no_data():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        assert _call_without_blocking(reader.read) is None
        # twice more: still non-blocking, still None
        assert _call_without_blocking(reader.read) is None
        assert _call_without_blocking(reader.read) is None
    finally:
        reader.close()
        os.close(r)
        os.close(w)


def test_keyreader_read_parses_written_bytes():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        os.write(w, b"\x1b[C")
        assert _call_without_blocking(reader.read) == "wind_right"
        assert _call_without_blocking(reader.read) is None  # drained
        os.write(w, b"q")
        assert _call_without_blocking(reader.read) == "quit"
        os.write(w, b"zz")
        assert _call_without_blocking(reader.read) is None  # noise -> None
    finally:
        reader.close()
        os.close(r)
        os.close(w)


def test_keyreader_sets_raw_mode_and_restores_on_close():
    master, slave = pty.openpty()
    try:
        before = termios.tcgetattr(master)
        reader = KeyReader(master)
        try:
            during = termios.tcgetattr(master)
            # raw mode active: terminal settings changed while open
            assert during != before
            # echo is off in raw mode
            assert not (during[3] & termios.ECHO)
        finally:
            reader.close()
        after = termios.tcgetattr(master)
        assert after == before  # restored exactly
        # close is idempotent
        reader.close()
        assert termios.tcgetattr(master) == before
    finally:
        os.close(master)
        os.close(slave)


def test_keyreader_on_tty_reads_arrow_key_written_to_slave():
    master, slave = pty.openpty()
    try:
        reader = KeyReader(master)
        try:
            os.write(slave, b"\x1b[A")
            assert _call_without_blocking(reader.read) == "intensity_up"
        finally:
            reader.close()
    finally:
        os.close(master)
        os.close(slave)


# --- wiring: keys -> FireApp ---------------------------------------------------

def test_no_keys_behavior_unchanged_wind_stays_zero():
    app, sink = make_app(keys=None)
    app.run(fps=30, max_frames=3)
    assert [c[0] for c in app.field.calls] == [0, 0, 0]
    assert len(frames_of(sink)) == 3
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


def test_keys_polled_exactly_once_per_tick_before_step():
    keys = FakeKeys()
    app, _sink = make_app(keys=keys)
    app.run(fps=30, max_frames=4)
    assert keys.reads == 4
    assert len(app.field.calls) == 4


def test_wind_right_increases_wind_used_in_step():
    keys = FakeKeys([None, "wind_right", None])
    app, _sink = make_app(keys=keys)
    app.run(fps=30, max_frames=3)
    # polled before step: frame 1 sees 0, frames 2-3 see 1
    assert [c[0] for c in app.field.calls] == [0, 1, 1]


def test_wind_left_decreases_wind_used_in_step():
    keys = FakeKeys(["wind_left", "wind_left"])
    app, _sink = make_app(keys=keys)
    app.run(fps=30, max_frames=2)
    assert [c[0] for c in app.field.calls] == [-1, -2]


def test_wind_is_clamped_to_minus_three_through_three():
    keys = FakeKeys(["wind_right"] * 6 + ["wind_left"] * 10)
    app, _sink = make_app(keys=keys)
    app.run(fps=30, max_frames=16)
    winds = [c[0] for c in app.field.calls]
    assert max(winds) == 3
    assert min(winds) == -3
    assert all(-3 <= w <= 3 for w in winds)


def test_quit_stops_the_loop_with_exactly_one_exit():
    keys = FakeKeys([None, None, "quit"])
    app, sink = make_app(keys=keys)
    app.run(fps=30, max_frames=None)  # unbounded: only the key stops it
    assert len(frames_of(sink)) == 2
    assert sum(w == fire_render.ENTER for w in sink.writes) == 1
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


def test_quit_on_first_tick_stops_before_any_frame():
    keys = FakeKeys(["quit"])
    app, sink = make_app(keys=keys)
    app.run(fps=30, max_frames=5)
    assert frames_of(sink) == []
    assert app.field.calls == []
    assert sum(w == fire_render.EXIT for w in sink.writes) == 1


# --- wiring: intensity as extra decay applied before step ---------------------

def test_intensity_up_applies_extra_decay_to_values_before_step():
    # non-source rows seeded with known values; source row must stay 36.
    seed = [[10, 5, 1, 0]]
    keys = FakeKeys(["intensity_up", None])
    app, _sink = make_app(keys=keys, size=(4, 1), seed_rows=seed)
    app.run(fps=30, max_frames=2)
    snap1 = app.field.calls[0][1]
    snap2 = app.field.calls[1][1]
    # level 1: each value -= 1, clamped at 0; source row untouched
    assert snap1[0:4] == [9, 4, 0, 0]
    assert snap1[4:8] == [36, 36, 36, 36]
    # intensity persists: decay applied again on the next tick
    assert snap2[0:4] == [8, 3, 0, 0]
    assert snap2[4:8] == [36, 36, 36, 36]


def test_intensity_down_cancels_decay_and_clamps_at_zero():
    seed = [[10, 5, 1, 0]]
    keys = FakeKeys(["intensity_down", "intensity_up", "intensity_down",
                     "intensity_down", None])
    app, _sink = make_app(keys=keys, size=(4, 1), seed_rows=seed)
    app.run(fps=30, max_frames=5)
    snaps = [c[1] for c in app.field.calls]
    # tick 1: intensity_down from 0 stays 0 -> no decay
    assert snaps[0][0:4] == [10, 5, 1, 0]
    # tick 2: intensity_up -> decay by 1
    assert snaps[1][0:4] == [9, 4, 0, 0]
    # tick 3: intensity_down -> back to 0, no further decay
    assert snaps[2][0:4] == [9, 4, 0, 0]
    # ticks 4-5: intensity stays clamped at 0
    assert snaps[3][0:4] == [9, 4, 0, 0]
    assert snaps[4][0:4] == [9, 4, 0, 0]


def test_intensity_decay_never_goes_below_zero():
    seed = [[0, 1, 2, 3]]
    keys = FakeKeys(["intensity_up"] * 3)
    app, _sink = make_app(keys=keys, size=(4, 1), seed_rows=seed)
    app.run(fps=30, max_frames=3)
    snaps = [c[1] for c in app.field.calls]
    # each level subtracts 1: level 1 -> -1, level 2 -> -2, level 3 -> -3,
    # every value clamped at 0.
    assert snaps[0][0:4] == [0, 0, 1, 2]
    assert snaps[1][0:4] == [0, 0, 0, 0]
    assert snaps[2][0:4] == [0, 0, 0, 0]
    assert all(v >= 0 for v in app.field.buffer)
