"""Color-capability + licking-flame contract tests for src/fire.py (CC-113).

Run via:  bash scripts/run.sh test tests/fire_color_test.py

Covers: nearest-256-color quantization (``rgb_to_256``), terminal color
capability detection (``detect_color_mode``), the ``render()``
``color_mode`` argument (truecolor default / 256 / none), the CLI
``--color`` flag (forced mode, headless default stays truecolor), and the
licking-flame shape (internal gaps / tongues in the middle body rows and
no terminal-edge contact on the base row).
"""

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")

import fire  # src is on sys.path via pythonpath=src in run.sh

# One cell: a truecolor half-block or a plain space (the default renderer).
TRUECOLOR_CELL_RE = re.compile(r"(\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[0m▀| )")
# One cell in 256-color mode.
ANSI256_CELL_RE = re.compile(r"(\x1b\[38;5;(\d+)m\x1b\[0m▀| )")

W, H = 80, 24          # shape-contract frame grid
SEED = 42             # fixed seed -> deterministic frames
TICKS = 30            # run to steady state


def _run_py(args):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable] + args,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )


def _decode_truecolor(frame):
    """Truecolor frame -> list of rows; each cell True (colored) / False."""
    grid = []
    for line in frame.split("\n"):
        row = []
        pos = 0
        for m in TRUECOLOR_CELL_RE.finditer(line):
            assert m.start() == pos, "frame is not cell-aligned"
            pos = m.end()
            row.append(m.group(2) is not None)
        assert pos == len(line), "trailing garbage in line"
        grid.append(row)
    return grid


def _steady_grid():
    sim = fire.FireSim(W, H, seed=SEED)
    for _ in range(TICKS):
        sim.tick()
    return _decode_truecolor(fire.render(sim))


# --- rgb_to_256 ---------------------------------------------------------------

def test_rgb_to_256_anchor_colors():
    assert fire.rgb_to_256((0, 0, 0)) == 16
    assert fire.rgb_to_256((255, 255, 255)) == 231
    assert 196 <= fire.rgb_to_256((255, 0, 0)) <= 202


def test_rgb_to_256_range_and_deterministic():
    for rgb in ((0, 0, 0), (255, 255, 255), (255, 0, 0), (0, 255, 0),
                (0, 0, 255), (127, 127, 127), (200, 100, 50), (12, 34, 200)):
        idx = fire.rgb_to_256(rgb)
        assert isinstance(idx, int)
        assert 0 <= idx <= 255
        assert fire.rgb_to_256(rgb) == idx, "rgb_to_256 must be deterministic"


# --- detect_color_mode ----------------------------------------------------------

def test_detect_color_mode_matrix():
    assert fire.detect_color_mode({"COLORTERM": "truecolor"}) == "truecolor"
    assert fire.detect_color_mode({"COLORTERM": "24bit"}) == "truecolor"
    assert fire.detect_color_mode({"COLORTERM": "TRUECOLOR"}) == "truecolor"
    assert fire.detect_color_mode({"TERM": "xterm-256color"}) == "256"
    assert fire.detect_color_mode({"TERM": "dumb"}) == "none"
    assert fire.detect_color_mode({}) == "none"
    # COLORTERM takes precedence over TERM.
    assert fire.detect_color_mode(
        {"COLORTERM": "truecolor", "TERM": "xterm-256color"}
    ) == "truecolor"


def test_detect_color_mode_none_env_uses_os_environ():
    assert fire.detect_color_mode(None) in ("truecolor", "256", "none")


# --- render color_mode ------------------------------------------------------------

def test_render_default_still_emits_truecolor():
    """Regression guard: the default call is byte-compatible with the
    truecolor renderer (every cell matches the truecolor cell regex)."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    assert "\x1b[38;2;" in frame
    for line in frame.split("\n"):
        pos = 0
        for m in TRUECOLOR_CELL_RE.finditer(line):
            assert m.start() == pos, "frame is not cell-aligned"
            pos = m.end()
        assert pos == len(line), "trailing garbage in line"


def test_render_256_mode_cell_aligned_and_in_range():
    sim = fire.FireSim(40, 12, seed=42)
    for _ in range(20):
        sim.tick()
    frame = fire.render(sim, color_mode="256")
    lines = frame.split("\n")
    assert len(lines) == 12
    colored = 0
    for line in lines:
        pos = 0
        for m in ANSI256_CELL_RE.finditer(line):
            assert m.start() == pos, "256-mode frame is not cell-aligned"
            pos = m.end()
            if m.group(2) is not None:
                idx = int(m.group(2))
                assert 0 <= idx <= 255, f"256 index {idx} out of range"
                colored += 1
        assert pos == len(line), "trailing garbage in line"
    assert colored > 0, "256-mode frame has no colored cells"
    assert "\x1b[38;2;" not in frame, "256 mode must not emit truecolor escapes"


def test_render_none_mode_has_no_ansi():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="none")
    assert "\x1b[" not in frame, "none mode must emit no ANSI escapes"
    for line in frame.split("\n"):
        assert set(line) <= {" ", "▀"}, f"none-mode line has extra chars: {line!r}"


# --- licking flame: internal gaps --------------------------------------------------

def _has_internal_gap(row):
    """True iff the row has colored i < blank j < colored k (tongue gap)."""
    colored = [x for x, c in enumerate(row) if c]
    return any(
        colored[b] - colored[a] >= 2
        for a in range(len(colored) - 1)
        for b in (a + 1,)
    )


def test_middle_body_rows_have_internal_gaps():
    """In >= 50% of the middle flame-body rows (strictly between the
    topmost and bottommost body rows) a blank cell sits strictly between
    two colored cells: the body licks, it is not a solid cone."""
    grid = _steady_grid()
    body = [y for y in range(H) if any(grid[y])]
    assert body, "flame body is empty: no colored cells at all"
    y_top, y_bot = min(body), max(body)
    middle = [y for y in body if y_top < y < y_bot]
    assert middle, "flame body has no middle rows"
    gap_rows = [y for y in middle if _has_internal_gap(grid[y])]
    assert len(gap_rows) / len(middle) >= 0.50, (
        f"only {len(gap_rows)}/{len(middle)} middle rows have internal gaps; "
        f"at least 50% must (gap rows: {gap_rows}, middle: {middle})"
    )


# --- licking flame: no edge contact ---------------------------------------------------

def test_base_row_does_not_touch_terminal_edges():
    """On the base row the leftmost colored cell is not in column 0 and
    the rightmost is not in the last column: the flame does not touch the
    terminal edges."""
    grid = _steady_grid()
    base = grid[H - 1]
    lit = [x for x, c in enumerate(base) if c]
    assert lit, "base row has no colored cells"
    assert lit[0] != 0, f"leftmost base cell is in column 0 (edge contact)"
    assert lit[-1] != W - 1, f"rightmost base cell is in the last column"


# --- CLI --color flag ---------------------------------------------------------------

def test_cli_color_none_forces_plain_output():
    p = _run_py(["src/fire.py", "--color", "none", "--frame", "5",
                 "--width", "24", "--height", "10"])
    assert p.returncode == 0, p.stderr
    assert "\x1b[" not in p.stdout, "--color none must emit no ANSI escapes"
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 10
    for line in lines:
        assert len(line) == 24, "plain cells: line must be exactly width chars"


def test_cli_color_256_forces_256_escapes():
    p = _run_py(["src/fire.py", "--color", "256", "--frame", "5",
                 "--width", "24", "--height", "10"])
    assert p.returncode == 0, p.stderr
    assert "\x1b[38;5;" in p.stdout, "--color 256 must emit 38;5 escapes"
    assert "\x1b[38;2;" not in p.stdout, "--color 256 must not emit truecolor"


def test_cli_headless_default_stays_truecolor():
    p = _run_py(["src/fire.py", "--frame", "5", "--width", "24", "--height", "10"])
    assert p.returncode == 0, p.stderr
    assert "\x1b[38;2;" in p.stdout, "headless default must stay truecolor"
