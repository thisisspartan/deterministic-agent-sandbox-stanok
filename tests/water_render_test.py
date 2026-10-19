"""CC-300 — water_render reference tests (pins R1..R5).

The contract (docs/water_render.md): a pure renderer from a duck-typed frame
state (heights/light/foam/glint) to an ANSI-truecolor frame string.
water_engine is NOT imported here or in the subject; every expected color and
every expected cell is an in-test transcription of the SPEC-pinned hex
literals and of the pinned mix/depth formulas — the production module is
never used to derive an expectation.

Fixtures are defined inside this file (no conftest.py).
"""

import ast
import copy
import dataclasses
import inspect
import math
import re

import pytest

import water_render as r  # pythonpath=src

# --- SPEC-pinned palette (R1 host literals) --------------------------------

SPEC_HEX = {
    "P0": "#03121e", "P1": "#07294a", "P2": "#0d4f70", "P3": "#16799c",
    "P4": "#27a3c0", "P5": "#7fd4e0", "FOAM": "#e9f6fa", "GLINT": "#ffffff",
}
STOP_ORDER = ("P0", "P1", "P2", "P3", "P4", "P5", "FOAM", "GLINT")


def _hex(literal: str) -> tuple:
    return tuple(int(literal[i:i + 2], 16) for i in (1, 3, 5))


SPEC = {name: _hex(literal) for name, literal in SPEC_HEX.items()}

RESET = "\x1b[0m"
TOP = "▀"  # ▀
BOTTOM = "▄"  # ▄
SPACE = " "
SEG_RE = re.compile(
    r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m(.)", re.DOTALL
)

MIN_WIDTH, MIN_HEIGHT = 12, 4
W, H = 12, 4


# --- in-test transcription of the pinned formulas --------------------------

def _mix(a, b, u):
    return tuple(math.floor(a_c + (b_c - a_c) * u + 0.5) for a_c, b_c in zip(a, b))


_DEEP = [SPEC["P4"], SPEC["P3"], SPEC["P2"], SPEC["P1"], SPEC["P0"]]


def _depth(rr):
    rr = min(rr, 8)
    s = min(3, int(rr / 8 * 4))
    u = rr / 8 * 4 - s
    return _mix(_DEEP[s], _DEEP[s + 1], u)


def _water(l):
    return _mix(SPEC["P4"], SPEC["P5"], max(0.0, min(1.0, l)))


def _cell(fg, bg, glyph):
    return "\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm%s" % (
        fg[0], fg[1], fg[2], bg[0], bg[1], bg[2], glyph)


def _frame_exp(state, width, height):
    """Independent transcription of R3/R4: the expected cell plan."""
    rows = []
    for row in range(height):
        cells = []
        for x in range(width):
            if row == 0:
                cells.append(_cell(SPEC["P0"], SPEC["P0"], SPACE))
            elif row == 1:
                fg = _water(state.light[x])
                if state.glint[x]:
                    fg = SPEC["GLINT"]
                elif state.foam[x]:
                    fg = SPEC["FOAM"]
                h = state.heights[x] + 1.0
                if h - math.floor(h) >= 0.5:
                    cells.append(_cell(fg, _depth(1), TOP))
                else:
                    cells.append(_cell(fg, SPEC["P0"], BOTTOM))
            else:
                c = _depth(row - 1)
                cells.append(_cell(c, c, SPACE))
        rows.append("".join(cells) + RESET)
    return "\n".join(rows)


def _lum(c):  # WCAG sRGB relative luminance
    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


# --- local duck-typed states (no water_engine anywhere) -------------------


@dataclasses.dataclass
class FakeState:
    heights: tuple
    light: tuple
    foam: tuple = ()
    glint: tuple = ()

    def __post_init__(self):
        self.heights = tuple(self.heights)
        self.light = tuple(self.light)
        width = len(self.heights)
        self.foam = tuple(self.foam) if self.foam else (False,) * width
        self.glint = tuple(self.glint) if self.glint else (False,) * width


def _state(heights, light, foam=None, glint=None):
    width = len(heights)
    return FakeState(
        heights=heights,
        light=light,
        foam=(False,) * width if foam is None else foam,
        glint=(False,) * width if glint is None else glint,
    )


def _flat(width=W, height=0.0, light=0.0):
    return _state([height] * width, [light] * width)


def _ramp(width, lo=0.0, hi=1.0):
    return _state([0.0] * width, [lo + (hi - lo) * x / (width - 1) for x in range(width)])


def _cells(line):
    """Strict parse of one styled line into (fg, bg, glyph) cells (R4 wire format)."""
    assert line.endswith(RESET), "line must end with the reset"
    assert line.count(RESET) == 1, "exactly one reset per line"
    body = line[: -len(RESET)]
    out = []
    pos = 0
    while pos < len(body):
        m = SEG_RE.match(body, pos)
        assert m is not None, f"malformed segment at {pos}: {body[pos:pos + 24]!r}"
        out.append(
            (
                (int(m.group(1)), int(m.group(2)), int(m.group(3))),
                (int(m.group(4)), int(m.group(5)), int(m.group(6))),
                m.group(7),
            )
        )
        pos = m.end()
    return out


def _rows(frame):
    assert isinstance(frame, str)
    assert not frame.endswith("\n"), "no trailing newline"
    return [_cells(line) for line in frame.split("\n")]


def _module_color_fields(module):
    """Every public rgb-tuple field of the module (the palette stops)."""
    out = {}
    for name, value in vars(module).items():
        if name.startswith("_"):
            continue
        if (
            isinstance(value, tuple)
            and len(value) == 3
            and all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)
        ):
            out[name] = value
    return out


# 1. R1 — palette stops and luminance order ---------------------------------

def test_palette_stops_are_the_pinned_rgb_tuples():
    for name in STOP_ORDER:
        assert getattr(r, name) == SPEC[name], f"palette stop {name} != {SPEC_HEX[name]}"


def test_palette_has_exactly_eight_stops():
    fields = _module_color_fields(r)
    assert len(fields) == 8, f"expected exactly 8 palette stops, got {sorted(fields)}"
    assert fields == SPEC


def test_palette_luminance_strictly_increases_in_stop_order():
    pinned = [_lum(SPEC[name]) for name in STOP_ORDER]
    assert all(pinned[i] < pinned[i + 1] for i in range(len(pinned) - 1)), pinned
    produced = [_lum(getattr(r, name)) for name in STOP_ORDER]
    assert all(produced[i] < produced[i + 1] for i in range(len(produced) - 1)), produced


def test_palette_hex_literals_are_host_literals():
    source = inspect.getsource(r)
    for name in STOP_ORDER:
        assert SPEC_HEX[name] in source, f"{name} hex literal {SPEC_HEX[name]} not in the source"


# 2. R2 — depth colors ------------------------------------------------------

@pytest.mark.parametrize("rr", list(range(0, 13)))
def test_depth_color_matches_the_pinned_formula(rr):
    assert r.depth_color(rr) == _depth(rr), f"depth_color({rr})"


def test_depth_color_darkens_monotonically_from_p4_to_p0():
    assert r.depth_color(0) == SPEC["P4"]
    prev = _depth(0)
    prev_lum = _lum(prev)
    for rr in range(1, 9):
        cur = r.depth_color(rr)
        assert all(cur[ch] < prev[ch] for ch in range(3)), f"depth {rr} is not darker than {rr - 1}"
        assert _lum(cur) < prev_lum
        prev, prev_lum = cur, _lum(cur)
    assert r.depth_color(8) == SPEC["P0"]


def test_depth_color_clamps_at_p0_for_r_over_eight():
    for rr in (8, 9, 10, 11, 16, 40, 1000):
        assert r.depth_color(rr) == SPEC["P0"], f"depth_color({rr}) must clamp to P0"


def test_depth_color_neighbour_rows_are_within_32_per_channel():
    prev = r.depth_color(0)
    for rr in range(1, 9):
        cur = r.depth_color(rr)
        assert all(abs(cur[ch] - prev[ch]) <= 32 for ch in range(3)), f"banding at depth {rr}"
        prev = cur


# 3. R3 — frame content -----------------------------------------------------

def test_sky_row_is_space_in_p0():
    rows = _rows(r.render_frame(_flat(), W, H))
    assert rows[0] == [(SPEC["P0"], SPEC["P0"], SPACE)] * W


def test_depth_rows_are_space_in_the_depth_color():
    st = _flat()
    rows = _rows(r.render_frame(st, W, 12))
    for row in range(2, 12):
        c = _depth(row - 1)
        assert rows[row] == [(c, c, SPACE)] * W, f"row {row}"


@pytest.mark.parametrize(
    "height_value,glyph",
    [
        (-0.4, TOP),   # f = 0.60 -> upper half
        (-0.5, TOP),   # f = 0.50 -> boundary belongs to the upper half
        (0.5, TOP),    # f = 0.50 (1.5 - 1) -> boundary
        (0.9, TOP),    # f = 0.90
        (0.0, BOTTOM),  # f = 0.00
        (0.49, BOTTOM),  # f = 0.49
        (-0.51, BOTTOM),  # f = 0.49
        (-0.9, BOTTOM),  # f = 0.10
    ],
)
def test_waterline_glyph_follows_frac_height_plus_one(height_value, glyph):
    st = _flat(light=0.5, height=height_value)
    waterline = _rows(r.render_frame(st, W, H))[1]
    assert [cell[2] for cell in waterline] == [glyph] * W


def test_waterline_background_is_depth1_under_the_upper_half_and_p0_under_the_lower():
    crest = _flat(height=-0.4)
    trough = _flat(height=0.0)
    for st, bg in ((crest, _depth(1)), (trough, SPEC["P0"])):
        for row in _rows(r.render_frame(st, W, H))[1:2]:
            assert [cell[1] for cell in row] == [bg] * W


def test_waterline_foreground_is_water_color_of_light():
    st = _ramp(W, 0.0, 1.0)
    waterline = _rows(r.render_frame(st, W, H))[1]
    assert [cell[0] for cell in waterline] == [_water(st.light[x]) for x in range(W)]


def test_water_color_is_the_pinned_mix_and_clamps_light():
    for l in (0.0, 0.25, 0.5, 0.75, 1.0, -3.0, 4.0):
        assert r.water_color(l) == _water(l), f"water_color({l})"
    assert r.water_color(-3.0) == SPEC["P4"]
    assert r.water_color(4.0) == SPEC["P5"]


def test_foam_overrides_the_waterline_foreground():
    foam = [x == 3 for x in range(W)]
    st = _state([-0.4] * W, [0.5] * W, foam=foam)
    waterline = _rows(r.render_frame(st, W, H))[1]
    assert waterline[3][0] == SPEC["FOAM"]
    assert waterline[3][2] == TOP
    for x in range(W):
        if x != 3:
            assert waterline[x][0] == _water(0.5)


def test_glint_overrides_foam_and_water():
    foam = [x in (2, 5) for x in range(W)]
    glint = [x == 5 for x in range(W)]
    st = _state([-0.4] * W, [0.5] * W, foam=foam, glint=glint)
    waterline = _rows(r.render_frame(st, W, H))[1]
    assert waterline[5][0] == SPEC["GLINT"], "glint must win over foam"
    assert waterline[2][0] == SPEC["FOAM"]
    # glint without foam is still GLINT
    st2 = _state([-0.4] * W, [0.5] * W, glint=[x == 7 for x in range(W)])
    assert _rows(r.render_frame(st2, W, H))[1][7][0] == SPEC["GLINT"]


def test_overrides_never_change_the_background_or_the_glyph():
    st = _state([0.0] * W, [0.5] * W, foam=[x == 1 for x in range(W)],
                glint=[x == 1 for x in range(W)])
    waterline = _rows(r.render_frame(st, W, H))[1]
    assert waterline[1] == (SPEC["GLINT"], SPEC["P0"], BOTTOM)


def test_full_frame_matches_the_transcribed_plan():
    states = [
        _flat(),
        _flat(height=-0.4, light=0.0),
        _flat(height=0.5, light=0.0),  # exact boundary f = 0.5
        _flat(height=0.49, light=1.0),
        _ramp(W, 0.0, 1.0),
        _state([0.4 * math.sin(2 * math.pi * x / W) for x in range(W)],
               [0.5 + 0.4 * math.cos(2 * math.pi * x / W) for x in range(W)]),
        _state([-0.4] * W, [0.5] * W,
               foam=[x in (2, 5) for x in range(W)], glint=[x == 5 for x in range(W)]),
    ]
    for st in states:
        assert r.render_frame(st, W, H) == _frame_exp(st, W, H)


def test_adjacent_water_colors_are_within_40_per_channel_on_a_flat_surface():
    for width in (12, 24, 48):
        st = _ramp(width, 0.0, 1.0)
        waterline = _rows(r.render_frame(st, width, H))[1]
        for x in range(width - 1):
            a, b = waterline[x][0], waterline[x + 1][0]
            assert all(abs(a[ch] - b[ch]) <= 40 for ch in range(3)), f"band at x={x}, width={width}"
    ramp = [x / 23 for x in range(24)]
    for i in range(len(ramp) - 1):
        a, b = r.water_color(ramp[i]), r.water_color(ramp[i + 1])
        assert all(abs(a[ch] - b[ch]) <= 40 for ch in range(3))


# 4. R4 — frame structure and wire format -----------------------------------

def test_frame_has_exactly_height_lines_of_exactly_width_cells():
    for width, height in ((12, 4), (12, 5), (20, 9), (40, 4)):
        st = _state([0.0] * width, [0.3] * width)
        frame = r.render_frame(st, width, height)
        lines = frame.split("\n")
        assert len(lines) == height, f"{width}x{height}: {len(lines)} lines"
        for n, line in enumerate(lines):
            assert len(_cells(line)) == width, f"line {n} is not width cells"
            assert line.count("38;2;") == width and line.count("48;2;") == width


def test_frame_has_no_trailing_newline_and_one_reset_at_the_end_of_each_line():
    frame = r.render_frame(_flat(), W, 6)
    assert not frame.endswith("\n")
    lines = frame.split("\n")
    assert len(lines) == 6
    for n, line in enumerate(lines):
        assert line.endswith(RESET), f"line {n} does not end with the reset"
        assert line.count(RESET) == 1, f"line {n} has an extra reset inside"
        # every escape sequence in the line: two SGR codes per cell, plus the reset
        assert line.count("\x1b[") == 2 * W + 1, "no escape code beyond the cells and the reset"


def test_line_body_is_a_complete_concatenation_of_sgr_cells():
    frame = r.render_frame(_flat(height=-0.4, light=0.25), W, H)
    for line in frame.split("\n"):
        body = "".join(
            m.group(0) for m in SEG_RE.finditer(line)
        )
        assert body + RESET == line, "no stray bytes between the cells"


@pytest.mark.parametrize("width", [11, 0, -1, -100])
def test_width_below_twelve_raises_value_error(width):
    with pytest.raises(ValueError):
        r.render_frame(_flat(width=max(width, 1)), width, H)


@pytest.mark.parametrize("height", [3, 0, -1, -100])
def test_height_below_four_raises_value_error(height):
    with pytest.raises(ValueError):
        r.render_frame(_flat(), W, height)


def test_minimum_accepted_size_is_twelve_by_four():
    frame = r.render_frame(_flat(), 12, 4)
    assert len(frame.split("\n")) == 4


def test_render_reads_the_state_duck_typed_and_never_imports_the_engine():
    st = _state([-0.2] * 12, [0.7] * 12)
    out = r.render_frame(st, 12, 4)
    assert out.count("38;2;") == 4 * 12
    tree = ast.parse(inspect.getsource(r))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert "water_engine" not in imported, "render must not import water_engine"
    assert not any(str(name).startswith("water_engine") for name in imported)


def test_render_does_not_mutate_the_state():
    st = _state([0.4 * math.sin(x) for x in range(W)],
                [0.5 + 0.4 * math.cos(x) for x in range(W)],
                foam=[x % 3 == 0 for x in range(W)], glint=[x % 5 == 0 for x in range(W)])
    snapshot = copy.deepcopy(st)
    r.render_frame(st, W, H)
    assert st == snapshot


# 5. R5 — byte determinism --------------------------------------------------

def test_two_calls_on_the_same_state_are_byte_identical():
    st = _state([-0.4] * W, [0.25] * W, foam=[x == 4 for x in range(W)])
    assert r.render_frame(st, W, H) == r.render_frame(st, W, H)


def test_two_equal_states_give_identical_bytes():
    a = _state([-0.4] * W, [0.25] * W, foam=[x == 4 for x in range(W)])
    b = _state([-0.4] * W, [0.25] * W, foam=[x == 4 for x in range(W)])
    assert r.render_frame(a, W, H) == r.render_frame(b, W, H)
    assert r.depth_color(3) == r.depth_color(3)
    assert r.water_color(0.37) == r.water_color(0.37)
