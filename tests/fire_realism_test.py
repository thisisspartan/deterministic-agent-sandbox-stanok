"""Reference tests for renderer realism (TASK-FIRE-10).

Contract:
- ``FireRenderer(palette, blue_palette=None, base_rows=0, jitter_seed=None)``:
  - ``blue_palette``: a 256-entry ``(r, g, b)`` palette or ``None``; the same
    validation as ``palette`` (non-empty list of int tuples in ``[0..255]``);
  - ``base_rows``: int ``>= 0`` — the number of BOTTOM buffer rows (counted
    from the last) that are indexed into ``blue_palette`` instead of
    ``palette``; ``0`` or ``blue_palette=None`` disables the effect;
  - ``jitter_seed``: int or ``None``; if not ``None`` anti-banding jitter is
    enabled.
- ``render(buffer, flicker=1.0)`` — per-cell value transforms, in order:
  1. ``flicker`` (a number ``> 0``): ``value = clamp(round(value * flicker),
     0, 255)``; ``1.0`` is a no-op;
  2. jitter: if ``jitter_seed is not None`` add ``{-1, 0, 1}`` to the value,
     clamped to ``[0, 255]``; a fresh ``random.Random(jitter_seed)`` is created
     on every ``render()`` call and consumed in row-major order (rows top to
     bottom, left to right) — same buffer => same frame;
  3. palette selection: buffer row ``y`` (and ``y + 1`` for bg) is taken from
     ``blue_palette`` if ``y >= height - base_rows``, else from ``palette``.
- ``base_rows`` not an int or ``< 0`` -> ``ValueError``; ``flicker`` not a
  number or ``<= 0`` -> ``ValueError``.
"""

import io
import re

from fire.cli import main
from fire.palette import generate_fire_palette
from fire.renderer import FireRenderer

# 256 entries: cold half black, hot half "explicitly blue".
_BLUE = [(0, 0, 0)] * 128 + [(0, 0, 255)] * 128


def _fg_codes(frame):
    """The set of distinct foreground SGR colors in a frame."""
    return set(re.findall(r"\033\[38;2;(\d+;\d+;\d+)m", frame))


def test_blue_base_used():
    # 4x4 buffer: rows 0..1 cold, rows 2..3 hot. With base_rows=2 the bottom
    # two rows index the blue palette, so row 2's fg is _BLUE[200] = (0,0,255).
    buffer = [
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [200, 200, 200, 200],
        [200, 200, 200, 200],
    ]
    renderer = FireRenderer(
        generate_fire_palette(), blue_palette=_BLUE, base_rows=2
    )
    out = renderer.render(buffer)
    assert "\033[38;2;0;0;255m" in out  # fg of row 2 via the blue palette


def test_no_blue_base_without_palette():
    # Same buffer, no blue palette: the hot rows use the fire palette, which
    # never produces (0, 0, 255).
    buffer = [
        [0, 0, 0, 0],
        [0, 0, 0, 0],
        [200, 200, 200, 200],
        [200, 200, 200, 200],
    ]
    renderer = FireRenderer(generate_fire_palette())
    out = renderer.render(buffer)
    assert "\033[38;2;0;0;255m" not in out


def test_jitter_breaks_banding():
    # Flat 4x4 buffer (all 128): without jitter every fg is identical (one
    # code); with jitter the per-cell {-1,0,1} perturbation breaks the band.
    buffer = [[128] * 4 for _ in range(4)]
    out_jitter = FireRenderer(generate_fire_palette(), jitter_seed=7).render(buffer)
    assert len(_fg_codes(out_jitter)) > 1
    out_flat = FireRenderer(generate_fire_palette()).render(buffer)
    assert len(_fg_codes(out_flat)) == 1


def test_jitter_deterministic():
    # Same flat buffer, two render() calls with the same seed -> identical
    # frames (a fresh Random(seed) is created per call).
    buffer = [[128] * 4 for _ in range(4)]
    renderer = FireRenderer(generate_fire_palette(), jitter_seed=7)
    assert renderer.render(buffer) == renderer.render(buffer)


def test_flicker_default_noop():
    palette = generate_fire_palette()
    buffer = [
        [255, 128, 64, 0],
        [0, 32, 96, 180],
        [128, 255, 0, 64],
        [32, 96, 180, 0],
    ]
    renderer = FireRenderer(palette)
    assert renderer.render(buffer) == renderer.render(buffer, flicker=1.0)


def test_flicker_scales():
    # 2x2 buffer, one hot cell (128) in the fg row, the rest 0.
    palette = generate_fire_palette()
    buffer = [[128, 0], [0, 0]]
    renderer = FireRenderer(palette)
    hot = palette[255]  # 128 * 2.0 = 256 -> clamped to 255
    out_double = renderer.render(buffer, flicker=2.0)
    assert f"\033[38;2;{hot[0]};{hot[1]};{hot[2]}m" in out_double
    mid = palette[64]  # 128 * 0.5 = 64
    out_half = renderer.render(buffer, flicker=0.5)
    assert f"\033[38;2;{mid[0]};{mid[1]};{mid[2]}m" in out_half


def test_cli_wires_blue_base():
    # The CLI wires the blue combustion base into the renderer: the rendered
    # frame must contain at least one SGR color with blue dominance
    # (b - r >= 50). The fire palette's maximum b - r is 35, so this can only
    # come from the blue base.
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frame", "5", "--width", "20", "--height", "10"],
        stream=buf,
    )
    assert rc == 0
    frame = buf.getvalue()
    colors = re.findall(r"\033\[(?:38|48);2;(\d+);(\d+);(\d+)m", frame)
    assert colors, "frame contains no SGR colors"
    assert any((int(b) - int(r)) >= 50 for r, _g, b in colors)
