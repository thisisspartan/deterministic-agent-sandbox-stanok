"""Basic contract tests for src/fire.py (CC-108: working skeleton).

Run via:  bash scripts/run.sh test tests/fire_basic_test.py
"""

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

import fire  # noqa: E402  (src is on sys.path via pythonpath=src in run.sh)


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


# --- import contract ----------------------------------------------------------

def test_import_has_no_io_side_effects():
    # Importing the module must not start the animation and must not write
    # anything to stdout/stderr.
    p = _run_py(["-c", "import fire"])
    assert p.returncode == 0, p.stderr
    assert p.stdout == ""
    assert p.stderr == ""


# --- determinism ---------------------------------------------------------------

def test_same_seed_gives_identical_frames():
    a = fire.FireSim(24, 12, seed=42)
    b = fire.FireSim(24, 12, seed=42)
    for _ in range(6):
        a.tick()
        b.tick()
    assert fire.render(a) == fire.render(b)


def test_different_seed_changes_frames():
    a = fire.FireSim(24, 12, seed=42)
    b = fire.FireSim(24, 12, seed=7)
    for _ in range(8):
        a.tick()
        b.tick()
    assert fire.render(a) != fire.render(b)


def test_cli_frame_is_deterministic():
    args = ["src/fire.py", "--seed", "7", "--frame", "12",
            "--width", "24", "--height", "10"]
    p1 = _run_py(args)
    p2 = _run_py(args)
    assert p1.returncode == 0, p1.stderr
    assert p2.returncode == 0, p2.stderr
    assert p1.stdout == p2.stdout


# --- heat field -----------------------------------------------------------------

def test_heat_field_bounds_and_evolution():
    sim = fire.FireSim(24, 12, seed=1)
    sim.tick()
    for row in sim.heat:
        for v in row:
            assert 0.0 <= v <= 1.0
    snap = [list(r) for r in sim.heat]
    sim.tick()
    assert sim.heat != snap
    # The flame actually exists: substantial heat at the base row.
    assert max(sim.heat[11]) > 0.5
    # Base-zone flag: middle of the bottom row is the blue combustion zone.
    assert sim.base[11][12] is True
    # After several ticks the flame climbs to the upper rows.
    sim2 = fire.FireSim(24, 12, seed=1)
    for _ in range(10):
        sim2.tick()
    assert max(max(r) for r in sim2.heat[:6]) > 0.0


def test_smoke_particles_sparse_and_in_bounds():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(60):
        sim.tick()
    assert 0 <= len(sim.smoke) <= 12
    for p in sim.smoke:
        assert 0 <= p.x < 24
        assert 0 <= p.y < 12
        assert 0.0 < p.life <= 1.0


# --- palette --------------------------------------------------------------------

def test_palette_returns_none_for_zero_heat():
    assert fire.palette(0.0, False) is None
    assert fire.palette(0.0, True) is None


def test_palette_components_in_range():
    for heat in (0.05, 0.2, 0.35, 0.5, 0.7, 0.9, 1.0):
        rgb = fire.palette(heat, False)
        assert rgb is not None
        assert len(rgb) == 3
        for c in rgb:
            assert isinstance(c, int)
            assert 0 <= c <= 255


def test_palette_hot_is_bright_and_white_hot_at_peak():
    hot = fire.palette(1.0, False)
    cool = fire.palette(0.3, False)
    assert sum(hot) > sum(cool)
    assert fire.palette(1.0, False) == (255, 255, 240)


def test_palette_base_zone_is_blue():
    rgb = fire.palette(0.5, True)
    assert rgb is not None
    assert rgb[2] > rgb[0]  # blue channel dominant


# --- renderer ---------------------------------------------------------------------

def test_render_dimensions_match_grid():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    lines = frame.split("\n")
    assert len(lines) == 12
    for line in lines:
        visible = ANSI_RE.sub("", line)
        assert len(visible) == 24


def test_render_emits_truecolor_ansi_and_half_blocks():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    assert "\x1b[38;2;" in frame
    assert "▀" in frame


def test_render_zero_heat_is_plain_spaces():
    sim = fire.FireSim(8, 4, seed=0)
    frame = fire.render(sim)
    assert "38;2" not in frame
    for line in frame.split("\n"):
        assert ANSI_RE.sub("", line) == " " * 8


# --- CLI / entrypoint -------------------------------------------------------------

def test_cli_frame_zero_exits_clean():
    p = _run_py(["src/fire.py", "--frame", "0", "--width", "20", "--height", "8"])
    assert p.returncode == 0, p.stderr
    lines = p.stdout.split("\n")
    assert len(lines) == 9 and lines[-1] == ""
    for line in lines[:-1]:
        assert len(ANSI_RE.sub("", line)) == 20


def test_cli_frames_renders_n_frames_then_exits():
    p = _run_py(["src/fire.py", "--frames", "3", "--width", "20", "--height", "8"])
    assert p.returncode == 0, p.stderr
    blocks = p.stdout.strip("\n").split("\n")
    assert len(blocks) == 3 * 8


def test_headless_no_tty_renders_one_frame_and_exits():
    p = _run_py(["src/fire.py", "--width", "20", "--height", "8"])
    assert p.returncode == 0, p.stderr
    blocks = p.stdout.strip("\n").split("\n")
    assert len(blocks) == 8


def test_run_sh_smoke_loads_module_without_animation():
    p = subprocess.run(
        ["bash", "scripts/run.sh", "smoke", "src/fire.py"],
        cwd=REPO_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=20,
    )
    assert p.returncode == 0, p.stderr
