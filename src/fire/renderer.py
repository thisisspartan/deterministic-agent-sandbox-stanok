"""Sub-pixel half-block terminal renderer (TASK-FIRE-04).

The character ``▀`` (U+2580, Upper Half Block) draws the upper half of a
cell in the Foreground color (``\\033[38;2;R;G;Bm``) and the lower half in
the Background color (``\\033[48;2;R;G;Bm``). A heat buffer of height
``2 * H`` therefore renders into ``H`` terminal lines with vertical
resolution ``2 * H``.
"""

from __future__ import annotations

from typing import List, Optional, Tuple

RGB = Tuple[int, int, int]

HALF_BLOCK = "\u2580"  # ▀
_RESET = "\033[0m"


class FireRenderer:
    """Renders a heat buffer as half-block TrueColor terminal lines.

    ``palette`` is a list of ``(r, g, b)`` tuples (each channel an int in
    ``[0..255]``); buffer values index into it: the upper half of a cell
    takes ``palette[buffer[y][x]]`` as foreground, the lower half takes
    ``palette[buffer[y + 1][x]]`` as background.
    """

    def __init__(self, palette: List[RGB]) -> None:
        if not isinstance(palette, (list, tuple)) or not palette:
            raise ValueError("palette must be a non-empty list of (r, g, b) tuples")
        for entry in palette:
            if (
                not isinstance(entry, (tuple, list))
                or len(entry) != 3
                or any(not isinstance(c, int) or not 0 <= c <= 255 for c in entry)
            ):
                raise ValueError(
                    "palette entries must be (r, g, b) tuples of ints in [0..255]"
                )
        self.palette: List[RGB] = [tuple(entry) for entry in palette]

    def render(self, buffer: List[List[int]]) -> str:
        """Render the heat buffer into a frame of half-block lines.

        ``buffer`` must be a rectangular matrix of height ``2 * H`` (even)
        and width ``W`` with values in ``[0, len(palette) - 1]``. Row pair
        ``(y, y + 1)`` becomes one line of ``W`` ``▀`` characters. A color
        code is emitted only when it differs from the previous pixel's
        (the terminal color state persists across the whole frame); the
        frame ends with a color reset (``\\033[0m``).
        """
        if not isinstance(buffer, (list, tuple)):
            raise ValueError("buffer must be a list of rows")
        width = len(buffer[0]) if buffer else 0
        for row in buffer:
            if not isinstance(row, (list, tuple)) or len(row) != width:
                raise ValueError("buffer must be rectangular")
        height = len(buffer)
        if height % 2 != 0:
            raise ValueError("buffer height must be even (2 * H)")
        max_value = len(self.palette) - 1
        for row in buffer:
            for value in row:
                if not isinstance(value, int) or not 0 <= value <= max_value:
                    raise ValueError(
                        f"buffer value {value!r} outside [0..{max_value}]"
                    )

        parts: List[str] = []
        cur_fg: Optional[RGB] = None
        cur_bg: Optional[RGB] = None
        for y in range(0, height, 2):
            top = buffer[y]
            bottom = buffer[y + 1]
            for x in range(width):
                fg = self.palette[top[x]]
                bg = self.palette[bottom[x]]
                if fg != cur_fg:
                    parts.append(f"\033[38;2;{fg[0]};{fg[1]};{fg[2]}m")
                    cur_fg = fg
                if bg != cur_bg:
                    parts.append(f"\033[48;2;{bg[0]};{bg[1]};{bg[2]}m")
                    cur_bg = bg
                parts.append(HALF_BLOCK)
            if y + 2 < height:
                parts.append("\n")
        parts.append(_RESET)
        return "".join(parts)
