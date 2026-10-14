"""doomfire palette — heat -> color -> ANSI frame string, pure formatting, no I/O.

Maps a heat field (``list[list[int]]``, rows top->bottom, cells in
``[0, 255]`` — the shape produced by the core model, though this module
imports nothing from the project) to a renderable string: the classic DOOM
fire colormap
(21 entries, black -> red -> orange -> yellow -> white) rendered either as
ANSI 24-bit half-block cells (default) or as a 1:1 ASCII ramp.

This module imports nothing from the project and no I/O stdlib
(``sys``/``os``/``time``); it only returns strings.
"""

FIRE_PALETTE = (
    (0, 0, 0),
    (7, 7, 7),
    (31, 7, 7),
    (50, 11, 7),
    (74, 17, 7),
    (102, 27, 7),
    (134, 37, 7),
    (172, 47, 7),
    (206, 67, 7),
    (244, 83, 7),
    (255, 103, 15),
    (255, 127, 27),
    (255, 151, 39),
    (255, 171, 59),
    (255, 199, 79),
    (255, 227, 103),
    (255, 255, 127),
    (255, 255, 159),
    (255, 255, 199),
    (255, 255, 239),
    (255, 255, 255),
)

ASCII_CHARS = " .:-=+*#%@"


def _clamp_heat(heat: int) -> int:
    if heat < 0:
        return 0
    if heat > 255:
        return 255
    return heat


def heat_to_rgb(heat: int) -> tuple[int, int, int]:
    """Color of a heat value: clamped to [0, 255], index = heat * 20 // 255."""
    return FIRE_PALETTE[_clamp_heat(heat) * 20 // 255]


def render_frame(field, ascii: bool = False) -> str:
    """Render the whole heat field as one string; no I/O.

    Half-block mode (default): each output line renders a pair of field
    rows (0,1), (2,3), ...; an odd last row pairs with cold (heat 0). One
    cell = foreground of the TOP row heat + background of the BOTTOM row
    heat + U+2580 + reset. Output line count = (height + 1) // 2.

    ascii=True: one charset char per cell, rows rendered 1:1, char index
    = heat * 9 // 255 (heat clamped). Every line ends with "\\n".
    """
    lines = []
    if ascii:
        for row in field:
            lines.append(
                "".join(ASCII_CHARS[_clamp_heat(heat) * 9 // 255] for heat in row)
                + "\n"
            )
        return "".join(lines)

    height = len(field)
    for y in range(0, height, 2):
        top = field[y]
        bottom = field[y + 1] if y + 1 < height else [0] * len(top)
        cells = []
        for x, heat in enumerate(top):
            r1, g1, b1 = heat_to_rgb(heat)
            r2, g2, b2 = heat_to_rgb(bottom[x])
            cells.append(
                f"\x1b[38;2;{r1};{g1};{b1}m"
                f"\x1b[48;2;{r2};{g2};{b2}m"
                "▀"
                "\x1b[0m"
            )
        lines.append("".join(cells) + "\n")
    return "".join(lines)
