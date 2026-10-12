"""Terminal driver + half-block renderer (TASK-STANOK-CC-249, FIRE2-02).

Turns a FireField-like buffer (see src/fire_engine.py: attributes `width`,
`height`, `buffer`) into one ANSI frame of upper-half-block cells: each
terminal row covers TWO field rows — fg is the top field row's palette color,
bg the bottom field row's — so a terminal of N rows displays a field of 2N.

Pure string building: no process loop, no I/O (that is FIRE2-03). The hot
render path only joins precomputed strings from PAIR_CACHE — no per-pixel
formatting.
"""

from fire_engine import PALETTE

# Terminal control sequences: enter/leave the alternate screen with the cursor
# hidden while animating, restored (SGR reset too) on exit.
ENTER = "\x1b[?1049h\x1b[?25l"
EXIT = "\x1b[?1049l\x1b[?25h\x1b[0m"

HOME = "\x1b[H"  # cursor home — no clear: every cell of the frame is repainted
RESET = "\x1b[0m"
CELL = "▀"  # U+2580 UPPER HALF BLOCK

INDEX_COUNT = len(PALETTE)  # 37 palette indices (0..36)


class _PairCache(dict):
    """Lookup table of fg/bg escape sequences for every palette index pair.

    Keyed by the (top, bottom) tuple; a flat `top * 37 + bottom` integer is
    accepted too (same entry), so callers may index either way.
    """

    def __missing__(self, key):
        if isinstance(key, int):
            return self[key // INDEX_COUNT, key % INDEX_COUNT]
        raise KeyError(key)


def _build_pair_cache():
    """Build all 37x37 entries once, at import: the only place f-strings run."""
    cache = _PairCache()
    for top_index, (tr, tg, tb) in enumerate(PALETTE):
        fg = f"\x1b[38;2;{tr};{tg};{tb}m"
        for bottom_index, (br, bg, bb) in enumerate(PALETTE):
            cache[(top_index, bottom_index)] = (
                f"{fg}\x1b[48;2;{br};{bg};{bb}m{CELL}"
            )
    return cache


PAIR_CACHE = _build_pair_cache()


def render_frame(field):
    """One full frame: `\\x1b[H` + rows of cached `▀` cells joined by `\\n` + reset.

    Terminal row i pairs field rows (2i, 2i+1). A trailing unpaired field row
    (odd height) is rendered as a full block (fg == bg) rather than dropped.
    The field is read-only; it is never mutated.
    """
    width, height, buf = field.width, field.height, field.buffer
    cache = PAIR_CACHE
    rows = []
    for y in range(0, height, 2):
        top = y * width
        bottom = min(y + 1, height - 1) * width
        rows.append("".join(
            cache[(buf[top + x], buf[bottom + x])] for x in range(width)
        ))
    return HOME + "\n".join(rows) + RESET


def frame_bytes(frame):
    """UTF-8 encoding of a frame, for callers that write bytes to the terminal."""
    return frame.encode("utf-8")
