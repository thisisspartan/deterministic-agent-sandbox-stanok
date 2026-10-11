"""fire_render — terminal driver + half-block renderer for the Doom fire (FIRE-02).

Pure string building over a `FireField`-shaped object (`width`, `height`,
`buffer`): no process loop, no file/socket I/O, no subprocess. The engine
(`src/fire_engine.py`) supplies the palette; this module only turns a buffer
into terminal bytes.

Contract (stdlib only):

- ENTER / EXIT: the terminal control sequences that enter the alternate screen
  with the cursor hidden, and leave it with the cursor shown and SGR reset.

- PAIR_CACHE: for every (top, bottom) pair of palette indices, the exact
  escape string `"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m▀"`,
  built ONCE at import. The render path only joins cached strings — no
  formatting per pixel.

- render_frame(field) -> str: one full frame. Starts with `"\x1b[H"` (cursor
  home, no clear), then one line per terminal row — each terminal row pairs
  two field rows (top row y, bottom row y+1) into `width` half-block cells,
  fg from the top field row and bg from the bottom field row — joined with
  `"\n"`, ending with `"\x1b[0m"`.

- frame_bytes(frame) -> bytes: the utf-8 encoding of a frame string.
"""

try:  # imported as part of the package (tests, `python3 -m pytest`)
    from src.fire_engine import PALETTE
except ImportError:  # run directly: `python3 src/fire_render.py` puts src/ on sys.path
    from fire_engine import PALETTE

# Enter the alternate screen and hide the cursor.
ENTER = "\x1b[?1049h\x1b[?25l"
# Leave the alternate screen, show the cursor, reset all SGR state.
EXIT = "\x1b[?1049l\x1b[?25h\x1b[0m"

# A frame starts by homing the cursor (no clear: the whole screen is repainted)
# and ends by resetting SGR so the shell is left clean.
HOME = "\x1b[H"
RESET = "\x1b[0m"

# The half block: fg paints the top field row, bg the bottom one.
HALF_BLOCK = "▀"

_INDEX_COUNT = len(PALETTE)


def _pair(top, bottom):
    """Format one half-block cell for a pair of palette indices."""
    tr, tg, tb = PALETTE[top]
    br, bg, bb = PALETTE[bottom]
    return f"\x1b[38;2;{tr};{tg};{tb}m\x1b[48;2;{br};{bg};{bb}m{HALF_BLOCK}"


# Precomputed at import: every (top, bottom) index pair -> its escape string.
# 37x37 = 1369 entries; the hot render path does dict lookups and joins only.
PAIR_CACHE = {
    (top, bottom): _pair(top, bottom)
    for top in range(_INDEX_COUNT)
    for bottom in range(_INDEX_COUNT)
}


def render_frame(field):
    """Render a FireField-like object (width, height, buffer) as one frame.

    Terminal rows are pairs of field rows: the cell at column x takes fg from
    `buffer[y][x]` and bg from `buffer[y + 1][x]`. The field is only read.
    """
    width, height, buf = field.width, field.height, field.buffer
    cache = PAIR_CACHE
    rows = []
    for y in range(0, height - 1, 2):
        top = y * width
        bottom = top + width
        rows.append("".join(
            cache[(buf[top + x], buf[bottom + x])] for x in range(width)
        ))
    return HOME + "\n".join(rows) + RESET


def frame_bytes(frame):
    """Encode a frame string as utf-8 bytes, for callers that write bytes."""
    return frame.encode("utf-8")
