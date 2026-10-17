"""fire_render — stage 2 of the console-fire pipeline: heat field -> frame string.

Pure string-in/string-out renderer using the half-block glyph (U+2580) and
24-bit ANSI truecolor: two field rows are packed into one character line
(upper half = foreground of the upper row, lower half = background of the
lower row). No CLI, no terminal probing, no sleeps, no stdout writes — the
CLI (stage 3) supplies the canvas size and calls these names.

The contract is documented in docs/fire_render.md and pinned by
tests/fire_render_test.py.
"""

import random

import fire_sim

HALF_BLOCK = "▀"  # U+2580
FALLBACK_COLUMNS = 80  # default canvas width the CLI may use
FALLBACK_ROWS = 24  # default canvas height the CLI may use
ANSI_RESET = "\x1b[0m"


def render_frame(field: list[list[float]], color_rng: random.Random) -> str:
    """Render ONE heat field (height rows x width cols, values in [0, 1])
    into ONE frame string of `height // 2` lines joined by "\\n", each line
    exactly `width` half-block glyphs.

    height must be even (two field rows per character line) — odd height
    raises ValueError. For each character cell the upper half shows the
    upper row's heat, the lower half the lower row's heat:

      - both halves empty -> a bare HALF_BLOCK with no escape codes;
      - otherwise -> "\\x1b[38;2;{r};{g};{b}m" for the upper color (if any),
        then "\\x1b[48;2;{r};{g};{b}m" for the lower color (if any), then
        the glyph, then ANSI_RESET.

    Colors come from fire_sim.heat_to_rgb for every cell, top-left to
    bottom-right, row-major — a single deterministic rng stream. Pure:
    `field` is never mutated; same field + same rng state -> byte-identical
    string.
    """
    height = len(field)
    if height % 2 != 0:
        raise ValueError(f"field height must be even (got {height})")
    if height == 0:
        return ""
    width = len(field[0])

    # One color per cell, row-major top-left to bottom-right: a single
    # deterministic stream of heat_to_rgb draws from color_rng.
    colors = [
        [fire_sim.heat_to_rgb(field[r][c], color_rng) for c in range(width)]
        for r in range(height)
    ]

    lines: list[str] = []
    for r in range(0, height, 2):
        upper_row, lower_row = colors[r], colors[r + 1]
        cells: list[str] = []
        for c in range(width):
            upper, lower = upper_row[c], lower_row[c]
            if upper is None and lower is None:
                cells.append(HALF_BLOCK)
                continue
            cell = ""
            if upper is not None:
                cell += f"\x1b[38;2;{upper[0]};{upper[1]};{upper[2]}m"
            if lower is not None:
                cell += f"\x1b[48;2;{lower[0]};{lower[1]};{lower[2]}m"
            cell += HALF_BLOCK + ANSI_RESET
            cells.append(cell)
        lines.append("".join(cells))
    return "\n".join(lines)


def compose_frame(frame: str, columns: int, rows: int) -> str:
    """Center a frame string in a `rows` x `columns` canvas: returns exactly
    `rows` lines joined by "\\n" — each frame line padded with leading spaces
    so it is horizontally centered ((columns - len(line)) // 2), the canvas
    filled below the frame with blank lines.

    Frame taller than the canvas -> ValueError; any frame line wider than the
    canvas -> ValueError. Pure string-in/string-out; terminal sizes are the
    CLI's concern (FALLBACK_COLUMNS / FALLBACK_ROWS are defaults the CLI may
    use).
    """
    lines = frame.split("\n")
    if len(lines) > rows:
        raise ValueError(f"frame is taller than the canvas ({len(lines)} > {rows})")
    for line in lines:
        if len(line) > columns:
            raise ValueError(
                f"frame is wider than the canvas (line of {len(line)} > {columns})"
            )
    out = [" " * ((columns - len(line)) // 2) + line for line in lines]
    out.extend("" for _ in range(rows - len(out)))
    return "\n".join(out)
