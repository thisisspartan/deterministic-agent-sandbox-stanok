"""Reference tests for src/fire.py — multicolored terminal fire.

Run via: bash scripts/run.sh test tests/fire_test.py
"""
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import fire  # noqa: E402

ANSI_RE = re.compile(r"\x1b\[38;2;(\d{1,3});(\d{1,3});(\d{1,3}) m")

W, H, SEED = 40, 30, 7


def decoded_colors(frame):
    """All distinct (r, g, b) emitted by a rendered frame."""
    return {tuple(map(int, m)) for m in ANSI_RE.findall(frame)}


def color_family_count(rgbs):
    """How many of the four required color families are present."""
    n = 0
    if any(b > r for r, g, b in rgbs):
        n += 1  # blue combustion base
    if any(r >= 200 and g >= 160 and b < 140 for r, g, b in rgbs):
        n += 1  # yellow
    if any(r >= 200 and g < 160 for r, g, b in rgbs):
        n += 1  # orange
    if any(140 <= r < 200 and g < 80 for r, g, b in rgbs):
        n += 1  # red / red-orange
    return n


class FireTest(unittest.TestCase):
    def test_determinism_same_seed_identical_frames(self):
        f1, f2 = fire.Fire(W, H, SEED), fire.Fire(W, H, SEED)
        for _ in range(20):
            f1.step()
            f2.step()
        self.assertEqual(f1.frame(), f2.frame())

    def test_heat_field_bounds_and_changes(self):
        f = fire.Fire(W, H, SEED)
        f.step()
        flat = [v for row in f.grid for v in row]
        self.assertTrue(all(0.0 <= v <= 1.0 for v in flat))
        s1 = list(map(list, f.grid))
        f.step()
        s2 = list(map(list, f.grid))
        self.assertNotEqual(s1, s2)
        # also non-trivially hot somewhere
        self.assertTrue(max(flat) > 0.5)

    def test_palette_component_range_and_ordering(self):
        hot = fire.palette(0.95, False)
        cool = fire.palette(0.3, False)
        for c in (hot, cool):
            self.assertIsNotNone(c)
            for ch in c:
                self.assertTrue(0 <= ch <= 255)
        self.assertGreater(sum(hot), sum(cool))  # hot core brighter than cool edge
        self.assertIsNone(fire.palette(0.0, False))
        self.assertIsNone(fire.palette(0.0, True))

    def test_rendered_frame_multicolor(self):
        f = fire.Fire(W, H, SEED)
        rgbs = set()
        for _ in range(30):
            f.step()
            rgbs |= decoded_colors(f.frame())
        self.assertGreaterEqual(color_family_count(rgbs), 4)

    def test_blue_base_zone_blue_dominant(self):
        f = fire.Fire(W, H, SEED)
        for _ in range(15):
            f.step()
            for y in range(H):
                for x in range(W):
                    if f.base[y][x] and f.grid[y][x] > 0.0:
                        r, g, b = fire.palette(f.grid[y][x] * f.flicker, True)
                        self.assertIsNotNone(r)
                        self.assertGreater(b, r)
            if any(any(f.base[y]) for y in range(H)):
                break
        self.assertTrue(any(any(row) for row in f.base))

    def test_renderer_ansi_and_dimensions(self):
        f = fire.Fire(W, H, SEED)
        f.step()
        frame = f.frame()
        self.assertIn("\x1b[38;2;", frame)
        # display dimensions (ANSI codes are cell attributes, not columns)
        plain = re.sub(r"\x1b\[[0-9;]+ ?m", "", frame)
        lines = plain.split("\n")
        self.assertEqual(len(lines), H)
        self.assertTrue(all(len(line) == W for line in lines))

    def test_smoke_particles_above_flame_top(self):
        f = fire.Fire(W, H, SEED)
        seen = False
        for _ in range(30):
            f.step()
            heat_top = min(
                (y for y in range(H) if any(v > 0.0 for v in f.grid[y])),
                default=None,
            )
            if heat_top is not None and any(
                p["y"] < heat_top for p in f.particles
            ):
                seen = True
                break
        self.assertTrue(seen)


if __name__ == "__main__":
    unittest.main()
