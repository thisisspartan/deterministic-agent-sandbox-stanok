"""Reference tests for src/fire/palette.py (TASK-FIRE-01).

Contract:
- generate_fire_palette() -> list of exactly 256 (r, g, b) int tuples;
- index 0 is strictly (0, 0, 0) (cold/background);
- control points at indices 0/32/96/180/240/255, smooth linear
  interpolation between them;
- every channel strictly within [0..255];
- brightness (r + g + b) monotonically non-decreasing from index 0 to 240;
- generate_blue_fire_palette() satisfies the same structural contract.
"""

from fire.palette import generate_blue_fire_palette, generate_fire_palette

PALETTE_SIZE = 256

FIRE_NODES = (
    (0, (0, 0, 0)),        # black / background
    (32, (140, 0, 0)),     # dark red
    (96, (255, 100, 0)),   # bright orange
    (180, (255, 220, 50)), # golden yellow
    (240, (255, 255, 230)),# white
    (255, (220, 240, 255)),# white-blue hot sparks
)


def _check_structure(palette):
    assert isinstance(palette, list)
    assert len(palette) == PALETTE_SIZE
    for entry in palette:
        assert isinstance(entry, tuple) and len(entry) == 3
        for channel in entry:
            assert isinstance(channel, int)
            assert 0 <= channel <= 255
    assert palette[0] == (0, 0, 0)
    # Brightness monotonically increases from 0 to 240.
    for i in range(1, 241):
        assert sum(palette[i]) >= sum(palette[i - 1])


def _expected_color(nodes, i):
    for (i0, c0), (i1, c1) in zip(nodes, nodes[1:]):
        if i0 <= i <= i1:
            t = (i - i0) / (i1 - i0)
            return tuple(c0[k] + (c1[k] - c0[k]) * t for k in range(3))
    raise AssertionError(f"index {i} outside node range")


def test_fire_palette_structure():
    _check_structure(generate_fire_palette())


def test_fire_palette_control_points():
    palette = generate_fire_palette()
    for index, color in FIRE_NODES:
        assert palette[index] == color, (
            f"index {index}: {palette[index]} != {color}"
        )


def test_fire_palette_linear_interpolation():
    palette = generate_fire_palette()
    for i in range(PALETTE_SIZE):
        expected = _expected_color(FIRE_NODES, i)
        for k in range(3):
            assert abs(palette[i][k] - expected[k]) <= 1, (
                f"index {i} channel {k}: {palette[i][k]} != {expected[k]:.4f}"
            )


def test_blue_fire_palette_structure():
    palette = generate_blue_fire_palette()
    _check_structure(palette)
    # Hot sparks stay blue-dominant.
    assert palette[255][2] >= 240


def test_blue_fire_palette_differs_from_fire():
    assert generate_blue_fire_palette() != generate_fire_palette()
