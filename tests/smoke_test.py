"""Headless smoke test for the fire pipeline (TASK-FIRE-06).

Runs 100 frames of the full pipeline (ignite -> step -> render) at a
120x80 heat buffer (a 120x40 virtual terminal) with NO TTY output —
the renderer returns frame strings, nothing is written to stdout —
and asserts the average frame time stays within the 33 ms budget
(>= 30 FPS).
"""

import re
import time

from fire.palette import generate_fire_palette
from fire.renderer import FireRenderer
from fire.simulator import FireSimulation

WIDTH = 120
HEIGHT = 80  # heat rows; renders to HEIGHT // 2 = 40 terminal lines
FRAMES = 100
MAX_AVG_FRAME_MS = 33.0  # average frame must not exceed 33 ms (< 30 FPS)
HALF_BLOCK = "\u2580"  # ▀
ESC = "\033"


def _strip_ansi(text):
    return re.sub(r"\033\[[0-9;]*m", "", text)


def test_headless_100_frames_meet_30fps_budget():
    # 100 cycles of ignite -> step -> render at 120x80 (virtual 120x40),
    # headless (no TTY writes); the average frame time must be <= 33 ms.
    palette = generate_fire_palette()
    renderer = FireRenderer(palette)
    sim = FireSimulation(width=WIDTH, height=HEIGHT)

    start = time.perf_counter()
    for _ in range(FRAMES):
        sim.ignite_bottom()
        sim.step()
        renderer.render(sim.buffer)
    elapsed_s = time.perf_counter() - start

    avg_frame_ms = elapsed_s * 1000.0 / FRAMES
    assert avg_frame_ms <= MAX_AVG_FRAME_MS, (
        f"average frame time {avg_frame_ms:.2f} ms exceeds the "
        f"{MAX_AVG_FRAME_MS} ms budget (< 30 FPS)"
    )


def test_headless_frame_is_40_lines_of_120_half_blocks():
    # One rendered frame is exactly 40 terminal lines of 120 '▀' each,
    # carries TrueColor fg/bg codes and ends with a color reset.
    palette = generate_fire_palette()
    renderer = FireRenderer(palette)
    sim = FireSimulation(width=WIDTH, height=HEIGHT)
    sim.ignite_bottom()
    sim.step()
    frame = renderer.render(sim.buffer)
    lines = frame.split("\n")
    assert len(lines) == HEIGHT // 2
    for line in lines:
        assert _strip_ansi(line).count(HALF_BLOCK) == WIDTH
    assert "38;2;" in frame
    assert "48;2;" in frame
    assert frame.endswith(ESC + "[0m")
