"""Realism contract tests for src/fire.py (CC-109: multicolor fire).

Run via:  bash scripts/run.sh test tests/fire_realism_test.py

Decodes the truecolor RGBs emitted in rendered frames and checks that the
fire behaves like a *real* flame: multicolor with a blue combustion base,
a white-hot core, per-frame flicker, turbulent (non-static) tongues,
smoke rising above the flame top, and no color banding.
"""

import re

import fire  # src is on sys.path via pythonpath=src in run.sh

# One cell: either a truecolor half-block or a plain space.
CELL_RE = re.compile(r"(\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[0m▀| )")


def decode_frame(frame):
    """Rendered frame -> list of rows (top to bottom); each cell is an
    (r, g, b) tuple, or None for a blank cell."""
    grid = []
    for line in frame.split("\n"):
        row = []
        pos = 0
        for m in CELL_RE.finditer(line):
            assert m.start() == pos, "frame is not cell-aligned"
            pos = m.end()
            if m.group(2) is not None:
                row.append((int(m.group(2)), int(m.group(3)), int(m.group(4))))
            else:
                row.append(None)
        assert pos == len(line), "trailing garbage in line"
        grid.append(row)
    return grid


def flame_top_y(heat, threshold=0.45):
    """Topmost row (smallest y) that actually contains flame heat."""
    for y in range(len(heat)):
        if max(heat[y]) > threshold:
            return y
    return len(heat)


def tick_and_render(sim, n):
    """Return the frames rendered after each of the next n ticks."""
    frames = []
    for _ in range(n):
        sim.tick()
        frames.append(fire.render(sim))
    return frames


def color_family(rgb):
    r, g, b = rgb
    if b >= r and b >= g and b > 60:
        return "blue"
    if r >= 200 and g >= 160 and b <= 160:
        return "yellow"
    if r >= 200 and 60 <= g <= 160 and b <= 80:
        return "orange"
    if 120 <= r <= 200 and g <= 80 and b <= 50:
        return "red"
    return "other"


# --- multicolor ---------------------------------------------------------------

def test_frame_contains_four_color_families():
    sim = fire.FireSim(30, 16, seed=42)
    tick_and_render(sim, 15)
    grid = decode_frame(fire.render(sim))
    colors = [c for row in grid for c in row if c is not None]
    assert colors, "frame has no colored cells at all"
    families = {color_family(c) for c in colors}
    assert {"blue", "yellow", "orange", "red"} <= families, (
        f"expected blue base, yellow, orange and red families, got {families}"
    )


# --- blue combustion base ------------------------------------------------------

def test_base_zone_renders_blue_dominant():
    sim = fire.FireSim(24, 12, seed=42)
    tick_and_render(sim, 6)
    checked = 0
    grid = decode_frame(fire.render(sim))
    for y in range(12):
        for x in range(24):
            if sim.base[y][x] and sim.heat[y][x] >= 0.05:
                assert grid[y][x] is not None, "visible base cell rendered blank"
                r, g, b = grid[y][x]
                assert b > r, f"base cell ({x}, {y}) not blue-dominant: {(r, g, b)}"
                checked += 1
    assert checked > 0, "no visible base-zone cells to check"
    # The palette itself must be blue-dominant for any hot base heat.
    for heat in (0.1, 0.25, 0.5, 0.75, 0.95):
        rgb = fire.palette(heat, True)
        assert rgb is not None
        assert rgb[2] > rgb[0], f"palette({heat}, base) not blue-dominant: {rgb}"


# --- white-hot core -------------------------------------------------------------

def test_white_hot_core_brighter_than_cool_edge():
    sim = fire.FireSim(30, 16, seed=42)
    tick_and_render(sim, 15)
    heat = sim.heat
    # Hottest cell in the whole field.
    hy, hx = max(
        ((y, x) for y in range(16) for x in range(30)),
        key=lambda c: heat[c[0]][c[1]],
    )
    grid = decode_frame(fire.render(sim))
    hot = grid[hy][hx]
    assert hot is not None, "hottest cell rendered blank"
    # A cool edge cell: visible, mid-low heat, outside the base zone.
    cy = cx = None
    for y in range(16):
        for x in range(30):
            v = heat[y][x]
            if 0.15 <= v <= 0.30 and not sim.base[y][x]:
                cy, cx = y, x
                break
        if cy is not None:
            break
    assert cy is not None, "no cool edge cell in the flame"
    cool = grid[cy][cx]
    assert cool is not None
    assert sum(hot) > sum(cool), (
        f"hottest cell {(hy, hx)} sum={sum(hot)} must beat cool edge "
        f"{(cy, cx)} sum={sum(cool)}"
    )


# --- flicker ---------------------------------------------------------------------

def test_consecutive_frames_differ():
    sim = fire.FireSim(30, 16, seed=42)
    frames = tick_and_render(sim, 12)
    diffs = sum(1 for a, b in zip(frames, frames[1:]) if a != b)
    assert diffs >= 4, f"only {diffs}/11 consecutive frame pairs differ (no flicker)"


# --- turbulence --------------------------------------------------------------------

def test_flame_top_position_varies_across_frames():
    sim = fire.FireSim(30, 16, seed=42)
    tick_and_render(sim, 5)
    tops = set()
    for _ in range(10):
        sim.tick()
        heat = sim.heat
        ytop = flame_top_y(heat)
        if ytop < 16:
            row = heat[ytop]
            xtop = row.index(max(row))
            tops.add((ytop, xtop))
    assert len(tops) >= 3, (
        f"flame top only visited {len(tops)} positions over 10 frames: {tops}"
    )


# --- smoke -------------------------------------------------------------------------

def test_smoke_particles_rise_above_flame_top():
    sim = fire.FireSim(30, 16, seed=42)
    seen = False
    for _ in range(40):
        sim.tick()
        ytop = flame_top_y(sim.heat, threshold=0.40)
        if any(0 <= p.y < ytop for p in sim.smoke):
            seen = True
            break
    assert seen, "no smoke particle ever appears above the flame top"


# --- no color banding ---------------------------------------------------------------

def test_adjacent_equal_heat_cells_render_differently():
    rgb = fire.palette(0.5, False)
    assert rgb is not None
    c00 = fire.jittered_rgb(rgb, 3, 3)
    c10 = fire.jittered_rgb(rgb, 4, 3)
    c01 = fire.jittered_rgb(rgb, 3, 4)
    assert len(c00) == 3
    assert all(0 <= c <= 255 for c in c00)
    # Jitter is small...
    assert all(abs(a - b) <= 8 for a, b in zip(c00, rgb))
    # ...but adjacent cells with the same heat are not pixel-identical.
    assert c00 != c10, f"horizontally adjacent equal-heat cells identical: {c00}"
    assert c00 != c01, f"vertically adjacent equal-heat cells identical: {c00}"


# --- heat rises and decays ------------------------------------------------------------

def test_heat_rises_from_base():
    # Heat propagates upward one row per tick: after 4 ticks the flame
    # body spans rows 8..11 (base row 11), so row 8 must carry heat.
    sim = fire.FireSim(16, 12, seed=5)
    for _ in range(4):
        sim.tick()
    assert max(sim.heat[11]) > 0.5, "base row not hot after 4 ticks"
    assert max(sim.heat[8]) > 0.1, "heat did not rise 3 rows after 4 ticks"
    # ...and keeps climbing with more ticks.
    for _ in range(6):
        sim.tick()
    assert max(sim.heat[2]) > 0.05, "heat did not reach the upper rows"


def test_heat_decays_without_injection():
    sim = fire.FireSim(16, 12, seed=5, inject=False)
    sim.heat[6][8] = 0.9
    total0 = sum(sum(r) for r in sim.heat)
    for _ in range(3):
        sim.tick()
    assert sim.heat[6][8] < 0.5, "heat spike did not decay without injection"
    total1 = sum(sum(r) for r in sim.heat)
    assert total1 < total0, "total heat grew although no heat was injected"
