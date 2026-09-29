"""Reference tests for seeded determinism in src/fire/simulator.py (TASK-FIRE-08).

Contract:
- ``FireSimulation`` accepts an optional ``seed`` keyword (last parameter of
  ``__init__``). ``seed=None`` (default) preserves the previous
  non-deterministic behavior; ``seed=N`` makes the whole simulation
  deterministic: two simulations with the same seed and the same call
  sequence produce identical buffers.
- The randomness source is an internal ``random.Random(seed)`` instance;
  the module-level ``random`` functions are no longer consulted.
"""

from fire.simulator import FireSimulation


def _run(seed, width=20, height=10, ticks=30):
    sim = FireSimulation(width=width, height=height, seed=seed)
    sim.ignite_bottom()
    for _ in range(ticks):
        sim.update_wind()
        sim.step()
        sim.spawn_sparks()
    return sim


def test_same_seed_same_buffer():
    a = _run(seed=42)
    b = _run(seed=42)
    assert [row[:] for row in a.buffer] == [row[:] for row in b.buffer]


def test_different_seed_differs():
    a = _run(seed=42)
    b = _run(seed=43)
    assert [row[:] for row in a.buffer] != [row[:] for row in b.buffer]


def test_seed_none_still_valid():
    sim = FireSimulation(width=10, height=8)
    sim.ignite_bottom()
    for _ in range(5):
        sim.step()
    for row in sim.buffer:
        for value in row:
            assert 0 <= value <= 255
