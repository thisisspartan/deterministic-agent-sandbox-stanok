"""Reference tests for TASK-STANOK-CC-251 (FIRE2-04): src/fire_input.py —
the pure key parser and the non-blocking raw-mode KeyReader — and its wiring
into FireApp (src/fire_main.py).

No real terminal is required: the parser is pure; KeyReader is exercised on
os.pipe() fds (the non-tty path) and on a pty.openpty() pair (the raw-mode
setup/restore path); the wiring is driven through the injected fakes
established in tests/fire_main_test.py (sink / clock / size_fn), with a spy
field recording the wind each step() receives.
"""

import os
import pty
import termios
import time
from contextlib import contextmanager

import pytest

import fire_main
from fire_input import KeyReader, parse_key
from fire_engine import FireField, WIND_LIMIT
from fire_main import FireApp
from fire_render import ENTER, EXIT


# --- pure parser ---------------------------------------------------------------


@pytest.mark.parametrize(
    "data, action",
    [
        (b"\x1b[D", "wind_left"),
        (b"\x1b[C", "wind_right"),
        (b"\x1b[A", "intensity_up"),
        (b"\x1b[B", "intensity_down"),
        (b"q", "quit"),
        (b"\x03", "quit"),
    ],
)
def test_parse_key_maps_each_sequence_to_its_action(data, action):
    assert parse_key(data) == action


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x1b",
        b"\x1b[",
        b"\x1b[Z",
        b"\x1b[CJ",  # an arrow sequence glued to noise
        b"\x1b[C\x1b[D",  # two keys in one read: multi-byte noise
        b"ab",
        b"Q",
        b"\x04",
        b"\xff",
    ],
)
def test_parse_key_returns_none_for_unknown_bytes(data):
    assert parse_key(data) is None


# --- KeyReader: non-blocking poll on a pipe fd ---------------------------------


def test_read_returns_none_immediately_when_the_fd_has_no_data():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        start = time.monotonic()
        assert reader.read() is None
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"read() must never block; it took {elapsed:.3f}s"
    finally:
        reader.close()
        os.close(r)
        os.close(w)


def test_read_parses_a_key_written_to_the_pipe():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        os.write(w, b"\x1b[C")
        assert reader.read() == "wind_right"
        assert reader.read() is None  # the fd is drained
    finally:
        reader.close()
        os.close(r)
        os.close(w)


def test_read_returns_none_on_eof_without_raising():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        os.close(w)  # EOF: select reports readable, os.read returns b""
        assert reader.read() is None
    finally:
        reader.close()
        os.close(r)


def test_read_returns_none_for_multi_byte_noise():
    r, w = os.pipe()
    reader = KeyReader(r)
    try:
        os.write(w, b"ab")
        assert reader.read() is None
    finally:
        reader.close()
        os.close(r)
        os.close(w)


# --- KeyReader: raw mode set on a tty, restored on close ----------------------


def test_raw_mode_is_applied_on_a_tty_and_restored_on_close():
    master, slave = pty.openpty()
    try:
        before = termios.tcgetattr(slave)
        reader = KeyReader(slave)
        during = termios.tcgetattr(slave)
        assert during != before, "raw-mode setup must change the termios settings"
        reader.close()
        after = termios.tcgetattr(slave)
        assert after == before, "close() must restore the saved termios state"
        reader.close()  # idempotent
        assert termios.tcgetattr(slave) == before
    finally:
        os.close(master)
        os.close(slave)


# --- wiring into FireApp ---------------------------------------------------------


class FakeSink:
    """Output sink: records every write. out.write must receive a str."""

    def __init__(self):
        self.writes = []

    def write(self, text):
        assert isinstance(text, str), f"out.write must receive a str, got {text!r}"
        self.writes.append(text)


class FakeClock:
    """Injected clock: perf_counter never advances on its own (work is free);
    sleep records and advances the clock by the requested budget."""

    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def perf_counter(self):
        return self.now

    def sleep(self, seconds):
        assert seconds > 0, f"sleep must be called only with a positive budget, got {seconds!r}"
        self.sleeps.append(seconds)
        self.now += seconds


class FakeKeys:
    """KeyReader stand-in: hands out the queued actions, then None forever."""

    def __init__(self, actions=()):
        self.actions = list(actions)
        self.polls = 0

    def read(self):
        self.polls += 1
        if self.actions:
            return self.actions.pop(0)
        return None


_SPY_FIELDS = []


class SpyField:
    """FireField stand-in that records the wind of every step() call and
    delegates the real simulation, so the buffer stays observable."""

    def __init__(self, width, height, rng=None):
        self._inner = FireField(width, height, rng=rng)
        self.winds = []
        _SPY_FIELDS.append(self)

    @property
    def width(self):
        return self._inner.width

    @property
    def height(self):
        return self._inner.height

    @property
    def buffer(self):
        return self._inner.buffer

    def step(self, wind=0):
        self.winds.append(wind)
        self._inner.step(wind)


@contextmanager
def spy_field_installed():
    original = fire_main.FireField
    _SPY_FIELDS.clear()
    fire_main.FireField = SpyField
    try:
        yield _SPY_FIELDS
    finally:
        fire_main.FireField = original


def make_app(size=(8, 3), wind=0, keys=None):
    sink = FakeSink()
    clock = FakeClock()
    app = FireApp(
        out=sink, clock=clock, size_fn=lambda: size, wind=wind, keys=keys
    )
    return app, sink, clock


def frames_of(sink):
    """The frame writes of a completed run: ENTER, then frames, then EXIT."""
    writes = sink.writes
    assert writes, "a run must write something"
    assert writes[0] == ENTER, "the first write must be ENTER"
    assert writes[-1] == EXIT, "the last write must be EXIT"
    return writes[1:-1]


def test_keys_none_leaves_the_loop_unchanged():
    # The default (keys=None) is the contract of every existing test; a keys
    # source that always answers None must change nothing either.
    app, sink, clock = make_app(size=(4, 2), keys=FakeKeys([]))
    app.run(fps=30, max_frames=2)
    assert len(frames_of(sink)) == 2
    assert app.wind == 0
    assert app.field.buffer[-4:] == [36] * 4  # the source row is untouched


def test_wind_right_key_increases_the_wind_passed_to_step():
    keys = FakeKeys(["wind_right"])
    with spy_field_installed() as spies:
        app, sink, clock = make_app(size=(4, 2), keys=keys)
        app.run(fps=30, max_frames=3)
    assert app.wind == 1
    assert len(spies) == 1
    assert spies[0].winds == [1, 1, 1]  # applied once, before the first step


def test_wind_left_key_decreases_the_wind_and_keys_poll_once_per_tick():
    # The poll happens BEFORE step, so the tick that sees the key already
    # steps with the updated wind.
    keys = FakeKeys(["wind_left", None, "wind_left"])
    with spy_field_installed() as spies:
        app, sink, clock = make_app(size=(4, 2), wind=2, keys=keys)
        app.run(fps=30, max_frames=3)
    assert app.wind == 0
    assert spies[0].winds == [1, 1, 0]
    assert keys.polls == 3  # exactly one poll per tick


def test_wind_keys_are_clamped_to_the_engine_limit():
    keys = FakeKeys(["wind_right"] * 10)
    with spy_field_installed() as spies:
        app, sink, clock = make_app(size=(4, 2), keys=keys)
        app.run(fps=30, max_frames=10)
    assert app.wind == WIND_LIMIT
    assert spies[0].winds == [min(i, WIND_LIMIT) for i in range(1, 11)]


def test_intensity_up_adds_extra_decay_to_the_field_before_step():
    # Documented choice (see src/fire_main.py): FireField.step has no
    # intensity parameter, so intensity is an extra decay applied to every
    # value before step: value -= 1 per intensity level, clamped >= 0.
    # The bottom (source) row is seeded to 36 and step never rewrites it,
    # so after one tick it reads 36 - 1*level.
    keys = FakeKeys(["intensity_up"])
    app, sink, clock = make_app(size=(4, 2), keys=keys)
    app.run(fps=30, max_frames=1)
    assert app.intensity == 1
    assert app.field.buffer[-4:] == [35] * 4


def test_intensity_levels_accumulate_and_clamp_at_zero():
    keys = FakeKeys(["intensity_up", "intensity_up", "intensity_down"])
    app, sink, clock = make_app(size=(4, 2), keys=keys)
    app.run(fps=30, max_frames=3)
    assert app.intensity == 1  # up, up, down -> level 1
    # The decay runs every tick before step: 36 -1 -> 35, -2 -> 33, -1 -> 32.
    assert app.field.buffer[-4:] == [32] * 4

    keys = FakeKeys(["intensity_down"] * 5)
    app2, sink2, _ = make_app(size=(4, 2), keys=keys)
    app2.run(fps=30, max_frames=1)
    assert app2.intensity == 0  # clamped >= 0
    assert app2.field.buffer[-4:] == [36] * 4  # no decay at level 0


def test_quit_key_stops_the_loop_with_exactly_one_exit():
    keys = FakeKeys(["quit"])
    app, sink, clock = make_app(size=(4, 2), keys=keys)
    app.run(fps=30, max_frames=50)  # the stop request, not max_frames, ends it
    assert len(frames_of(sink)) == 1  # the tick that saw "quit" completes
    assert sink.writes.count(EXIT) == 1
    app.teardown()
    assert sink.writes.count(EXIT) == 1  # teardown still exactly once
