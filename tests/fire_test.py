"""Reference tests for the terminal fire (max-propagation simulation).

Stdlib unittest. Covers the ticket contract:
  - determinism (same seed -> identical rendered frame)
  - heat field (values in [0, 1]; changes between ticks)
  - palette (0-255 channels; hot brighter than cool; zero heat -> None)
  - multicolor frame (>= 4 color families: blue, yellow, orange, red)
  - blue-dominant combustion base zone (b > r)
  - renderer (ANSI escapes present; frame dimensions match the grid)
  - smoke (fixed seed: particles above the flame top in some frame)
  - headless load (module import / main() without animation)
"""

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import fire  # noqa: E402

_TRUECOLOR_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+) m")
_ANY_ESCAPE_RE = re.compile(r"\x1b\[[0-9; ]*[A-Za-z]")


def _rgb_colors(frame):
    """Decode every emitted 24-bit truecolor RGB triple from a frame."""
    return [(int(r), int(g), int(b)) for r, g, b in _TRUECOLOR_RE.findall(frame)]


def _families(frame):
    """Classify decoded colors into color families."""
    fams = set()
    for r, g, b in _rgb_colors(frame):
        if b > r + 40:
            fams.add("blue")
        elif r >= 230 and g >= 180 and b <= 110:
            fams.add("yellow")
        elif r >= 230 and 60 <= g <= 185 and b <= 40:
            fams.add("orange")
        elif 100 <= r <= 245 and 5 <= g <= 100 and b <= 50:
            fams.add("red")
    return fams


def _hot_frame(seed=1, ticks=40):
    """Run a default-size simulation to a bright steady state and render it."""
    sim = fire.FireSimulation(seed=seed)
    for _ in range(ticks):
        sim.tick()
    frame = fire.render(sim.heat, sim.smoke, sim.width, sim.height,
                        sim.base_rows, seed=sim.seed)
    return sim, frame


class TestDeterminism(unittest.TestCase):
    def test_same_seed_same_frame(self):
        a = fire.FireSimulation(seed=42)
        b = fire.FireSimulation(seed=42)
        for _ in range(12):
            a.tick()
            b.tick()
        self.assertEqual(a.heat, b.heat)
        fa = fire.render(a.heat, a.smoke, a.width, a.height, a.base_rows, seed=a.seed)
        fb = fire.render(b.heat, b.smoke, b.width, b.height, b.base_rows, seed=b.seed)
        self.assertEqual(fa, fb)


class TestHeatField(unittest.TestCase):
    def test_values_in_unit_range_and_field_changes(self):
        sim = fire.FireSimulation(width=48, height=28, seed=7)
        for _ in range(15):
            sim.tick()
            for row in sim.heat:
                for v in row:
                    self.assertGreaterEqual(v, 0.0)
                    self.assertLessEqual(v, 1.0)
        prev = [row[:] for row in sim.heat]
        sim.tick()
        self.assertNotEqual(sim.heat, prev, "field must change between ticks")


class TestPalette(unittest.TestCase):
    def test_components_in_range(self):
        for heat in (1.0, 0.95, 0.9, 0.75, 0.6, 0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.06, 0.05):
            for seed in (0, 1, 999):
                color = fire.palette(heat, False, seed)
                self.assertIsNotNone(color)
                self.assertEqual(len(color), 3)
                for ch in color:
                    self.assertGreaterEqual(ch, 0)
                    self.assertLessEqual(ch, 255)

    def test_hot_core_brighter_than_cool_edge(self):
        core = fire.palette(0.95)
        edge = fire.palette(0.2)
        self.assertGreater(sum(core), sum(edge))

    def test_zero_heat_is_none(self):
        self.assertIsNone(fire.palette(0.0))
        self.assertIsNone(fire.palette(0.0, True))


class TestMulticolor(unittest.TestCase):
    def test_frame_has_at_least_four_color_families(self):
        _, frame = _hot_frame()
        fams = _families(frame)
        for needed in ("blue", "yellow", "orange", "red"):
            self.assertIn(needed, fams,
                          "missing family %r; saw %s" % (needed, sorted(fams)))
        self.assertGreaterEqual(len(fams), 4)


class TestBlueBase(unittest.TestCase):
    def test_base_zone_cells_are_blue_dominant(self):
        sim, frame = _hot_frame()
        lines = frame.split("\n")
        base_top = sim.height - sim.base_rows
        found = 0
        for y in range(base_top, sim.height):
            for r, g, b in _rgb_colors(lines[y]):
                self.assertGreater(b, r, "base zone must be blue-dominant")
                found += 1
        self.assertGreater(found, 0, "expected lit base-zone cells")


class TestRenderer(unittest.TestCase):
    def test_ansi_escapes_and_dimensions_match_grid(self):
        sim = fire.FireSimulation(width=40, height=22, seed=3)
        for _ in range(20):
            sim.tick()
        frame = fire.render(sim.heat, sim.smoke, sim.width, sim.height,
                            sim.base_rows, seed=sim.seed)
        self.assertIn("\x1b[", frame, "frame must contain ANSI escapes")
        plain = _ANY_ESCAPE_RE.sub("", frame)
        lines = plain.split("\n")
        self.assertEqual(len(lines), sim.height)
        for line in lines:
            self.assertEqual(len(line), sim.width)


class TestSmoke(unittest.TestCase):
    def test_smoke_above_flame_top_in_some_frame(self):
        sim = fire.FireSimulation(seed=11)
        seen = False
        for _ in range(40):
            sim.tick()
            for x, y, _life in sim.smoke:
                top = sim.column_top(x)
                if top is not None and y < top:
                    seen = True
                    break
            if seen:
                break
        self.assertTrue(seen, "smoke must appear above the flame top in some frame")


class TestHeadless(unittest.TestCase):
    def test_main_is_noop_without_tty(self):
        self.assertFalse(sys.stdout.isatty())
        self.assertIsNone(fire.main())


if __name__ == "__main__":
    unittest.main()
