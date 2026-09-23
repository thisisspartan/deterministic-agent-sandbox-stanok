"""Color-capability contract tests for src/fire.py (CC-115).

The default color mode is 256: on a terminal that carries no explicit
color signal the flame must still render in 256-color ANSI escapes, not
monochrome. ``detect_color_mode`` returns:

- ``"none"`` on an EXPLICIT opt-out: ``NO_COLOR`` set to a non-empty
  value (wins over everything) or ``TERM == "dumb"``;
- ``"truecolor"`` when ``COLORTERM`` contains ``truecolor`` / ``24bit``
  (case-insensitive);
- ``"256"`` otherwise (the default -- most terminals support 256 colors
  even without ``COLORTERM``).

Run via:  bash scripts/run.sh test tests/fire_color_test.py
"""

import re

import fire  # src is on sys.path via pythonpath=src in run.sh

# One 256-mode cell: an escape-indexed half-block or a plain space.
CELL256_RE = re.compile(r"(\x1b\[38;5;(\d+)m\x1b\[0m▀| )")
# One truecolor cell (default renderer) or a plain space.
CELLTC_RE = re.compile(r"(\x1b\[38;2;\d+;\d+;\d+m\x1b\[0m▀| )")
BLOCK = "\u2580"
SEED = 42
TICKS = 30


def _grid(w, h, seed=SEED, ticks=TICKS):
    """Frame rendered after ``ticks`` ticks (default truecolor mode) ->
    list of rows (top to bottom); each cell is True (colored) or
    False (blank)."""
    sim = fire.FireSim(w, h, seed=seed)
    for _ in range(ticks):
        sim.tick()
    grid = []
    for line in fire.render(sim).split("\n"):
        row = []
        pos = 0
        for m in CELLTC_RE.finditer(line):
            assert m.start() == pos, "frame is not cell-aligned"
            pos = m.end()
            row.append(m.group(1)[0] == "\x1b")
        assert pos == len(line), "trailing garbage in line"
        grid.append(row)
    return grid


# --- rgb_to_256 ---------------------------------------------------------------

def test_rgb_to_256_known_indices():
    # Exact palette hits: black and white tie between the 16 base colors
    # and the 6x6x6 cube; per contract the cube color wins (black -> 16,
    # white -> 231).
    assert fire.rgb_to_256((0, 0, 0)) == 16
    assert fire.rgb_to_256((255, 255, 255)) == 231
    # The 16 base colors resolve to their exact indices.
    assert fire.rgb_to_256((196, 0, 0)) == 1
    assert fire.rgb_to_256((0, 196, 0)) == 2
    assert fire.rgb_to_256((0, 0, 204)) == 4


def test_rgb_to_256_index_in_range():
    for rgb in ((0, 0, 0), (1, 1, 1), (90, 15, 8), (160, 30, 10),
                (255, 140, 0), (255, 220, 80), (255, 255, 240),
                (25, 45, 90), (80, 130, 220), (150, 200, 255),
                (60, 60, 65), (200, 100, 50)):
        idx = fire.rgb_to_256(rgb)
        assert isinstance(idx, int)
        assert 0 <= idx <= 255, f"rgb_to_256({rgb}) = {idx} out of range"


# --- detect_color_mode ---------------------------------------------------------

def test_detect_empty_env_defaults_to_256():
    """No explicit signal -> the default is 256, not monochrome."""
    assert fire.detect_color_mode({}) == "256"


def test_detect_colorterm_truecolor():
    assert fire.detect_color_mode({"COLORTERM": "truecolor"}) == "truecolor"


def test_detect_colorterm_24bit():
    assert fire.detect_color_mode({"COLORTERM": "24bit"}) == "truecolor"


def test_detect_colorterm_case_insensitive():
    assert fire.detect_color_mode({"COLORTERM": "TRUECOLOR"}) == "truecolor"
    assert fire.detect_color_mode({"COLORTERM": "24BIT"}) == "truecolor"


def test_detect_term_256color():
    assert fire.detect_color_mode({"TERM": "xterm-256color"}) == "256"


def test_detect_plain_term_defaults_to_256():
    """TERM without a 256-color signal -> still the 256 default."""
    assert fire.detect_color_mode({"TERM": "xterm"}) == "256"


def test_detect_dumb_term_is_none():
    assert fire.detect_color_mode({"TERM": "dumb"}) == "none"


def test_detect_truecolor_wins_over_term():
    env = {"COLORTERM": "truecolor", "TERM": "xterm-256color"}
    assert fire.detect_color_mode(env) == "truecolor"


def test_detect_no_color_is_none():
    """Explicit opt-out: NO_COLOR set to a non-empty value."""
    assert fire.detect_color_mode({"NO_COLOR": "1"}) == "none"


def test_detect_no_color_wins_over_truecolor():
    env = {"NO_COLOR": "1", "COLORTERM": "truecolor"}
    assert fire.detect_color_mode(env) == "none"


def test_detect_empty_no_color_does_not_opt_out():
    """NO_COLOR set but empty is NOT an explicit opt-out -> 256."""
    assert fire.detect_color_mode({"NO_COLOR": ""}) == "256"


# --- renderer: 256 mode ---------------------------------------------------------

def test_render_256_mode_cell_alignment():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="256")
    assert "\x1b[38;2;" not in frame, "256 mode must not emit truecolor escapes"
    lines = frame.split("\n")
    assert len(lines) == 12
    saw_block = False
    for line in lines:
        pos = 0
        for m in CELL256_RE.finditer(line):
            assert m.start() == pos, "256-mode frame is not cell-aligned"
            pos = m.end()
            idx = m.group(2)
            if idx is not None:
                saw_block = True
                assert 0 <= int(idx) <= 255
        assert pos == len(line), "trailing garbage in 256-mode line"
        assert len(CELL256_RE.findall(line)) == 24
    assert saw_block, "256-mode frame has no colored cells"


def test_render_256_mode_is_deterministic():
    a = fire.FireSim(24, 12, seed=42)
    b = fire.FireSim(24, 12, seed=42)
    for _ in range(8):
        a.tick()
        b.tick()
    assert fire.render(a, color_mode="256") == fire.render(b, color_mode="256")


def test_render_none_mode_has_no_ansi():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="none")
    assert "\x1b[" not in frame
    for line in frame.split("\n"):
        assert len(line) == 24
    assert BLOCK in frame


def test_render_default_stays_truecolor():
    """Regression guard: the default renderer keeps emitting 24-bit
    truecolor escapes, never 256-mode ones."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    assert "\x1b[38;2;" in frame
    assert "\x1b[38;5;" not in frame
    assert BLOCK in frame


# --- simulation shape guards (kept from the CC-113 suite) -----------------------

def test_base_row_has_internal_gaps():
    """At 80x24 (seed 42, 30 ticks) the base row's span is a ragged band,
    not a solid one: within the leftmost..rightmost colored cells, at
    least 25% are blank."""
    grid = _grid(80, 24)
    base = grid[23]
    lit = [x for x, c in enumerate(base) if c]
    assert lit, "base row is empty: no flame at all"
    lo, hi = lit[0], lit[-1]
    span = hi - lo + 1
    blank = sum(1 for x in range(lo, hi + 1) if not base[x])
    assert blank / span >= 0.25, (
        f"only {100.0 * blank / span:.1f}% of the base span is blank; "
        f"at least 25% must be (span {span}, blank {blank})"
    )


def test_flame_does_not_touch_terminal_edges():
    """At 80x24 (seed 42, 30 ticks) the leftmost and rightmost columns
    are never lit: the flame never touches the terminal edges."""
    grid = _grid(80, 24)
    for y in range(24):
        assert not grid[y][0], f"leftmost column lit in row {y}"
        assert not grid[y][79], f"rightmost column lit in row {y}"
