"""CC-288 — reference tests for src/fire_render.py.

Covers the ticket contract: frame size and cell format, palette colors
end-to-end through render, palette anchors/clamp/monotonicity, absence of
home/clear sequences, purity and determinism, and independence from
fire_engine. No TTY, no subprocesses.
"""
import re
from pathlib import Path

import fire_render

CELL_PREFIX = "\x1b[48;2;"
CELL_RE = re.compile(r"\d+;\d+;\d+m \Z")


def parse_cells(line):
    """Split one frame line into its cells; return list of (r, g, b)."""
    parts = line.split(CELL_PREFIX)
    assert parts[0] == ""  # a line is exactly a concatenation of cells
    colors = []
    for part in parts[1:]:
        m = re.fullmatch(r"(\d+);(\d+);(\d+)m ", part)
        assert m is not None, f"malformed cell: {part!r}"
        colors.append((int(m.group(1)), int(m.group(2)), int(m.group(3))))
    return colors


# ---------------------------------------------------------------- 1. frame size

def test_frame_has_exactly_one_line_per_grid_row():
    grid = [[0] * 6 for _ in range(4)]
    frame = fire_render.render(grid)
    lines = frame.split("\r\n")
    assert len(lines) == 4  # frame height == len(grid)
    assert not frame.endswith("\r\n")  # no trailing line break
    for line in lines:
        assert len(parse_cells(line)) == 6  # frame width == len(grid[0])
        assert line.count(CELL_PREFIX) == 6  # 6 cells, SGR-bg + space each


def test_cell_is_sgr_background_plus_space():
    grid = [[100]]
    frame = fire_render.render(grid)
    r, g, b = fire_render.palette(100)
    assert frame == f"\x1b[48;2;{r};{g};{b}m "  # exact cell, nothing else


# ---------------------------------------------------------------- 2. colors end-to-end

def test_rendered_colors_match_palette():
    grid = [[0, 100, 200, 255, 64, 128, 192]]
    frame = fire_render.render(grid)
    colors = parse_cells(frame.split("\r\n")[0])
    for heat, actual in zip(grid[0], colors):
        assert actual == fire_render.palette(heat)


# ---------------------------------------------------------------- 3. palette

def test_palette_anchors_exact():
    assert fire_render.palette(0) == (0, 0, 0)
    assert fire_render.palette(64) == (135, 0, 0)
    assert fire_render.palette(128) == (255, 60, 0)
    assert fire_render.palette(192) == (255, 160, 0)
    assert fire_render.palette(255) == (255, 255, 0)


def test_palette_clamps_out_of_range_input():
    assert fire_render.palette(-5) == fire_render.palette(0) == (0, 0, 0)
    assert fire_render.palette(300) == fire_render.palette(255) == (255, 255, 0)
    assert fire_render.palette(-1000) == fire_render.palette(0)
    assert fire_render.palette(10**9) == fire_render.palette(255)


def test_palette_monotonic_in_r_and_g():
    prev_r = prev_g = -1
    for heat in range(0, 256):
        r, g, b = fire_render.palette(heat)
        assert 0 <= r <= 255 and 0 <= g <= 255 and 0 <= b <= 255
        assert r >= prev_r, f"R decreased at heat {heat}"
        assert g >= prev_g, f"G decreased at heat {heat}"
        prev_r, prev_g = r, g


def test_palette_between_anchors_is_interpolated():
    # midpoint of 0..64 on the R ramp: halfway to (135, 0, 0)
    r, g, b = fire_render.palette(32)
    assert 0 < r < 135 and g == 0 and b == 0
    # midpoint of 128..192 on the G ramp: halfway to (255, 160, 0)
    r, g, b = fire_render.palette(160)
    assert r == 255 and 60 < g < 160 and b == 0


# ---------------------------------------------------------------- 4. no home/clear

def test_frame_has_no_home_clear_or_cursor_sequences():
    grid = [[h % 256 for h in range(12)] for _ in range(3)]
    frame = fire_render.render(grid)
    for seq in ("\x1b[H", "\x1b[2J", "\x1b[?25", "\x1b[1;", "\x1b[3;"):
        assert seq not in frame
    # home/clear are the CLI's job: the ONLY escapes in the frame are SGR.
    assert frame.count("\x1b") == frame.count(CELL_PREFIX)


# ---------------------------------------------------------------- 5. purity / determinism

def test_render_does_not_mutate_input_grid():
    grid = [[10, 200, 300, -7], [64, 128, 192, 255]]
    before = [row[:] for row in grid]
    fire_render.render(grid)
    assert grid == before


def test_same_grid_byte_identical_output():
    grid = [[i * 7 % 256 for i in range(9)] for _ in range(5)]
    assert fire_render.render(grid) == fire_render.render(grid)


def test_two_grids_rendered_independently():
    a = [[0] * 4 for _ in range(2)]
    b = [[255] * 4 for _ in range(2)]
    frame_a1 = fire_render.render(a)
    frame_b = fire_render.render(b)
    frame_a2 = fire_render.render(a)
    assert frame_a1 == frame_a2  # no hidden state between calls
    assert frame_a1 != frame_b
    assert parse_cells(frame_b.split("\r\n")[0])[0] == (255, 255, 0)


# ---------------------------------------------------------------- 6. no engine import

def test_render_module_does_not_import_the_engine():
    source = Path(__file__).resolve().parent.parent / "src" / "fire_render.py"
    text = source.read_text(encoding="utf-8")
    assert "import fire_engine" not in text
    assert "from src.fire_engine" not in text
    assert "fire_engine" not in re.sub(
        r"#[^\n]*|\"\"\".*?\"\"\"", "", text, flags=re.S
    )  # no reference outside comments/docstrings
