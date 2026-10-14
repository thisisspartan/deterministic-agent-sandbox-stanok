"""CC-264: doomfire terminal controller — alternate screen, signals, teardown.

Fixtures live inside this file (no conftest.py). The controller is exercised
against io.StringIO — never a real TTY. The exact escape sequences, the
flag-only signal handlers, the idempotent teardown, the one-write/one-flush
present and the module purity are the contract and are exercised exactly.
"""

import atexit
import io
import signal
from pathlib import Path

import pytest

from src.doomfire_terminal import (
    EXIT_SIGINT,
    EXIT_SIGTERM,
    TerminalController,
)

MODULE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "doomfire_terminal.py"

SETUP_SEQUENCE = "\x1b[?1049h\x1b[?25l"
TEARDOWN_SEQUENCE = "\x1b[?25h\x1b[?1049l"

MANAGED_SIGNALS = (signal.SIGINT, signal.SIGTERM, signal.SIGWINCH)


class _CountingStream(io.StringIO):
    """io.StringIO that counts write()/flush() calls — the contract demands
    exactly one write and one flush per frame, no per-cell writes."""

    def __init__(self):
        super().__init__()
        self.writes = 0
        self.flushes = 0

    def write(self, s):
        self.writes += 1
        return super().write(s)

    def flush(self):
        self.flushes += 1
        super().flush()


@pytest.fixture
def restore_signal_handlers():
    """setup() installs process-wide handlers; restore the process defaults
    afterwards so the test process is not left with the controller's."""
    original = {sig: signal.getsignal(sig) for sig in MANAGED_SIGNALS}
    yield
    for sig, handler in original.items():
        signal.signal(sig, handler)


# 1. setup()


def test_setup_writes_exact_alternate_screen_and_hide_cursor_sequence():
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    assert stream.getvalue() == SETUP_SEQUENCE


def test_second_setup_writes_nothing_more():
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    controller.setup()
    assert stream.getvalue() == SETUP_SEQUENCE


def test_setup_registers_teardown_via_atexit_exactly_once(monkeypatch, restore_signal_handlers):
    registered = []
    monkeypatch.setattr(atexit, "register", registered.append)
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    assert len(registered) == 1
    assert registered[0] == controller.teardown
    # the registered callable performs the exact teardown when invoked
    registered[0]()
    assert stream.getvalue() == SETUP_SEQUENCE + TEARDOWN_SEQUENCE


def test_setup_installs_handlers_for_all_three_signals(restore_signal_handlers):
    defaults = {sig: signal.getsignal(sig) for sig in MANAGED_SIGNALS}
    controller = TerminalController(io.StringIO())
    controller.setup()
    for sig in MANAGED_SIGNALS:
        handler = signal.getsignal(sig)
        assert callable(handler)
        assert handler is not defaults[sig], f"no handler installed for {sig}"


# 2. teardown()


def test_teardown_writes_exact_show_cursor_and_exit_alternate_screen_sequence():
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.teardown()
    assert stream.getvalue() == TEARDOWN_SEQUENCE


def test_teardown_is_idempotent_second_call_is_a_noop():
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.teardown()
    controller.teardown()
    assert stream.getvalue() == TEARDOWN_SEQUENCE


def test_teardown_after_setup_full_sequence_and_second_call_does_not_raise(
    restore_signal_handlers,
):
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    controller.teardown()
    controller.teardown()  # safe after teardown; must not raise, must not write
    assert stream.getvalue() == SETUP_SEQUENCE + TEARDOWN_SEQUENCE


# 3. Signal handlers: flags only, exit codes recorded, no exception


def test_sigint_handler_sets_should_exit_and_records_130(restore_signal_handlers):
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    handler = signal.getsignal(signal.SIGINT)
    handler(signal.SIGINT, None)  # must not raise
    assert controller.should_exit is True
    assert controller.exit_code == 130
    assert controller.resize_requested is False


def test_sigterm_handler_sets_should_exit_and_records_143(restore_signal_handlers):
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    handler = signal.getsignal(signal.SIGTERM)
    handler(signal.SIGTERM, None)  # must not raise
    assert controller.should_exit is True
    assert controller.exit_code == 143
    assert controller.resize_requested is False


def test_sigwinch_handler_sets_resize_requested_only(restore_signal_handlers):
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    handler = signal.getsignal(signal.SIGWINCH)
    handler(signal.SIGWINCH, None)  # must not raise
    assert controller.resize_requested is True
    assert controller.should_exit is False


def test_module_level_exit_constants():
    assert EXIT_SIGINT == 130
    assert EXIT_SIGTERM == 143


# 4. present(): one write, one flush per frame


def test_present_writes_frame_exactly_once_and_flushes_once():
    stream = _CountingStream()
    controller = TerminalController(stream)
    controller.present("X")
    assert stream.getvalue() == "X"
    assert stream.writes == 1
    assert stream.flushes == 1


def test_present_multi_line_frame_is_still_one_write_one_flush():
    stream = _CountingStream()
    controller = TerminalController(stream)
    frame = "line1\nline2\n"
    controller.present(frame)
    assert stream.getvalue() == frame
    assert stream.writes == 1
    assert stream.flushes == 1


# 5. clear_flags()


def test_flags_start_false():
    controller = TerminalController(io.StringIO())
    assert controller.should_exit is False
    assert controller.resize_requested is False


def test_clear_flags_resets_both_flags(restore_signal_handlers):
    stream = io.StringIO()
    controller = TerminalController(stream)
    controller.setup()
    signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
    signal.getsignal(signal.SIGWINCH)(signal.SIGWINCH, None)
    assert controller.should_exit is True
    assert controller.resize_requested is True
    controller.clear_flags()
    assert controller.should_exit is False
    assert controller.resize_requested is False


# 6. Source purity: no sys/os/time, no project imports


def test_module_is_pure():
    src = MODULE_SOURCE.read_text(encoding="utf-8")
    for needle in (
        "import sys",
        "import os",
        "import time",
        "doomfire_core",
        "doomfire_palette",
    ):
        assert needle not in src, f"impure construct in module source: {needle!r}"
