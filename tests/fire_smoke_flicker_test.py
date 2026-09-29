"""Reference tests for smoke particles and per-frame flicker (TASK-FIRE-11).

Contract:
- Flicker: ``FireApp`` owns a per-frame global intensity factor
  ``app._flicker`` (``1.0`` initially), recomputed at the end of every
  ``_step()`` as ``1.0 + uniform(-0.15, 0.15)`` from the app's OWN
  ``random.Random(seed)`` (never ``sim._rng``). Consecutive frames differ;
  equal seeds give equal sequences.
- Smoke (simulator): ``FireSimulation.smoke`` is a ``height x width``
  grid of ints ``>= 0`` (0 = no smoke, ``> 0`` = remaining particle life).
  ``update_smoke()`` moves every particle up one row and decrements its
  life (particles on row 0 or with life 1 vanish). ``spawn_smoke()`` with
  probability 0.5 spawns one particle just above the flame top of a
  random column (life ``randint(8, 16)``). ``step()`` calls
  ``spawn_smoke()`` then ``update_smoke()`` at the end and never touches
  the heat buffer for smoke.
- Smoke (renderer): ``render(buffer, flicker=1.0, smoke=None)`` —
  ``smoke`` is a rectangular grid of ints ``>= 0`` of the same size as
  ``buffer`` or ``None`` (``ValueError`` otherwise). Per cell, after
  flicker/jitter: ``smoke[y][x] > 0`` -> fg = ``SMOKE_GRAY``;
  ``smoke[y+1][x] > 0`` -> bg = ``SMOKE_GRAY``.
- CLI: ``current_frame()`` renders with ``flicker=app._flicker`` and
  ``smoke=sim.smoke``; the rendered frame of a running fire contains the
  smoke gray color.
"""

import io

from fire.cli import FireApp, main
from fire.palette import generate_fire_palette
from fire.renderer import FireRenderer
from fire.simulator import FireSimulation

SMOKE_GRAY_CODE = "\033[38;2;60;60;65m"


# --- Flicker (FireApp) --------------------------------------------------------


def test_flicker_range():
    app = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    vals = []
    for _ in range(10):
        app.advance(1)
        vals.append(app._flicker)
    assert all(0.85 <= v <= 1.15 for v in vals)
    # Consecutive frames differ (the flicker is not stuck at one value).
    assert len(set(vals)) > 1


def test_flicker_deterministic():
    a = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    b = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    seq_a = []
    seq_b = []
    for _ in range(5):
        a.advance(1)
        b.advance(1)
        seq_a.append(a._flicker)
        seq_b.append(b._flicker)
    assert seq_a == seq_b


def test_flicker_default_one():
    app = FireApp(fps=30, seed=7, width=20, height=10, stream=io.StringIO())
    assert app._flicker == 1.0


# --- Smoke (simulator) ----------------------------------------------------------


def test_smoke_rises_and_fades():
    sim = FireSimulation(4, 8, seed=1)
    sim.smoke[3][2] = 5
    for _ in range(3):
        sim.update_smoke()
    # 3 ticks up: (3,2,5) -> (2,2,4) -> (1,2,3) -> (0,2,2).
    assert sim.smoke[0][2] == 2
    # One more tick: the particle is on row 0 -> it vanishes.
    sim.update_smoke()
    for row in sim.smoke:
        for value in row:
            assert value == 0


def test_spawn_smoke_populates():
    sim = FireSimulation(20, 40, seed=5)
    sim.ignite_bottom()
    for _ in range(50):
        sim.spawn_smoke()
    assert any(v > 0 for row in sim.smoke for v in row)


def test_smoke_rises_over_frames():
    sim = FireSimulation(20, 40, seed=11)
    sim.ignite_bottom()
    tops = []
    for _ in range(30):
        sim.step()
        ys = [
            y
            for y in range(sim.height)
            for x in range(sim.width)
            if sim.smoke[y][x] > 0
        ]
        if ys:
            tops.append(min(ys))
    assert tops, "no smoke appeared over 30 frames"
    # The smoke top moved upward (smaller y) over the frames.
    assert min(tops) < max(tops)


# --- Smoke (renderer + CLI) ------------------------------------------------------


def test_smoke_renders_gray():
    buffer = [[0] * 4 for _ in range(4)]
    smoke = [[0] * 4 for _ in range(4)]
    smoke[0][0] = 5
    renderer = FireRenderer(generate_fire_palette())
    out = renderer.render(buffer, smoke=smoke)
    assert SMOKE_GRAY_CODE in out
    # Without the smoke grid the gray color is absent.
    out_plain = renderer.render(buffer)
    assert SMOKE_GRAY_CODE not in out_plain


def test_cli_smoke_present():
    buf = io.StringIO()
    rc = main(
        ["--seed", "42", "--frame", "30", "--width", "20", "--height", "10"],
        stream=buf,
    )
    assert rc == 0
    assert SMOKE_GRAY_CODE in buf.getvalue()
