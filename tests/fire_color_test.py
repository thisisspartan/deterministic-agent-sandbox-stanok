"""Reference tests for src/fire_color.py — multicolored terminal fire.

Contract (ticket TASK-STANOK-CC-105):
- deterministic seeded simulation (heat in [0,1], base-zone flag, smoke)
- multicolor palette (white-hot -> yellow -> orange -> red, blue base zone)
- pure ANSI renderer (24-bit truecolor, half-block chars, dims == grid)
- 4+ distinct color families in a rendered hot frame
- smoke particles rise above the flame top
"""
import re

import fire_color as fc

TRUECOLOR_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+) m")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ ]?[A-Za-z]")


def _strip_ansi(s):
    return ANSI_RE.sub("", s)


def _families(frame):
    """Classify every emitted truecolor RGB into a color family."""
    fam = set()
    for m in TRUECOLOR_RE.finditer(frame):
        r, g, b = (int(v) for v in m.groups())
        if b > r and b > g:
            fam.add("blue")
        if r > 200 and g >= 150 and b < 120:
            fam.add("yellow")
        if r > 200 and 80 <= g < 180 and b < 80:
            fam.add("orange")
        if r > 120 and g < 80 and b < 80:
            fam.add("red")
    return fam


def test_determinism_same_seed_identical_frames():
    a = fc.new_state(40, 20, seed=1234)
    b = fc.new_state(40, 20, seed=1234)
    for _ in range(30):
        a = fc.step(a)
        b = fc.step(b)
    assert fc.render(a) == fc.render(b)
    # a different seed must (with overwhelming probability) differ
    c = fc.new_state(40, 20, seed=9999)
    for _ in range(30):
        c = fc.step(c)
    assert fc.render(c) != fc.render(a)


def test_heat_field_range_and_changes_between_ticks():
    st = fc.new_state(40, 20, seed=7)
    first = None
    prev = None
    for _ in range(10):
        st = fc.step(st)
        for row in st.heat:
            for v in row:
                assert 0.0 <= v <= 1.0
        snapshot = [list(r) for r in st.heat]
        if first is None:
            first = snapshot
        if prev is not None:
            assert snapshot != prev  # field changes between two ticks
        prev = snapshot
    assert prev != first


def test_palette_components_and_hot_brighter_than_cool():
    hot = fc.palette(0.95, False)
    cool = fc.palette(0.2, False)
    assert hot is not None and cool is not None
    for c in (hot, cool):
        assert len(c) == 3
        for ch in c:
            assert 0 <= ch <= 255
    # white-hot core must be brighter (sum of RGB) than a cool edge
    assert sum(hot) > sum(cool)
    # zero heat -> None (empty cell)
    assert fc.palette(0.0, False) is None
    assert fc.palette(0.0, True) is None
    # sweep: every non-None output has in-range components
    for i in range(21):
        c = fc.palette(i / 20.0, False)
        if c is not None:
            assert all(0 <= ch <= 255 for ch in c)
    # palette is deterministic: same inputs -> same output
    assert fc.palette(0.5, False, 0.3) == fc.palette(0.5, False, 0.3)


def test_base_zone_cells_render_blue_dominant():
    st = fc.new_state(40, 20, seed=42)
    for _ in range(30):
        st = fc.step(st)
    flagged = [(y, x)
               for y in range(len(st.heat))
               for x in range(len(st.heat[y]))
               if st.base[y][x]]
    assert flagged, "a hot scene must have combustion-base cells"
    # base zone is the bottom rows of the flame body
    assert all(y < 3 for y, _ in flagged)
    for y, x in flagged:
        assert st.heat[y][x] > 0.0
        c = fc.palette(st.heat[y][x], True)
        assert c is not None
        assert c[2] > c[0]  # blue-dominant: b > r


def test_multicolor_frame_contains_four_color_families():
    st = fc.new_state(40, 20, seed=42)
    found = set()
    for _ in range(30):
        st = fc.step(st)
        found |= _families(fc.render(st))
    assert {"blue", "yellow", "orange", "red"} <= found, (
        "frame must show blue base, yellow, orange and red families, got %s"
        % sorted(found)
    )


def test_renderer_ansi_and_dimensions_match_grid():
    st = fc.new_state(30, 16, seed=5)
    for _ in range(20):
        st = fc.step(st)
    frame = fc.render(st)
    lines = frame.split("\n")
    assert len(lines) == st.grid_height  # frame height == grid height
    for line in lines:
        assert len(_strip_ansi(line)) == st.width  # frame width == grid width
    assert "\x1b[38;2;" in frame  # 24-bit truecolor escapes emitted
    assert "▀" in _strip_ansi(frame)  # half-block vertical resolution


def test_empty_field_renders_plain_spaces_no_escapes():
    st = fc.new_state(30, 16, seed=1)  # before any tick: zero heat, no smoke
    frame = fc.render(st)
    expected = "\n".join([" " * st.width] * st.grid_height)
    assert frame == expected
    assert "\x1b" not in frame


def test_smoke_particles_rise_above_flame_top():
    st = fc.new_state(40, 20, seed=42)
    seen = False
    for _ in range(80):
        st = fc.step(st)
        top = max((y for y in range(len(st.heat)) if max(st.heat[y]) > 0.15),
                  default=-1)
        if st.smoke and any(p[0] > top for p in st.smoke):
            seen = True
            break
    assert seen, "with a fixed seed some frame must show smoke above the flame top"


def test_smoke_particles_fade_out():
    st = fc.new_state(40, 20, seed=42)
    for _ in range(80):
        st = fc.step(st)
    # nothing lives forever: every particle has finite, positive life in (0, 1]
    for p in st.smoke:
        assert 0.0 < p[2] <= 1.0
    # and the particle list stays sparse
    assert len(st.smoke) < st.width
