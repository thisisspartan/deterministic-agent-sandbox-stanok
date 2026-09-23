"""16-color mode contract tests for src/fire.py (CC-117).

Compatibility defect fix: the 16-color mode must emit BASIC SGR codes
only -- ``\\x1b[3Xm`` (X in 0..7) and ``\\x1b[9Xm`` (bright 8..15, X in
0..7) -- the most compatible color encoding that exists. Terminals that
drop the extended SGR sequences ``\\x1b[38;5;N`` do so even for N in
0..15, but usually still understand the basic codes. Therefore:

- ``render(sim, color_mode="16")``: colored cell ``N`` in 0..7 renders
  as ``\\x1b[3Xm\\x1b[0m\\u2580`` with X = N; N in 8..15 renders as
  ``\\x1b[9Xm\\x1b[0m\\u2580`` with X = N - 8. Blank cell = space.
- ``rgb_to_16`` is UNCHANGED (returns 0..15, same mapping).
- All other modes keep their exact behavior (truecolor default, 256,
  none); CLI, simulation, determinism unchanged.

Run via:  bash scripts/run.sh test tests/fire_color16_test.py
"""

import os
import re
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(REPO_ROOT, "src")

import fire  # src is on sys.path via pythonpath=src in run.sh

# One 16-mode cell: a basic-SGR half-block (normal 3X or bright 9X) or a
# plain space. NO extended \x1b[38;5; codes may appear in 16-mode output.
CELL16_RE = re.compile(r"(\x1b\[(3[0-7]|9[0-7])m\x1b\[0m▀| )")
# A whole row of 16-mode cells.
LINE16_RE = re.compile(r"(?:\x1b\[(?:3[0-7]|9[0-7])m\x1b\[0m▀| )+")
CELL256_RE = re.compile(r"(\x1b\[38;5;(\d+)m\x1b\[0m▀| )")
CELLTC_RE = re.compile(r"(\x1b\[38;2;\d+;\d+;\d+m\x1b\[0m▀| )")
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
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


# --- rgb_to_16 (UNCHANGED contract) ------------------------------------------

def test_rgb_to_16_known_values():
    # Exact palette hits.
    assert fire.rgb_to_16((0, 0, 0)) == 0        # black
    assert fire.rgb_to_16((196, 0, 0)) == 1      # red
    assert fire.rgb_to_16((0, 196, 0)) == 2      # green
    assert fire.rgb_to_16((196, 196, 0)) == 3    # yellow
    assert fire.rgb_to_16((0, 0, 204)) == 4      # blue
    assert fire.rgb_to_16((196, 0, 196)) == 5    # magenta
    assert fire.rgb_to_16((0, 196, 196)) == 6    # cyan
    assert fire.rgb_to_16((229, 229, 229)) == 7  # white
    # Tie between the dim and the bright variant -> lower index wins, so
    # pure white maps to 7, pure red to 1.
    assert fire.rgb_to_16((255, 255, 255)) == 7
    assert fire.rgb_to_16((255, 0, 0)) == 1


def test_rgb_to_16_in_range_for_palette_colors():
    for heat in (0.15, 0.2, 0.35, 0.5, 0.7, 0.9, 1.0):
        rgb = fire.palette(heat, False)
        idx = fire.rgb_to_16(rgb)
        assert isinstance(idx, int)
        assert 0 <= idx <= 15, f"rgb_to_16({rgb}) = {idx} out of range"
    for heat in (0.1, 0.5, 1.0):
        rgb = fire.palette(heat, True)
        idx = fire.rgb_to_16(rgb)
        assert 0 <= idx <= 15


# --- renderer: 16 mode (basic SGR only) ----------------------------------------

def test_render_16_mode_cell_alignment_and_basic_sgr_only():
    frame = _frame16(24, 12)
    assert "\x1b[38;5;" not in frame, \
        "16 mode must not emit extended \\x1b[38;5; escapes"
    assert "\x1b[38;2;" not in frame, \
        "16 mode must not emit truecolor escapes"
    lines = frame.split("\n")
    assert len(lines) == 12
    saw_block = False
    for line in lines:
        pos = 0
        for m in CELL16_RE.finditer(line):
            assert m.start() == pos, "16-mode frame is not cell-aligned"
            pos = m.end()
            if m.group(1)[0] == "\x1b":
                saw_block = True
        assert pos == len(line), "trailing garbage in 16-mode line"
        assert len(CELL16_RE.findall(line)) == 24
    assert saw_block, "16-mode frame has no colored cells"


def test_render_16_mode_blank_cells_are_plain_spaces():
    frame = _frame16(24, 12)
    # Every character of a 16-mode frame is part of a basic-SGR cell or a
    # plain space (blank cell): each row full-matches the cell row pattern.
    for line in frame.split("\n"):
        assert LINE16_RE.fullmatch(line) is not None
        assert len(ANSI_RE.sub("", line)) == 24
    assert " " in frame, "expected blank (space) cells in the frame"


def test_render_16_mode_encodes_every_index_via_basic_sgr(monkeypatch):
    """For every N in 0..15 the 16-mode cell must be
    ``\\x1b[3Xm\\x1b[0m▀`` (N 0..7, X=N) or ``\\x1b[9Xm\\x1b[0m▀``
    (N 8..15, X=N-8) -- and no other color SGR code may appear."""
    sim = fire.FireSim(24, 12, seed=42)
    for _ in range(8):
        sim.tick()
    for n in range(16):
        monkeypatch.setattr(fire, "rgb_to_16", lambda rgb, n=n: n)
        frame = fire.render(sim, color_mode="16")
        esc = "3%d" % n if n < 8 else "9%d" % (n - 8)
        want = "\x1b[%sm" % esc
        assert want in frame, f"N={n}: expected {want!r} in the frame"
        for m in re.finditer(r"\x1b\[([0-9;]+)m", frame):
            code = m.group(1)
            assert code == "0" or code == esc, (
                f"N={n}: unexpected SGR code \\x1b[{code}m"
            )


def test_render_16_mode_is_deterministic():
    a = fire.FireSim(24, 12, seed=42)
    b = fire.FireSim(24, 12, seed=42)
    for _ in range(8):
        a.tick()
        b.tick()
    assert fire.render(a, color_mode="16") == fire.render(b, color_mode="16")
    c = fire.FireSim(24, 12, seed=7)
    for _ in range(8):
        c.tick()
    assert fire.render(a, color_mode="16") != fire.render(c, color_mode="16")


# --- regression guards: other modes keep their exact behavior -------------------

def test_render_default_stays_truecolor():
    """The default renderer keeps emitting 24-bit truecolor escapes and
    never basic- or extended-escape half-blocks."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim)
    assert "\x1b[38;2;" in frame
    assert "\x1b[38;5;" not in frame
    assert re.search(r"\x1b\[(3[0-7]|9[0-7])m", frame) is None, \
        "default mode must not emit basic SGR escapes"
    assert BLOCK in frame
    for line in frame.split("\n"):
        pos = 0
        for m in CELLTC_RE.finditer(line):
            assert m.start() == pos, "truecolor frame is not cell-aligned"
            pos = m.end()
        assert pos == len(line), "trailing garbage in truecolor line"


def test_render_256_mode_still_extended():
    """256 mode keeps emitting \\x1b[38;5;N (N 0..255) -- never basic
    SGR, never truecolor."""
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="256")
    assert "\x1b[38;5;" in frame
    assert "\x1b[38;2;" not in frame
    assert re.search(r"\x1b\[(3[0-7]|9[0-7])m", frame) is None, \
        "256 mode must not emit basic SGR escapes"
    for line in frame.split("\n"):
        pos = 0
        for m in CELL256_RE.finditer(line):
            assert m.start() == pos, "256-mode frame is not cell-aligned"
            pos = m.end()
            idx = m.group(2)
            if idx is not None:
                assert 0 <= int(idx) <= 255
        assert pos == len(line), "trailing garbage in 256-mode line"


def test_render_none_mode_has_no_ansi():
    sim = fire.FireSim(24, 12, seed=3)
    for _ in range(8):
        sim.tick()
    frame = fire.render(sim, color_mode="none")
    assert "\x1b[" not in frame
    for line in frame.split("\n"):
        assert len(line) == 24
    assert BLOCK in frame


# --- CLI ------------------------------------------------------------------------

def test_cli_color16_uses_basic_sgr_only():
    p = _run_py(["src/fire.py", "--color", "16", "--frames", "1",
                 "--width", "20", "--height", "8"])
    assert p.returncode == 0, p.stderr
    assert re.search(r"\x1b\[(3[0-7]|9[0-7])m", p.stdout), \
        "CLI --color 16 output must contain a basic SGR sequence"
    assert "\x1b[38;" not in p.stdout, \
        "CLI --color 16 output must contain no extended SGR sequence"
    lines = p.stdout.strip("\n").split("\n")
    assert len(lines) == 8
    for line in lines:
        assert LINE16_RE.fullmatch(line) is not None
        assert len(ANSI_RE.sub("", line)) == 20
