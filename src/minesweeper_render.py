"""minesweeper_render — pure text-frame renderer of the console Minesweeper (CC-307, R1..R3).

render(state) turns a GameState (duck-typed; src/minesweeper_engine.py) into a
tuple of strings: the console frame. The module imports NOTHING and performs no
I/O; it never mutates its input and returns the same frame for the same state.
Coordinates are 1-based: x = column 1..width, y = row 1..height.
"""


def _cell_char(state, x, y):
    """Cell symbol, priority top-down: revealed mine '*', flag 'F',
    opened ' ' (adj==0) or str(adj), otherwise closed '#'."""
    cell = (x, y)
    if state.status != "playing" and cell in state.mines:
        return "*"
    if cell in state.flagged:
        return "F"
    if cell in state.opened:
        adj = state.adj[y - 1][x - 1]
        return " " if adj == 0 else str(adj)
    return "#"


def render(state):
    """R1 frame: counter line, blank line, optional tens ruler (width > 9),
    units ruler, then one line per row with a right-aligned row-number prefix.
    R2: pure — the state is only read; the result is an immutable tuple.
    R3: after "won"/"lost" every mine is shown as '*' (flags keep 'F' on
    non-mine cells; '*' outranks 'F' on a flagged mine)."""
    width, height = state.width, state.height
    safe_total = width * height - state.mines_total
    word = {"playing": "playing", "won": "won", "lost": "lost"}[state.status]
    hh = len(str(height))
    gutter = " " * (hh + 1)
    lines = [
        "mines {}/{}  open {}/{}  {}".format(
            state.mines_total - len(state.flagged), state.mines_total,
            len(state.opened), safe_total, word),
        "",
    ]
    if width > 9:
        lines.append(gutter + "".join(
            str(x // 10) if x >= 10 else " " for x in range(1, width + 1)))
    lines.append(gutter + "".join(str(x % 10) for x in range(1, width + 1)))
    for y in range(1, height + 1):
        lines.append("{:>{}} ".format(y, hh) + "".join(
            _cell_char(state, x, y) for x in range(1, width + 1)))
    return tuple(lines)
