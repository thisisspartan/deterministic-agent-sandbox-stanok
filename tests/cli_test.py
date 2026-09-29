"""Reference tests for src/fire/cli.py (TASK-FIRE-07).

Contract:
- ``FireApp(fps=30, stream=io.StringIO())`` constructs headless (no TTY
  required).
- ``FireApp._step()`` advances the simulation by one frame AND spawns
  sparks every frame: ``spawn_sparks`` is called exactly once per frame in
  BOTH the auto-wind branch (``update_wind`` once, ``step`` once without a
  wind argument) and the static-wind branch (``step(wind=...)`` once).
"""

import io

from fire.cli import FireApp


class _StubSim:
    """Records calls to update_wind / step / spawn_sparks."""

    def __init__(self):
        self.update_wind_calls = 0
        self.step_winds = []  # the wind argument of each step() call
        self.spawn_sparks_calls = 0

    def update_wind(self):
        self.update_wind_calls += 1

    def step(self, wind=None):
        self.step_winds.append(wind)

    def spawn_sparks(self, count=3):
        self.spawn_sparks_calls += 1


def test_fireapp_constructs_headless():
    app = FireApp(fps=30, stream=io.StringIO())
    assert app.fps == 30
    assert app.wind == "auto"
    assert app.sim is not None
    assert app.renderer is not None


def test_step_auto_wind_spawns_sparks():
    app = FireApp(fps=30, stream=io.StringIO())
    stub = _StubSim()
    app.sim = stub
    app._step()
    assert stub.spawn_sparks_calls == 1
    assert stub.update_wind_calls == 1
    # step called exactly once, without a wind argument.
    assert stub.step_winds == [None]


def test_step_static_wind_spawns_sparks():
    app = FireApp(fps=30, stream=io.StringIO())
    app.wind = 1
    stub = _StubSim()
    app.sim = stub
    app._step()
    assert stub.spawn_sparks_calls == 1
    # step called exactly once with the static wind.
    assert stub.step_winds == [1]
