"""Polish/robustness contract tests for src/fire.py (CC-110).

Run via:  bash scripts/run.sh test tests/fire_polish_test.py

Covers: rendering performance (300 frames 80x24 under a time budget),
deterministic headless CLI (--frame N byte-stable, animation progresses),
--frames N, small terminals, flag-respected dimensions, non-TTY safety and
multi-run integration determinism.
"""

import os
import re
import subprocess
import sys
import time

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
        timeout=30,
    )


def _visible_width(line):
    return len(ANSI_RE.sub("", line))


# --- performance ---------------------------------------------------------------

def test_render_300_frames_within_budget():
    t0 = time.perf_counter()
    sim = fire.FireSim(80, 24, seed=42)
    for _ in range(300):
        sim.tick()
        frame = fire.render(sim)
        assert frame
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"300 frames at 80x24 took {elapsed:.2f}s (budget 5s)"


# --- deterministic headless CLI -------------------------------------------------

def test_cli_frame_n_deterministic_and_progresses():
    base = ["src/fire.py", "--seed", "11", "--width", "32", "--height", "12"]
    f0 = _run_py(base + ["--frame", "0"])
    f12a = _run_py(base + ["--frame", "12"])
    f12b = _run_py(base + ["--frame", "12"])
    for p in (f0, f12a, f12b):
        assert p.returncode == 0, p.stderr
    assert f12a.stdout == f12b.stdout, "--frame 12 not byte-identical across runs"
    assert f12a.stdout != f0.stdout, "frame 12 equals frame 0: animation did not progress"


def test_cli_frames_n_renders_n_frames_and_exits_0():
    p = _run_py(["src/fire.py", "--seed", "5", "--frames", "5",
                 "--width", "24", "--height", "10"])
    assert p.returncode == 0, p.stderr
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 5 * 10, f"expected 50 frame lines, got {len(lines)}"
    for line in lines:
        assert _visible_width(line) == 24


# --- small terminal / dimensions --------------------------------------------------

def test_small_terminal_renders_without_error():
    p = _run_py(["src/fire.py", "--seed", "3", "--width", "20", "--height", "10"])
    assert p.returncode == 0, p.stderr
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 10
    for line in lines:
        assert _visible_width(line) == 20


def test_flags_change_rendered_dimensions():
    a = _run_py(["src/fire.py", "--frame", "0", "--width", "15", "--height", "6"])
    b = _run_py(["src/fire.py", "--frame", "0", "--width", "30", "--height", "12"])
    assert a.returncode == 0, a.stderr
    assert b.returncode == 0, b.stderr
    la = a.stdout.strip("\n").split("\n")
    lb = b.stdout.strip("\n").split("\n")
    assert len(la) == 6, f"--height 6 gave {len(la)} lines"
    assert all(_visible_width(l) == 15 for l in la), "--width 15 not respected"
    assert len(lb) == 12, f"--height 12 gave {len(lb)} lines"
    assert all(_visible_width(l) == 30 for l in lb), "--width 30 not respected"


# --- non-TTY safety ------------------------------------------------------------------

def test_non_tty_render_path_does_not_crash():
    p = _run_py(["src/fire.py", "--seed", "9", "--frame", "3",
                 "--width", "16", "--height", "8"])
    assert p.returncode == 0, p.stderr
    assert p.stdout, "no output on a non-TTY stdout"
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 8
    for line in lines:
        assert _visible_width(line) == 16


# --- integration determinism --------------------------------------------------------

def test_60_frame_fixed_seed_run_is_deterministic():
    def run60():
        sim = fire.FireSim(40, 16, seed=123)
        frames = []
        for _ in range(60):
            sim.tick()
            frames.append(fire.render(sim))
        return frames

    a = run60()
    b = run60()
    assert a[0] == b[0], "frame 0 differs between identical seeded runs"
    assert a[30] == b[30], "frame 30 differs between identical seeded runs"
    assert a[59] == b[59], "frame 59 differs between identical seeded runs"
