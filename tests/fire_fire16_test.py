"""16-color flame ramp (``fire16``) and ``--probe`` swatch card contract
tests for src/fire.py (CC-119).

The 16-color mode must show a real hot->cold gradient (bright core, red
body, blue base) instead of a dark-red blob, and ``--probe`` must print a
static 16-color swatch card so a user can see which basic colors their
terminal renders.

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


def _frame16(w, h, seed=SEED, ticks=8):
    sim = fire.FireSim(w, h, seed=seed)
    for _ in range(ticks):
        sim.tick()
    return fire.render(sim, color_mode="16")


def _indices(frame):
    """Set of basic-ANSI indices (0..15) actually used in a 16-mode frame."""
    idxs = set()
    for m in re.finditer(r"\x1b\[([39])([0-7])m", frame):
        prefix, x = m.group(1), int(m.group(2))
        idxs.add(x if prefix == "3" else x + 8)
    return idxs


# --- fire16: pure heat -> basic-16 index --------------------------------------

def test_fire16_zero_and_below_blank_are_none():
    assert fire.fire16(0.0, False) is None
    assert fire.fire16(0.05, False) is None  # below the blank threshold


def test_fire16_flame_body_hot_to_cold_ramp():
    assert fire.fire16(0.15, False) == 1    # red
    assert fire.fire16(0.40, False) == 9    # bright red
    assert fire.fire16(0.65, False) == 3    # yellow
    assert fire.fire16(0.85, False) == 11   # bright yellow
    assert fire.fire16(1.0, False) == 7     # white


def test_fire16_base_blue_ramp():
    assert fire.fire16(0.3, True) == 4      # blue
    assert fire.fire16(0.9, True) == 12     # bright blue


# --- 16-mode frame: a real gradient, not a flat blob --------------------------

def test_frame16_has_hot_core_and_red_body():
    # A real hot->cold gradient, not a flat blob: a hot color in the core
    # (yellow 3 is the hottest the unchanged simulation reaches; 7/11/15
    # would appear if the core ran hotter) AND a red body (1/9).
    frame = _frame16(24, 12)
    idxs = _indices(frame)
    assert idxs & {3, 7, 11, 15}, \
        "no hot-core index in the 16-mode frame (got %r)" % idxs
    assert idxs & {1, 9}, \
        "no red-body index in the 16-mode frame (got %r)" % idxs


def test_frame16_uses_at_least_three_distinct_indices():
    frame = _frame16(24, 12)
    idxs = _indices(frame)
    assert len(idxs) >= 3, \
        "16-mode frame is monochrome (only %r)" % idxs


def test_frame16_basic_sgr_only():
    frame = _frame16(24, 12)
    assert "\x1b[38;" not in frame, \
        "16 mode must not emit extended \\x1b[38; escapes"
    assert "\x1b[38;2;" not in frame, \
        "16 mode must not emit truecolor escapes"


# --- CLI --probe: static 16-color swatch card ----------------------------------

def test_cli_probe_prints_swatch_card():
    p = _run_py(["src/fire.py", "--probe"])
    assert p.returncode == 0, p.stderr
    for i in range(8):
        assert "\x1b[3%dm" % i in p.stdout, "missing \\x1b[3%dm" % i
        assert "\x1b[9%dm" % i in p.stdout, "missing \\x1b[9%dm" % i
    assert p.stdout.count(BLOCK) == 16, \
        "expected 16 half-blocks, got %d" % p.stdout.count(BLOCK)
    assert "\x1b[38;" not in p.stdout, \
        "--probe must not emit extended \\x1b[38; escapes"
