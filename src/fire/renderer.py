"""Sub-pixel half-block terminal renderer (TASK-FIRE-04).

The character ``▀`` (U+2580, Upper Half Block) draws the upper half of a
cell in the Foreground color (``\\033[38;2;R;G;Bm``) and the lower half in
the Background color (``\\033[48;2;R;G;Bm``). A heat buffer of height
``2 * H`` therefore renders into ``H`` terminal lines with vertical
resolution ``2 * H``.

Realism effects (TASK-FIRE-10):

- **Blue combustion base** — the ``base_rows`` bottom buffer rows (counted
  from the last) are indexed into ``blue_palette`` (the gas palette)
  instead of ``palette``;
- **Anti-banding jitter** — when ``jitter_seed`` is not ``None``, each cell
  value gets a deterministic ``{-1, 0, 1}`` perturbation (a fresh
  ``random.Random(jitter_seed)`` per ``render()`` call, consumed in row-major
  order) so flat heat areas do not produce hard color steps;
- **Flicker** — ``render(buffer, flicker)`` scales every cell value by
  ``flicker`` (clamped to ``[0, 255]``); ``1.0`` is a no-op.

TASK-FIRE-11 adds **smoke**: ``render(buffer, flicker=1.0, smoke=None)``
accepts a rectangular grid of ints ``>= 0`` of the same size as the
buffer (or ``None``). After the flicker/jitter transforms, a cell with
``smoke[y][x] > 0`` takes ``SMOKE_GRAY`` as its foreground and a cell
with ``smoke[y + 1][x] > 0`` takes ``SMOKE_GRAY`` as its background
(instead of the palette colors).
"""

from __future__ import annotations

import random
from typing import List, Optional, Tuple

RGB = Tuple[int, int, int]

HALF_BLOCK = "\u2580"  # ▀
_RESET = "\033[0m"

# TASK-FIRE-11: the gray color of a smoke particle (fg or bg override).
SMOKE_GRAY: RGB = (60, 60, 65)


def _validate_palette(palette) -> List[RGB]:
    """Validate a palette and return it as a list of ``(r, g, b)`` tuples."""
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
    return [tuple(entry) for entry in palette]


class FireRenderer:
    """Renders a heat buffer as half-block TrueColor terminal lines.

    ``palette`` is a list of ``(r, g, b)`` tuples (each channel an int in
    ``[0..255]``); buffer values index into it: the upper half of a cell
    takes ``palette[buffer[y][x]]`` as foreground, the lower half takes
    ``palette[buffer[y + 1][x]]`` as background.

    ``blue_palette`` (same validation as ``palette``) or ``None``: when
    given, the ``base_rows`` bottom buffer rows (counted from the last) are
    indexed into it instead of ``palette`` (the blue combustion base).
    ``base_rows`` must be an int ``>= 0``; ``0`` or ``blue_palette=None``
    disables the effect. ``jitter_seed`` (int or ``None``) enables the
    deterministic anti-banding jitter when not ``None``.
    """

    def __init__(
        self,
        palette: List[RGB],
        blue_palette: Optional[List[RGB]] = None,
        base_rows: int = 0,
        jitter_seed: Optional[int] = None,
    ) -> None:
        self.palette: List[RGB] = _validate_palette(palette)
        self.blue_palette: Optional[List[RGB]] = (
            _validate_palette(blue_palette) if blue_palette is not None else None
        )
        if not isinstance(base_rows, int) or base_rows < 0:
            raise ValueError("base_rows must be an int >= 0")
        self.base_rows = base_rows
        self.jitter_seed = jitter_seed

    def render(
        self,
        buffer: List[List[int]],
        flicker: float = 1.0,
        smoke: Optional[List[List[int]]] = None,
    ) -> str:
        """Render the heat buffer into a frame of half-block lines.

        ``buffer`` must be a rectangular matrix of height ``2 * H`` (even)
        and width ``W`` with values in ``[0, len(palette) - 1]``. Row pair
        ``(y, y + 1)`` becomes one line of ``W`` ``▀`` characters. A color
        code is emitted only when it differs from the previous pixel's
        (the terminal color state persists across the whole frame); the
        frame ends with a color reset (``\\033[0m``).

        ``smoke`` (TASK-FIRE-11) is ``None`` or a rectangular grid of ints
        ``>= 0`` of the same size as ``buffer``; a ``ValueError`` is
        raised otherwise.

        Each cell value is transformed before the palette lookup, in order:

        1. ``flicker`` (a number ``> 0``): ``value = clamp(round(value *
           flicker), 0, 255)``; ``1.0`` is a no-op;
        2. jitter (when ``jitter_seed is not None``): add ``{-1, 0, 1}``,
           clamped to ``[0, 255]``; a fresh ``random.Random(jitter_seed)`` is
           created per call and consumed in row-major order (rows top to
           bottom, left to right) — same buffer => same frame;
        3. palette selection: buffer row ``y`` (and ``y + 1`` for bg) is
           taken from ``blue_palette`` if ``y >= height - base_rows``, else
           from ``palette``;
        4. smoke override: if ``smoke`` is given, ``smoke[y][x] > 0``
           replaces the foreground with ``SMOKE_GRAY`` and
           ``smoke[y + 1][x] > 0`` replaces the background with
           ``SMOKE_GRAY``.
        """
        if not isinstance(flicker, (int, float)) or flicker <= 0:
            raise ValueError("flicker must be a number > 0")
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
        if smoke is not None:
            if not isinstance(smoke, (list, tuple)):
                raise ValueError("smoke must be a list of rows or None")
            for row in smoke:
                if not isinstance(row, (list, tuple)) or len(row) != width:
                    raise ValueError("smoke must be rectangular like buffer")
            if len(smoke) != height:
                raise ValueError("smoke must have the same size as buffer")
            for row in smoke:
                for value in row:
                    if not isinstance(value, int) or value < 0:
                        raise ValueError(
                            f"smoke value {value!r} must be an int >= 0"
                        )

        # Per-cell transforms: flicker, then jitter (row-major order).
        rng = (
            random.Random(self.jitter_seed) if self.jitter_seed is not None else None
        )
        values: List[List[int]] = []
        for y in range(height):
            row_values: List[int] = []
            for x in range(width):
                value = min(255, max(0, round(buffer[y][x] * flicker)))
                if rng is not None:
                    value = min(255, max(0, value + rng.choice((-1, 0, 1))))
                row_values.append(value)
            values.append(row_values)

        # Blue combustion base: the bottom ``base_rows`` buffer rows index
        # ``blue_palette`` (disabled when ``blue_palette`` is ``None``).
        blue_from = (
            height - self.base_rows if self.blue_palette is not None else height
        )
        parts: List[str] = []
        cur_fg: Optional[RGB] = None
        cur_bg: Optional[RGB] = None
        for y in range(0, height, 2):
            top = values[y]
            bottom = values[y + 1]
            fg_palette = self.blue_palette if y >= blue_from else self.palette
            bg_palette = self.blue_palette if (y + 1) >= blue_from else self.palette
            for x in range(width):
                fg = fg_palette[top[x]]
                bg = bg_palette[bottom[x]]
                # TASK-FIRE-11: smoke overrides the palette colors.
                if smoke is not None:
                    if smoke[y][x] > 0:
                        fg = SMOKE_GRAY
                    if smoke[y + 1][x] > 0:
                        bg = SMOKE_GRAY
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
