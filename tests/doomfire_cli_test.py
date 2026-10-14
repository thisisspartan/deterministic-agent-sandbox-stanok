"""CC-265: doomfire runner CLI — headless rendering and the interactive guard.

Fixtures live inside this file (no conftest.py). The interactive loop is never
started: it needs a real TTY. What IS exercised is the CLI contract around it —
the argparse surface, the headless byte-for-byte determinism, the explicit
UTF-8 write to sys.stdout.buffer, the non-TTY refusal (rc=2), the frame count
and the module's import purity. The headless path is run both as a subprocess
(the real CLI, `python3 src/doomfire.py ...`) and in-process through
main(argv) with a stand-in sys.stdout.
"""

import io
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src import doomfire

SRC = Path(__file__).resolve().parent.parent / "src"
REPO_ROOT = SRC.parent
MODULE_SOURCE = SRC / "doomfire.py"

SETUP_SEQUENCE = "\x1b[?1049h\x1b[?25l"
TEARDOWN_SEQUENCE = "\x1b[?25h\x1b[?1049l"

ALLOWED_IMPORTS = {
    "sys",
    "argparse",
    "random",
    "shutil",
    "time",
    "doomfire_core",
    "doomfire_palette",
    "doomfire_terminal",
}


def run_cli(*args, timeout=30):
    """Run the real CLI as a subprocess: python3 src/doomfire.py <args>."""
    return subprocess.run(
        [sys.executable, str(SRC / "doomfire.py"), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=timeout,
    )


class _StdoutShim:
    """Stand-in for sys.stdout carrying only what the CLI may touch: a
    .buffer for the headless bytes and isatty() for the interactive guard."""

    def __init__(self):
        self.buffer = io.BytesIO()

    def isatty(self):
        return False


# 1. Headless mode: determinism, explicit UTF-8, ANSI half-block output


def test_headless_output_is_byte_identical_across_two_subprocess_runs():
    args = ("--headless", "3", "--seed", "42", "--width", "8", "--height", "4")
    first = run_cli(*args)
    second = run_cli(*args)
    assert first.returncode == 0, first.stderr.decode("utf-8", "replace")
    assert second.returncode == 0, second.stderr.decode("utf-8", "replace")
    assert first.stdout == second.stdout
    assert first.stdout != b""
    text = first.stdout.decode("utf-8")  # must be valid UTF-8
    assert "\x1b[38;2;" in text
    assert "▀" in text


def test_headless_output_is_valid_utf8_even_with_a_plain_ascii_environment():
    # locale-independent by contract: the CLI encodes to UTF-8 explicitly, so
    # a C/POSIX locale (ASCII stdout) must not break it or change the bytes.
    args = ("--headless", "1", "--seed", "42", "--width", "8", "--height", "4")
    env = {**os.environ, "LC_ALL": "C", "LANG": "C", "PYTHONIOENCODING": "ascii"}
    plain = run_cli(*args)
    forced = subprocess.run(
        [sys.executable, str(SRC / "doomfire.py"), *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=30,
        env=env,
    )
    assert plain.returncode == 0 and forced.returncode == 0
    assert forced.stdout == plain.stdout
    assert forced.stdout.decode("utf-8")


def test_headless_renders_exactly_n_half_block_frames():
    proc = run_cli("--headless", "3", "--seed", "42", "--width", "8", "--height", "4")
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8")
    lines = text.split("\n")
    assert lines[-1] == ""  # newline-terminated
    assert len(lines) - 1 == 3 * ((4 + 1) // 2)  # one frame = (height+1)//2 lines
    assert text.count("▀") == 3 * 8 * ((4 + 1) // 2)


def test_headless_zero_frames_writes_nothing_and_exits_zero():
    proc = run_cli("--headless", "0", "--seed", "1")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout == b""


def test_headless_does_not_write_terminal_setup_or_teardown_sequences():
    proc = run_cli("--headless", "1", "--seed", "3", "--width", "4", "--height", "2")
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8")
    for sequence in (SETUP_SEQUENCE, TEARDOWN_SEQUENCE, "\x1b[?1049h", "\x1b[?1049l"):
        assert sequence not in text


def test_default_dimensions_are_80x24():
    proc = run_cli("--headless", "1", "--seed", "5")
    assert proc.returncode == 0
    text = proc.stdout.decode("utf-8")
    assert text.count("\n") == (24 + 1) // 2
    assert text.count("▀") == 80 * ((24 + 1) // 2)


def test_ascii_headless_writes_no_escapes_and_no_half_blocks():
    proc = run_cli("--ascii", "--headless", "2", "--seed", "7", "--width", "6", "--height", "3")
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    text = proc.stdout.decode("utf-8")
    assert "\x1b" not in text
    assert "▀" not in text
    lines = text.split("\n")
    assert lines[-1] == ""
    assert len(lines) - 1 == 2 * 3  # ASCII mode renders rows 1:1
    assert all(len(line) == 6 for line in lines[:-1])
    assert all(set(line) <= set(" .:-=+*#%@") for line in lines[:-1])


def test_headless_is_deterministic_for_a_seed_and_differs_between_seeds():
    same = [run_cli("--headless", "2", "--seed", "42", "--width", "16", "--height", "6").stdout for _ in range(2)]
    assert same[0] == same[1]
    other = run_cli("--headless", "2", "--seed", "43", "--width", "16", "--height", "6").stdout
    assert other != same[0]


# 2. main(argv) in-process: the explicit UTF-8 write goes to sys.stdout.buffer


def test_main_headless_writes_utf8_bytes_to_stdout_buffer_and_returns_zero(monkeypatch):
    shim = _StdoutShim()
    monkeypatch.setattr(sys, "stdout", shim)
    code = doomfire.main(["--headless", "1", "--seed", "1", "--width", "2", "--height", "2"])
    assert code == 0
    raw = shim.buffer.getvalue()
    assert raw != b""
    text = raw.decode("utf-8")
    assert "\x1b[38;2;" in text
    assert "▀" in text
    assert text.count("\n") == (2 + 1) // 2


def test_main_headless_is_repeatable_in_one_process(monkeypatch):
    # no hidden global RNG state: two identical calls produce identical bytes
    args = ["--headless", "2", "--seed", "42", "--width", "6", "--height", "4"]
    outputs = []
    for _ in range(2):
        shim = _StdoutShim()
        monkeypatch.setattr(sys, "stdout", shim)
        assert doomfire.main(args) == 0
        outputs.append(shim.buffer.getvalue())
    assert outputs[0] == outputs[1] and outputs[0] != b""


def test_main_headless_ascii_writes_plain_text_to_stdout_buffer(monkeypatch):
    shim = _StdoutShim()
    monkeypatch.setattr(sys, "stdout", shim)
    code = doomfire.main(
        ["--ascii", "--headless", "2", "--seed", "7", "--width", "6", "--height", "3"]
    )
    assert code == 0
    text = shim.buffer.getvalue().decode("utf-8")
    assert "\x1b" not in text
    assert "▀" not in text


# 3. Import safety: importing the module starts no loop and prints nothing


def test_importing_the_module_prints_nothing_and_does_not_block():
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), str(SRC)])}
    proc = subprocess.run(
        [sys.executable, "-c", "import src.doomfire"],
        cwd=str(REPO_ROOT),
        capture_output=True,
        timeout=15,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", "replace")
    assert proc.stdout == b""


def test_importing_the_module_in_process_prints_nothing(capsys):
    sys.modules.pop("src.doomfire", None)
    assert doomfire.main(["--headless", "0", "--seed", "0"]) == 0
    assert capsys.readouterr().out == ""


# 4. Interactive mode: refused without a TTY (rc=2, one-line hint on stderr)


def test_interactive_without_a_tty_refuses_with_exit_two_and_writes_no_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    code = doomfire.main([])
    assert code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    hint = captured.err
    assert hint.strip()
    assert hint.count("\n") <= 1  # exactly one line
    assert "--headless" in hint  # the hint names the non-interactive mode


def test_interactive_without_a_tty_does_not_start_a_loop_or_touch_the_terminal(monkeypatch, capsys):
    # the refusal must not enter the alternate screen, install handlers or
    # render a single frame: stdout stays untouched, exit code is 2.
    monkeypatch.setattr(sys.stdout, "isatty", lambda: False)
    assert doomfire.main(["--seed", "1", "--width", "3", "--height", "2", "--fps", "60"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""


def test_headless_mode_does_not_require_a_tty(monkeypatch):
    # --headless must not consult isatty at all; a non-TTY stdout still works.
    shim = _StdoutShim()
    monkeypatch.setattr(sys, "stdout", shim)
    assert doomfire.main(["--headless", "1", "--seed", "2", "--width", "2", "--height", "2"]) == 0
    assert shim.buffer.getvalue() != b""


# 5. argparse surface: out-of-range values are usage errors (SystemExit 2)


@pytest.mark.parametrize(
    "flag,value",
    [
        ("--fps", "0"),
        ("--fps", "61"),
        ("--width", "0"),
        ("--height", "0"),
        ("--headless", "-1"),
        ("--fps", "not-a-number"),
    ],
)
def test_out_of_range_flag_is_a_usage_error(monkeypatch, flag, value):
    monkeypatch.setattr(sys, "stderr", io.StringIO())
    with pytest.raises(SystemExit) as excinfo:
        doomfire.main([flag, value, "--headless", "1"])
    assert excinfo.value.code == 2


def test_flags_are_accepted_in_any_order_and_headless_is_optional(monkeypatch):
    shim = _StdoutShim()
    monkeypatch.setattr(sys, "stdout", shim)
    assert doomfire.main(["--width", "4", "--height", "2", "--seed", "9", "--fps", "60", "--headless", "1"]) == 0
    assert shim.buffer.getvalue() != b""


# 6. Source purity: only the allowed imports, no curses/termios, no duplicated
# terminal escape sequences (teardown belongs to the controller)


def test_module_imports_only_the_allowed_modules():
    source = MODULE_SOURCE.read_text(encoding="utf-8")
    imported = set()
    for line in source.splitlines():
        match = re.match(r"\s*(?:from|import)\s+([A-Za-z_][A-Za-z0-9_.]*)", line)
        if match:
            imported.add(match.group(1).split(".")[0])
    unexpected = imported - ALLOWED_IMPORTS
    assert not unexpected, f"disallowed import(s) in src/doomfire.py: {sorted(unexpected)}"


def test_module_does_not_use_curses_or_termios():
    source = MODULE_SOURCE.read_text(encoding="utf-8")
    for needle in ("curses", "termios"):
        assert needle not in source, f"{needle} used in src/doomfire.py"


def test_module_does_not_duplicate_the_terminal_escape_sequences():
    source = MODULE_SOURCE.read_text(encoding="utf-8")
    for needle in ("\x1b[?1049h", "\x1b[?1049l", "\x1b[?25l", "\x1b[?25h", "?1049", "?25"):
        assert needle not in source, f"escape sequence written outside the controller: {needle!r}"


def test_module_has_a_testable_main_and_a_main_guard():
    source = MODULE_SOURCE.read_text(encoding="utf-8")
    assert "def main(argv=None)" in source
    assert 'if __name__ == "__main__":' in source
    assert "sys.exit(main())" in source
