#!/usr/bin/env python3
"""Reference tests for src/fire_color.py (ticket TASK-STANOK-CC-079).

Contract asserted here:
  - determinism (same seed -> identical frame string)
  - heat field in [0, 1] and evolving between ticks
  - palette: RGB in 0..255, hot brighter than cool, zero heat -> None
  - multicolor frame: >= 4 distinct color families (blue/yellow/orange/red)
  - blue base: base-zone cells render blue-dominant (b > r)
  - renderer: ANSI escapes present, frame dimensions match the grid
  - smoke: deterministic particles appear above the flame top in some frame
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from fire_color import Fire, palette, render_frame  # noqa: E402

ANSI_RGB = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m")
ALL_ESC = re.compile(r"\x1b\[[0-9;]*m")


def _decoded_colors(frame):
    return [tuple(int(c) for c in m) for m in ANSI_RGB.findall(frame)]


def _family(rgb):
    r, g, b = rgb
    if b >= r and b > g and b >= 200:
        return "blue"
    if r >= 200 and g >= 200 and b >= 200:
        return "white"
    if r >= 240 and 170 <= g <= 235 and b <= 130:
        return "yellow"
    if r >= 240 and 90 <= g < 170 and b <= 120:
        return "orange"
    if 120 <= r < 240 and g < 110 and b < 100:
        return "red"
    return None


class FireColorTest(unittest.TestCase):
    def _warmed(self, seed, ticks=40):
        sim = Fire(seed=seed)
        for _ in range(ticks):
            sim.tick()
        return sim

    def test_determinism_same_seed_identical_frame(self):
        a = render_frame(self._warmed(seed=7))
        b = render_frame(self._warmed(seed=7))
        self.assertEqual(a, b)
        # and the frame is not empty
        self.assertIn("\x1b[38;2;", a)

    def test_heat_field_bounded_and_changing(self):
        sim = Fire(seed=1)
        for _ in range(10):
            sim.tick()
        first = [row[:] for row in sim.heat]
        sim.tick()
        for row in sim.heat:
            for v in row:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 1.0)
        self.assertNotEqual(first, sim.heat)

    def test_palette_range_brightness_and_zero(self):
        hot = palette(1.0, False)
        cool = palette(0.3, False)
        for c in (hot, cool):
            self.assertIsNotNone(c)
            self.assertEqual(len(c), 3)
            for ch in c:
                self.assertGreaterEqual(ch, 0)
                self.assertLessEqual(ch, 255)
        self.assertGreater(sum(hot), sum(cool))
        self.assertIsNone(palette(0.0, False))
        self.assertIsNone(palette(0.0, True))

    def test_multicolor_frame_has_four_families(self):
        sim = self._warmed(seed=9)
        frame = render_frame(sim)
        families = {f for f in (_family(c) for c in _decoded_colors(frame)) if f}
        self.assertGreaterEqual(len(families), 4)
        self.assertTrue({"blue", "yellow", "orange", "red"} <= families,
                        msg="frame lacks a color family: %s" % families)

    def test_blue_base_zone(self):
        sim = self._warmed(seed=11)
        n = 0
        for y in range(sim.height):
            for x in range(sim.width):
                if sim.base[y][x]:
                    n += 1
                    r, g, b = palette(sim.heat[y][x], True)
                    self.assertIsNotNone(r)
                    self.assertGreater(b, r, "base cell must be blue-dominant")
        self.assertGreater(n, 0, "no base-zone cells found")

    def test_renderer_frame_dimensions_and_ansi(self):
        sim = Fire(seed=3)
        for _ in range(20):
            sim.tick()
        frame = render_frame(sim)
        self.assertIn("\x1b[", frame)
        lines = frame.split("\n")
        self.assertEqual(len(lines), sim.height // 2)
        for line in lines:
            self.assertEqual(len(ALL_ESC.sub("", line)), sim.width)

    def test_smoke_rises_above_flame_top(self):
        sim = Fire(seed=5)
        found = False
        for _ in range(80):
            sim.tick()
            if sim.smoke:
                top = None
                for y in range(sim.height):
                    if any(v > 0.5 for v in sim.heat[y]):
                        top = y
                        break
                if top is None:
                    top = sim.height
                if any(p["y"] < top for p in sim.smoke):
                    found = True
                    break
        self.assertTrue(found, "no smoke particle ever appeared above the flame top")


if __name__ == "__main__":
    unittest.main()
