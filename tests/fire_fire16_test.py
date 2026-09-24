"""16-color flame ramp (``fire16``) and ``--probe`` swatch card contract
tests (CC-119).

The 16-color mode must show a real hot->cold gradient on terminals that
render ONLY basic SGR (``\\x1b[3Xm`` 0..7, ``\\x1b[9Xm`` 8..15): a bright
core, a red body, a blue base -- not a flat dark-red blob. Therefore:

- ``fire16(heat, is_base, blank=0.10) -> int | None``: pure, deterministic
  heat->basic-16 flame ramp (no PRNG, no wall clock).
- ``render(sim, color_mode="16")`` uses ``fire16`` (NOT ``rgb_to_16``),
  emits basic SGR only, and renders a smoke cell as index 8 (bright black).
- ``fire.py --probe`` prints a static 16-color swatch card (2 rows of 8
  half-blocks, one per basic ANSI index 0..15) and exits 0; it takes
  precedence over ``--frame``/``--frames``/``--color`` and works headless.

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
    """The set of basic-16 color indices used in a 16-mode frame."""
    idxs = set()
    for m in re.finditer(r"\x1b\[([39])([0-7])m\x1b\[0m" + BLOCK, frame):
        idxs.add((8 if m.group(1) == "9" else 0) + int(m.group(2)))
    return idxs


# --- fire16: the pure heat->basic-16 flame ramp -------------------------------

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
    """A 24x12 frame (seed 42, 8 ticks) must contain at least one hot-core
    cell (index in {7, 11, 15}) AND at least one red-body cell (index in
    {1, 9}) -- a gradient, not a monochrome blob."""
    frame = _frame16(24, 12)
    idxs = _indices(frame)
    assert idxs & {7, 11, 15}, f"no hot-core index in {sorted(idxs)}"
    assert idxs & {1, 9}, f"no red-body index in {sorted(idxs)}"


def test_frame16_uses_at_least_three_distinct_indices():
    frame = _frame16(24, 12)
    assert len(_indices(frame)) >= 3, \
        f"16-mode frame is monochrome: {sorted(_indices(frame))}"


def test_frame16_emits_basic_sgr_only():
    frame = _frame16(24, 12)
    assert "\x1b[38;" not in frame, \
        "16 mode must not emit extended \\x1b[38; escapes"
    assert "\x1b[38;2;" not in frame, \
        "16 mode must not emit truecolor escapes"


# --- CLI --probe: the static 16-color swatch card -----------------------------

def test_cli_probe_prints_all_16_basic_colors():
    p = _run_py(["src/fire.py", "--probe"])
    assert p.returncode == 0, p.stderr
    for i in range(8):
        assert "\x1b[3%dm" % i in p.stdout, \
            f"probe card missing basic code \\x1b[3{i}m"
        assert "\x1b[9%dm" % i in p.stdout, \
            f"probe card missing bright code \\x1b[9{i}m"
    assert p.stdout.count(BLOCK) == 16, \
        f"probe card must show exactly 16 half-blocks, got {p.stdout.count(BLOCK)}"
    assert "\x1b[38;" not in p.stdout, \
        "probe card must use basic SGR only"


def test_cli_probe_takes_precedence_and_works_headless():
    """--probe wins over --frame/--frames/--color: no simulation runs, the
    output is the static card, and it works without a TTY."""
    p = _run_py(["src/fire.py", "--probe", "--frame", "5", "--frames", "3",
                 "--color", "truecolor"])
    assert p.returncode == 0, p.stderr
    assert p.stdout.count(BLOCK) == 16
    assert "\x1b[38;" not in p.stdout
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 2, "probe card is 2 rows of 8"
    for line in lines:
        assert len(re.sub(r"\x1b\[[0-9;]*m", "", line)) == 8
