"""Calibrated contract oracle for src/water_render.py (SPEC-WATER-CONSOLE R1..R5).

Independence policy: expected colors/cell-plans are hand-computed from the
SPEC-pinned hex literals and the pinned mix/depth formulas transcribed in
this file; the production module is never used to derive an expectation.
States are LOCAL duck-typed objects; water_engine is not imported here or
in the subject.

Calibration: lab /tmp/oracle-lab-water, mutants MR1..MR7 — see specs/STATUS.md
tables. GREEN on reference, RED on targeted mutants.
"""
import ast
import inspect
import math
import re

import pytest

import water_render as r

# SPEC R1 host literals (signed source: SPEC-WATER-CONSOLE.md §3)
SPEC_HEX = {
    "P0": "#03121e", "P1": "#07294a", "P2": "#0d4f70", "P3": "#16799c",
    "P4": "#27a3c0", "P5": "#7fd4e0", "FOAM": "#e9f6fa", "GLINT": "#ffffff",
}
RESET = "\x1b[0m"
SEG_RE = re.compile(
    r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m(.)", re.DOTALL
)


def _hex(s):
    return tuple(int(s[i:i + 2], 16) for i in (1, 3, 5))


DEEP = [_hex(SPEC_HEX["P4"]), _hex(SPEC_HEX["P3"]), _hex(SPEC_HEX["P2"]),
        _hex(SPEC_HEX["P1"]), _hex(SPEC_HEX["P0"])]


def _mix(a, b, u):
    return tuple(math.floor(a_c + (b_c - a_c) * u + 0.5) for a_c, b_c in zip(a, b))


def _depth(rr):
    rr = min(rr, 8)
    s = min(3, int(rr / 8 * 4))
    u = rr / 8 * 4 - s
    return _mix(DEEP[s], DEEP[s + 1], u)


def _water(l):
    return _mix(_hex(SPEC_HEX["P4"]), _hex(SPEC_HEX["P5"]), max(0.0, min(1.0, l)))


def _cell(fg, bg, glyph):
    return "\x1b[38;2;%d;%d;%dm\x1b[48;2;%d;%d;%dm%s" % (
        fg[0], fg[1], fg[2], bg[0], bg[1], bg[2], glyph)


def _frame_exp(state, W, H):
    """Independent transcription of R3/R4: hand-computed cell plan."""
    rows = []
    for row in range(H):
        cells = []
        for x in range(W):
            if row == 0:
                cells.append(_cell(_hex(SPEC_HEX["P0"]), _hex(SPEC_HEX["P0"]), " "))
            elif row == 1:
                fg = _water(state.light[x])
                if state.glint[x]:
                    fg = _hex(SPEC_HEX["GLINT"])
                elif state.foam[x]:
                    fg = _hex(SPEC_HEX["FOAM"])
                f = (state.heights[x] + 1.0) - math.floor(state.heights[x] + 1.0)
                if f >= 0.5:
                    cells.append(_cell(fg, _depth(1), "▀"))
                else:
                    cells.append(_cell(fg, _hex(SPEC_HEX["P0"]), "▄"))
            else:
                c = _depth(row - 1)
                cells.append(_cell(c, c, " "))
        rows.append("".join(cells) + RESET)
    return "\n".join(rows)


class State:  # LOCAL duck-typed state — no water_engine import
    def __init__(self, heights, light, foam=None, glint=None):
        W = len(heights)
        self.heights = tuple(heights)
        self.light = tuple(light)
        self.foam = tuple(foam if foam is not None else [False] * W)
        self.glint = tuple(glint if glint is not None else [False] * W)


def _lum(c):  # WCAG sRGB relative luminance
    def lin(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * lin(c[0]) + 0.7152 * lin(c[1]) + 0.0722 * lin(c[2])


def test_R1_palette_literals_and_luminance_order():
    for name, hx in SPEC_HEX.items():
        assert getattr(r, name) == _hex(hx), f"palette {name} != {hx}"
    order = [_hex(SPEC_HEX[k]) for k in
             ("P0", "P1", "P2", "P3", "P4", "P5", "FOAM", "GLINT")]
    lums = [_lum(c) for c in order]
    assert all(lums[i] < lums[i + 1] for i in range(7))
    prod = [getattr(r, k) for k in ("P0", "P1", "P2", "P3", "P4", "P5", "FOAM", "GLINT")]
    plums = [_lum(c) for c in prod]
    assert all(plums[i] < plums[i + 1] for i in range(7))


def test_R2_depth_color_transcription_and_banding():
    for rr in range(0, 11):
        assert r.depth_color(rr) == _depth(rr), f"depth_color({rr})"
    prev = _depth(0)
    for rr in range(1, 9):
        cur = _depth(rr)
        assert all(abs(cur[ch] - prev[ch]) <= 32 for ch in range(3))
        assert cur != prev or rr > 8
        prev = cur


def test_R3_waterline_glyphs_and_overrides_exact():
    W, H = 12, 4
    # A: crest half (f=0.6 -> ▀), light 0 -> fg=P4, plain
    st_a = State([-0.4] * W, [0.0] * W)
    assert r.render_frame(st_a, W, H) == _frame_exp(st_a, W, H)
    # B: exact boundary f=0.5 -> ▀ and 0.49 -> ▄
    st_b = State([0.5] * W, [0.0] * W)
    fr_b = r.render_frame(st_b, W, H)
    assert fr_b == _frame_exp(st_b, W, H)
    row1_b = fr_b.split("\n")[1]
    assert row1_b.count("▀") == W
    st_c = State([0.49] * W, [1.0] * W)
    fr_c = r.render_frame(st_c, W, H)
    assert fr_c == _frame_exp(st_c, W, H)
    assert fr_c.split("\n")[1].count("▄") == W
    # C: FOAM at x=2, GLINT at x=5 overrides
    st_d = State([-0.4] * W, [0.5] * W,
                 foam=[x in (2, 5) for x in range(W)],
                 glint=[x == 5 for x in range(W)])
    assert r.render_frame(st_d, W, H) == _frame_exp(st_d, W, H)
    row1_d = r.render_frame(st_d, W, H).split("\n")[1]
    assert _cell(_hex(SPEC_HEX["FOAM"]), _depth(1), "▀") in row1_d
    assert _cell(_hex(SPEC_HEX["GLINT"]), _depth(1), "▀") in row1_d


def test_R3_adjacent_water_color_smoothness():
    W, H = 12, 4
    st = State([0.0] * W, [x / (W - 1) for x in range(W)])
    fr = r.render_frame(st, W, H)
    row1 = fr.split("\n")[1]
    cells = SEG_RE.findall(row1)
    assert len(cells) == W
    for i in range(W - 1):
        fg1 = tuple(int(cells[i][j]) for j in range(3))
        fg2 = tuple(int(cells[i + 1][j]) for j in range(3))
        assert all(abs(fg1[ch] - fg2[ch]) <= 40 for ch in range(3))


def test_R4_frame_structure_and_errors():
    W, H = 12, 5
    st = State([0.0] * W, [0.3] * W)
    fr = r.render_frame(st, W, H)
    assert not fr.endswith("\n")
    lines = fr.split("\n")
    assert len(lines) == H
    for line in lines:
        assert line.endswith(RESET) and line.count(RESET) == 1
        segs = list(SEG_RE.finditer(line))
        joined = "".join(s.group(0) for s in segs)
        assert joined + RESET == line, "line is exactly width cells + one reset"
        assert len(segs) == W
    with pytest.raises(ValueError):
        r.render_frame(st, 11, H)
    with pytest.raises(ValueError):
        r.render_frame(st, W, 3)
    # import boundary via AST (docstrings/comments are not imports)
    tree = ast.parse(inspect.getsource(r))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module)
    assert "water_engine" not in imported, "render must not import water_engine"


def test_R4_duck_typed_local_state_only():
    st = State([-0.2] * 12, [0.7] * 12)
    out = r.render_frame(st, 12, 4)
    assert out.count("38;2;") == 4 * 12


def test_R5_byte_determinism():
    st = State([-0.4] * 12, [0.25] * 12)
    assert r.render_frame(st, 12, 4) == r.render_frame(st, 12, 4)
