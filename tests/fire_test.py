"""TASK-STANOK-CC-270: console fire — the contract of src/fire.py.

Four concerns, four groups of tests: simulation (pure, seeded), palette
(pure), renderer (pure), CLI (headless-safe). The module is imported as
`fire` because the runner sets pythonpath=src.
"""

import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

import fire

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_FIRE = REPO_ROOT / "src" / "fire.py"

ANSI_ANY = re.compile(r"\x1b\[[0-9;]*m")
TRUECOLOR = re.compile(r"\x1b\[(38|48);2;(\d+);(\d+);(\d+)m")


def _strip(text):
    return ANSI_ANY.sub("", text)


def _lum(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _frames(seed, width, height, ticks):
    """Render `ticks` frames from a seed: the same path the CLI takes."""
    return [
        fire.render_frame(field, rng=random.Random(seed))
        for field in fire.simulate(seed, width, height, ticks)
    ]


def _mean(values):
    return sum(values) / len(values)


# --- 1. determinism -------------------------------------------------------


def test_same_seed_and_dimensions_give_identical_frames():
    a = _frames(7, 24, 10, 6)
    b = _frames(7, 24, 10, 6)
    assert a == b
    assert any("\x1b[38;2;" in f for f in a), "frames are trivially empty"


def test_different_seeds_give_different_output():
    a = _frames(1, 24, 10, 6)
    b = _frames(2, 24, 10, 6)
    assert a != b


# --- 2. heat bounds and ignition -----------------------------------------


def test_heat_stays_in_the_unit_interval():
    rng = random.Random(11)
    field = fire.new_field(30, 12)
    for _ in range(40):
        field = fire.advance(field, rng)
        for row in field:
            assert len(row) == 30
            for value in row:
                assert 0.0 <= value <= 1.0, f"heat {value!r} out of [0,1]"
    assert len(field) == 12


def test_base_row_is_ignited_by_the_first_tick():
    rng = random.Random(3)
    field = fire.advance(fire.new_field(30, 12), rng)
    base = field[-1]
    assert min(base) >= 0.5, f"base row not hot: {min(base)}"
    assert _mean(base) >= 0.8, f"base row too cool: {_mean(base)}"


def test_the_field_changes_between_ticks():
    fields = fire.simulate(5, 24, 10, 4)
    assert len(fields) == 4
    assert fields[0] != fields[1]
    assert fields[2] != fields[3]


# --- 3. decay and shape --------------------------------------------------


def test_base_rows_run_hotter_than_top_rows():
    field = fire.simulate(5, 40, 20, 30)[-1]
    base = _mean([v for row in field[-2:] for v in row])
    top = _mean([v for row in field[:3] for v in row])
    assert base > top + 0.1, f"base {base} is not hotter than top {top}"


def test_flame_reaches_rows_above_the_base_but_not_the_top():
    field = fire.simulate(5, 40, 20, 30)[-1]
    just_above = field[-3]
    assert any(v >= 0.3 for v in just_above), "the flame does not climb above the base"
    top = field[0]
    hot = sum(1 for v in top if v >= 0.3)
    assert hot <= len(top) // 4, f"topmost row is not cold: {hot} hot cells"
    assert _mean(top) < 0.25, f"topmost row average heat {_mean(top)}"


def test_the_flame_top_x_position_varies_across_frames():
    fields = fire.simulate(9, 40, 20, 25)
    row = 12  # seven rows above the base
    tops = set()
    for field in fields[10:]:
        hot = [c for c in range(40) if field[row][c] >= 0.25]
        if hot:
            tops.add(max(hot, key=lambda c: field[row][c]))
    assert len(tops) >= 3, f"static cone: only {len(tops)} distinct flame tops"


# --- 4. palette contract -------------------------------------------------


def test_palette_returns_none_for_an_empty_cell():
    assert fire.heat_to_rgb(0.0) is None
    assert fire.heat_to_rgb(-0.3) is None
    assert fire.heat_to_rgb(0.0, base_zone=True) is None


def test_palette_components_stay_in_0_255():
    # heat 0 emits nothing (test_palette_returns_none_for_an_empty_cell);
    # this covers every heat that does emit.
    for step in range(1, 101):
        heat = step / 100
        for base_zone in (False, True):
            rgb = fire.heat_to_rgb(heat, base_zone=base_zone, rng=random.Random(step))
            assert rgb is not None
            assert len(rgb) == 3
            for component in rgb:
                assert isinstance(component, int)
                assert 0 <= component <= 255, f"component {component} out of range"


def test_palette_luminance_increases_with_heat():
    previous = -1.0
    for step in range(1, 101):  # heat 0 emits no colour at all
        rgb = fire.heat_to_rgb(step / 100)
        assert rgb is not None
        current = _lum(rgb)
        assert current > previous, f"luminance falls at heat {step / 100}"
        previous = current


def test_palette_hot_end_is_the_white_hot_stop():
    assert fire.heat_to_rgb(1.0) == (255, 255, 240)
    cold = fire.heat_to_rgb(0.01)
    assert cold is not None and max(cold) < 120, f"cold end is not dark: {cold}"


def test_base_zone_colors_are_blue_dominant():
    for step in range(1, 101):
        rgb = fire.heat_to_rgb(step / 100, base_zone=True, rng=random.Random(step))
        assert rgb[2] > rgb[0], f"not blue-dominant at heat {step / 100}: {rgb}"


# --- 5. renderer ---------------------------------------------------------


def test_frame_line_count_matches_the_grid():
    for height in (10, 11, 20):
        field = fire.simulate(4, 16, height, 3)[-1]
        lines = fire.render_frame(field, rng=random.Random(4)).split("\n")
        assert len(lines) == (height + 1) // 2, f"height {height}: {len(lines)} lines"
        for line in lines:
            assert len(_strip(line)) == 16, f"line width {len(_strip(line))}"


def test_a_hot_frame_uses_truecolor_sequences():
    field = fire.simulate(4, 16, 10, 3)[-1]
    frame = fire.render_frame(field, rng=random.Random(4))
    assert "\x1b[38;2;" in frame
    assert "\x1b[48;2;" in frame, "half-block needs a background colour too"
    assert "▀" in frame


def test_an_all_zero_field_renders_without_color_escapes():
    frame = fire.render_frame(fire.new_field(12, 6), rng=random.Random(0))
    assert "\x1b" not in frame, f"empty cells emitted ANSI: {frame!r}"
    lines = frame.split("\n")
    assert len(lines) == 3
    assert all(line == " " * 12 for line in lines)


# --- 6. flicker / no banding --------------------------------------------


def test_consecutive_frames_differ():
    fields = fire.simulate(8, 20, 10, 6)
    rendered = [fire.render_frame(f, rng=random.Random(8)) for f in fields]
    for i in range(len(rendered) - 1):
        assert rendered[i] != rendered[i + 1], f"frame {i} == frame {i + 1}"


def test_adjacent_equal_heat_cells_render_different_colors():
    field = fire.new_field(20, 4)
    for row in field:
        for c in range(len(row)):
            row[c] = 0.6
    frame = fire.render_frame(field, rng=random.Random(123))
    colors = {match.group(0) for match in TRUECOLOR.finditer(frame)}
    assert len(colors) >= 2, "color banding: equal-heat neighbours are identical"


# --- 7. headless CLI -----------------------------------------------------


def _cli(*args, env_extra=None):
    env = os.environ.copy()
    env.pop("COLUMNS", None)
    env.pop("LINES", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(SRC_FIRE), *args],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        env=env,
        timeout=30,
    )


def test_cli_frame_is_deterministic_and_exits_zero():
    args = ("--frame", "7", "--seed", "42", "--width", "20", "--height", "8")
    first, second = _cli(*args), _cli(*args)
    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert first.stdout.strip(), "no frame on stdout"
    assert first.stdout == second.stdout, "--frame is not deterministic"
    assert "\x1b[38;2;" in first.stdout


def test_cli_frames_count_exits_zero():
    result = _cli("--frames", "3", "--seed", "1", "--width", "12", "--height", "6")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip()


def test_cli_without_a_tty_renders_one_frame_and_exits():
    started = time.monotonic()
    result = _cli("--seed", "2", "--width", "12", "--height", "6")
    assert result.returncode == 0, result.stderr
    assert time.monotonic() - started < 10, "the headless path did not terminate"
    lines = result.stdout.splitlines()
    assert lines, "no frame on stdout"
    assert len(lines) <= 3, f"headless path rendered {len(lines)} lines, expected one frame"


def test_cli_renders_in_a_small_terminal():
    result = _cli("--seed", "3", env_extra={"COLUMNS": "10", "LINES": "5"})
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines, "no frame on stdout"
    assert len(lines) <= 5, f"{len(lines)} lines do not fit a 5-row terminal"
    for line in lines:
        assert len(_strip(line)) <= 10, f"{len(_strip(line))} columns do not fit 10"
