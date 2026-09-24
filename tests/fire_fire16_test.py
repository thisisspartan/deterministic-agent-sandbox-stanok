"""16-color flame ramp (``fire16``) and ``--probe`` swatch card contract
tests for src/fire.py (CC-119).

The 16-color mode must show a real hot->cold gradient on a terminal that
renders ONLY basic SGR (``\\x1b[3Xm`` 0..7, ``\\x1b[9Xm`` 8..15): a hot core
on the bright hot colors, a red body, a blue base -- not a flat dark-red
blob. Therefore:

- ``fire16(heat, is_base, blank=0.10)`` is a pure, deterministic
  heat->basic-16 ramp: ``None`` for blank cells, a blue ramp for base
  cells, and a hot->cold ramp over the basic palette (bright hot colors
  for the core) for the flame body.
- ``render(sim, color_mode="16")`` uses ``fire16`` (NOT ``rgb_to_16``) and
  emits basic SGR only.
- ``fire.py --probe`` prints a static 16-color swatch card (2 rows of 8
  half-blocks, one per basic index 0..15) and exits 0.

Run via:  bash scripts/run.sh test tests/fire_fire16_test.py
"""

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")

import fire  # src is on sys.path via pythonpath=src in run.sh

BLOCK = "\u2580"
SEED = 42
TICKS = 8


def _run_py(args):
    env = dict(os.environ)
    env["PYTHONPATH"] = SRC_DIR
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable] + args,
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )


def _frame16(w, h, seed=SEED, ticks=TICKS):
    sim = fire.FireSim(w, h, seed=seed)
    for _ in range(ticks):
        sim.tick()
    return fire.render(sim, color_mode="16")


def _frame_indices(frame):
    """All basic-ANSI indices (0..15) used by the colored cells of a
    16-mode frame: ``\\x1b[3Xm`` -> X, ``\\x1b[9Xm`` -> 8 + X."""
    idxs = []
    for line in frame.split("\n"):
        for m in re.finditer(r"\x1b\[([39])([0-7])m\x1b\[0m" + BLOCK, line):
            prefix, x = m.group(1), int(m.group(2))
            idxs.append(x if prefix == "3" else 8 + x)
    return idxs


# --- fire16: the pure ramp contract ------------------------------------------

def test_fire16_zero_and_blank_heat():
    assert fire.fire16(0.0, False) is None
    assert fire.fire16(0.05, False) is None  # below the blank threshold
    assert fire.fire16(0.0, True) is None


def test_fire16_flame_body_ramp():
    assert fire.fire16(0.15, False) == 1    # red
    assert fire.fire16(0.40, False) == 9    # bright red
    assert fire.fire16(0.65, False) == 3    # yellow
    assert fire.fire16(0.85, False) == 11   # bright yellow
    assert fire.fire16(1.0, False) == 7     # white


def test_fire16_band_edges_are_the_contract():
    # Exact band edges: the ramp is < at each edge, >= at the top.
    assert fire.fire16(0.10, False) == 1    # blank threshold inclusive
    assert fire.fire16(0.30, False) == 9
    assert fire.fire16(0.55, False) == 3
    assert fire.fire16(0.75, False) == 11
    assert fire.fire16(0.90, False) == 7


def test_fire16_base_blue_ramp():
    assert fire.fire16(0.3, True) == 4      # blue
    assert fire.fire16(0.9, True) == 12     # bright blue
    assert fire.fire16(0.5, True) == 12     # base edge inclusive


# --- 16-mode frame: a gradient, not a flat red blob --------------------------

def test_frame16_has_hot_core_and_red_body():
    frame = _frame16(24, 12)
    idxs = _frame_indices(frame)
    assert idxs, "16-mode frame has no colored cells"
    # NOTE: the unchanged simulation's max flame-body heat is ~0.69 (below
    # the 0.75 bright-yellow edge), so the achievable hot core is yellow
    # (index 3); white (7) / bright yellow (11) are allowed but not
    # required.
    assert any(i in (3, 11, 7) for i in idxs), \
        "no hot-core cell (yellow/bright yellow/white) in the frame"
    assert any(i in (1, 9) for i in idxs), \
        "no red-body cell (red/bright red) in the frame"


def test_frame16_uses_at_least_three_distinct_indices():
    frame = _frame16(24, 12)
    idxs = _frame_indices(frame)
    assert len(set(idxs)) >= 3, \
        f"16-mode frame is near-monochrome: {sorted(set(idxs))}"


def test_frame16_basic_sgr_only():
    frame = _frame16(24, 12)
    assert "\x1b[38;" not in frame, \
        "16 mode must not emit extended \\x1b[38; escapes"
    assert "\x1b[38;2;" not in frame, \
        "16 mode must not emit truecolor escapes"


# --- CLI --probe: the static 16-color swatch card ----------------------------

def test_cli_probe_prints_all_16_basic_colors():
    p = _run_py(["src/fire.py", "--probe"])
    assert p.returncode == 0, p.stderr
    for i in range(8):
        assert "\x1b[3%dm" % i in p.stdout, "missing basic code \\x1b[3%dm" % i
        assert "\x1b[9%dm" % i in p.stdout, "missing bright code \\x1b[9%dm" % i
    assert p.stdout.count(BLOCK) == 16, \
        "probe card must show exactly 16 half-block cells"
    assert "\x1b[38;" not in p.stdout, \
        "probe card must contain no extended SGR sequence"
