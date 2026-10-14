"""CC-263: doomfire palette and frame formatter — heat -> color -> ANSI string.

Fixtures live inside this file (no conftest.py). The palette, the index
formula (heat * 20 // 255), the half-block cell layout and the ASCII
charset (heat * 9 // 255) are the contract and are exercised exactly.
"""

from pathlib import Path

from src.doomfire_palette import FIRE_PALETTE, heat_to_rgb, render_frame

MODULE_SOURCE = Path(__file__).resolve().parents[1] / "src" / "doomfire_palette.py"

UPPER_HALF = "▀"
ASCII_CHARS = " .:-=+*#%@"


def _cell(top_rgb, bottom_rgb):
    """The exact one-cell half-block escape sequence from the contract."""
    return (
        f"\x1b[38;2;{top_rgb[0]};{top_rgb[1]};{top_rgb[2]}m"
        f"\x1b[48;2;{bottom_rgb[0]};{bottom_rgb[1]};{bottom_rgb[2]}m"
        + UPPER_HALF
        + "\x1b[0m"
    )


# 1. Palette


def test_palette_has_21_entries_with_exact_endpoints():
    assert len(FIRE_PALETTE) == 21
    assert FIRE_PALETTE[0] == (0, 0, 0)
    assert FIRE_PALETTE[20] == (255, 255, 255)


def test_palette_is_monotone_non_decreasing_per_channel():
    for prev, nxt in zip(FIRE_PALETTE, FIRE_PALETTE[1:]):
        assert len(prev) == 3 and len(nxt) == 3
        for c in range(3):
            assert nxt[c] >= prev[c], (
                f"channel {c} decreases: {prev} -> {nxt}"
            )


# 2. heat_to_rgb


def test_heat_to_rgb_endpoints():
    assert heat_to_rgb(0) == (0, 0, 0)
    assert heat_to_rgb(255) == (255, 255, 255)


def test_heat_to_rgb_clamps_out_of_range():
    assert heat_to_rgb(-1) == (0, 0, 0)
    assert heat_to_rgb(-1000) == (0, 0, 0)
    assert heat_to_rgb(256) == (255, 255, 255)
    assert heat_to_rgb(1000) == (255, 255, 255)


def test_heat_to_rgb_matches_index_formula_for_every_heat():
    for heat in range(256):
        assert heat_to_rgb(heat) == FIRE_PALETTE[heat * 20 // 255], (
            f"heat {heat}: index must be heat * 20 // 255"
        )


# 3. Half-block frame mode (default)


def test_half_block_4_rows_is_exactly_2_lines():
    field = [[255, 0], [0, 0], [0, 0], [0, 0]]
    expected = (
        _cell((255, 255, 255), (0, 0, 0)) + _cell((0, 0, 0), (0, 0, 0)) + "\n"
        + _cell((0, 0, 0), (0, 0, 0)) + _cell((0, 0, 0), (0, 0, 0)) + "\n"
    )
    out = render_frame(field)
    assert out.splitlines(keepends=True) and len(out.splitlines()) == 2
    assert out == expected


def test_half_block_cell_contains_exact_escape_substrings():
    field = [[255], [0]]
    out = render_frame(field)
    assert "\x1b[38;2;255;255;255m" in out
    assert "\x1b[48;2;0;0;0m" in out
    assert UPPER_HALF in out
    assert out == _cell((255, 255, 255), (0, 0, 0)) + "\n"


def test_every_half_block_line_ends_with_newline():
    field = [[10, 20, 30], [40, 50, 60], [70, 80, 90], [100, 110, 120], [130, 140, 150]]
    out = render_frame(field)
    assert out.endswith("\n")
    lines = out.splitlines(keepends=True)
    assert len(lines) == (len(field) + 1) // 2  # odd height 5 -> 3 lines
    for line in lines:
        assert line.endswith("\n")


def test_half_block_odd_height_last_row_pairs_with_black():
    field = [[255], [0], [128]]
    expected = (
        _cell((255, 255, 255), (0, 0, 0)) + "\n"
        + _cell(FIRE_PALETTE[128 * 20 // 255], (0, 0, 0)) + "\n"
    )
    out = render_frame(field)
    assert len(out.splitlines()) == 2
    assert out == expected


# 4. ASCII mode


def test_ascii_mode_has_no_escapes_and_no_half_block():
    field = [[0, 128, 255], [64, 192, 255]]
    out = render_frame(field, ascii=True)
    assert "\x1b" not in out
    assert UPPER_HALF not in out


def test_ascii_mode_endpoints_and_line_count():
    field = [[0, 255], [255, 0]]
    out = render_frame(field, ascii=True)
    assert out == " @\n@ \n"
    assert len(out.splitlines()) == len(field)  # rows rendered 1:1


def test_ascii_mode_index_formula_for_every_heat():
    for heat in range(256):
        expected_char = ASCII_CHARS[heat * 9 // 255]
        assert render_frame([[heat]], ascii=True) == expected_char + "\n"


def test_ascii_mode_clamps_out_of_range_heat():
    assert render_frame([[-5]], ascii=True) == " \n"
    assert render_frame([[300]], ascii=True) == "@\n"


# 5. Degenerate 1x1 field


def test_single_cell_field_half_block():
    out = render_frame([[200]])
    assert out == _cell(heat_to_rgb(200), (0, 0, 0)) + "\n"


def test_single_cell_field_ascii():
    out = render_frame([[200]], ascii=True)
    assert out == ASCII_CHARS[200 * 9 // 255] + "\n"


# 6. Purity: no project imports, no I/O stdlib, no print


def test_module_is_pure():
    src = MODULE_SOURCE.read_text(encoding="utf-8")
    for needle in (
        "import sys",
        "import os",
        "import time",
        "doomfire_core",
        "print(",
    ):
        assert needle not in src, f"impure construct in module source: {needle!r}"
