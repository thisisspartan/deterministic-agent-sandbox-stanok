"""Reference tests for src/fire_color.py (stdlib unittest, no external deps).

Contract (ticket STANOK-CC-079):
- deterministic simulation (seeded PRNG), heat field in [0, 1], changes per tick
- palette: RGB in 0..255, hot brighter than cool, zero heat -> None
- multicolor frame: blue base / yellow / orange / red families all present
- base-zone cells render blue-dominant (b > r)
- renderer: ANSI escapes present, frame dimensions match the grid,
  zero-heat frame is plain spaces with no escapes
- smoke particles appear above the flame top in some frame
- importing the module does NOT start the animation (main guard)
"""
import os
import random
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import fire_color  # noqa: E402  (import must not animate)

ANSI_TRUECOLOR_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
ANSI_ANY_RE = re.compile(r"\x1b\[[0-9;]*m")


def _decoded_colors(frame):
    return [(int(r), int(g), int(b)) for r, g, b in ANSI_TRUECOLOR_RE.findall(frame)]


def _family(r, g, b):
    if b > 200 and b > r + 20 and b > g:
        return "blue"
    if r > 200 and g > 170 and b < 120:
        return "yellow"
    if r > 200 and 90 <= g <= 170 and b < 100:
        return "orange"
    if 130 <= r <= 225 and g < 90 and b < 60:
        return "red"
    return None


def _flame_top(state):
    """Smallest grid row containing heat above threshold (flame top), or None."""
    for y in range(state["height"]):
        if any(v > 0.25 for v in state["heat"][y]):
            return y
    return None


def _cold_state(width, height):
    return {
        "seed": 0,
        "width": width,
        "height": height,
        "frame": 0,
        "rng": random.Random(0),
        "heat": [[0.0] * width for _ in range(height)],
        "base": [[False] * width for _ in range(height)],
        "turb": [0.0] * width,
        "particles": [],
        "jit": [[(0, 0, 0)] * width for _ in range(height)],
    }


class TestSimulation(unittest.TestCase):
    def test_determinism_same_seed_identical_frames(self):
        s1 = fire_color.new_state(seed=42, width=32, height=16)
        s2 = fire_color.new_state(seed=42, width=32, height=16)
        for _ in range(5):
            s1 = fire_color.step(s1)
            s2 = fire_color.step(s2)
            self.assertEqual(fire_color.render(s1), fire_color.render(s2))

    def test_heat_field_bounds_and_changes_between_ticks(self):
        s = fire_color.new_state(seed=1, width=32, height=16)
        for row in s["heat"]:
            for v in row:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)
        first = [row[:] for row in s["heat"]]
        s = fire_color.step(s)
        second = [row[:] for row in s["heat"]]
        self.assertNotEqual(first, second, "heat field must change between ticks")
        for row in second:
            for v in row:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)

    def test_smoke_particles_appear_above_flame_top(self):
        s = fire_color.new_state(seed=11, width=32, height=16)
        seen = False
        for _ in range(40):
            top = _flame_top(s)
            if top is not None and any(p["y"] < top for p in s["particles"]):
                seen = True
                break
            s = fire_color.step(s)
        self.assertTrue(seen, "no smoke particle ever rendered above the flame top")


class TestPalette(unittest.TestCase):
    def test_components_in_range(self):
        for heat in (0.1, 0.15, 0.3, 0.5, 0.7, 0.9, 1.0):
            c = fire_color.palette(heat, False)
            self.assertIsNotNone(c)
            self.assertEqual(len(c), 3)
            for ch in c:
                self.assertGreaterEqual(ch, 0)
                self.assertLessEqual(ch, 255)

    def test_zero_heat_is_empty(self):
        self.assertIsNone(fire_color.palette(0.0, False))
        self.assertIsNone(fire_color.palette(0.0, True))

    def test_hot_core_brighter_than_cool_edge(self):
        def brightness(rgb):
            return sum(rgb)
        self.assertGreater(
            brightness(fire_color.palette(0.95, False)),
            brightness(fire_color.palette(0.2, False)),
        )

    def test_base_zone_blue_dominant(self):
        s = fire_color.new_state(seed=5, width=32, height=16)
        s = fire_color.step(s)
        found = False
        for y in range(s["height"]):
            for x in range(s["width"]):
                if s["base"][y][x]:
                    heat = s["heat"][y][x]
                    self.assertGreater(heat, 0.0)
                    c = fire_color.palette(heat, True)
                    self.assertIsNotNone(c)
                    self.assertGreater(c[2], c[0], "base cell must be blue-dominant")
                    found = True
        self.assertTrue(found, "no base-zone cells found in a burning scene")
        # direct palette check across the whole base gradient
        for heat in (0.2, 0.5, 0.8, 1.0):
            r, g, b = fire_color.palette(heat, True)
            self.assertGreater(b, r)


class TestRenderer(unittest.TestCase):
    def test_frame_has_ansi_and_dimensions_match_grid(self):
        s = fire_color.new_state(seed=9, width=24, height=12)
        frame = fire_color.render(s)
        self.assertIsInstance(frame, str)
        self.assertIn("\x1b[38;2;", frame)
        lines = frame.split("\n")
        self.assertEqual(len(lines), 6, "frame rows must match grid height/2")
        for line in lines:
            self.assertEqual(len(ANSI_ANY_RE.sub("", line)), 24)

    def test_cold_grid_is_plain_spaces_no_escapes(self):
        frame = fire_color.render(_cold_state(24, 12))
        lines = frame.split("\n")
        self.assertEqual(len(lines), 6)
        for line in lines:
            self.assertEqual(line, " " * 24)
        self.assertNotIn("\x1b", frame)

    def test_multicolor_families_in_hot_scene(self):
        s = fire_color.new_state(seed=42, width=32, height=16)
        found = set()
        for _ in range(30):
            for (r, g, b) in _decoded_colors(fire_color.render(s)):
                fam = _family(r, g, b)
                if fam:
                    found.add(fam)
            s = fire_color.step(s)
        self.assertTrue(
            {"blue", "yellow", "orange", "red"} <= found,
            "missing color families, saw: %s" % sorted(found),
        )


if __name__ == "__main__":
    unittest.main()
