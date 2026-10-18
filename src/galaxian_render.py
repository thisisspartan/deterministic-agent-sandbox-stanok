"""galaxian_render — pure renderer: engine State -> half-block terminal frame (CC-294).

stdlib only; the engine is NOT imported (state attributes are duck-typed).
render_frame(state) returns exactly `state.height // 2 + 2` lines joined by
"\\n", no trailing newline: line 0 border, lines 1..height//2 half-block rows
encoding pixel pairs (2i, 2i+1) of the height x width field, last line status.
Pure: the state is never mutated; identical input -> identical output.
See docs/galaxian_render.md.
"""

from __future__ import annotations

# Palette (pinned by the contract).
EMPTY = (10, 10, 16)
BORDER = (60, 60, 90)
PLAYER = (235, 235, 235)
K1 = (0, 200, 0)
K2 = (0, 180, 220)
K3 = (255, 60, 60)
BULLET = (235, 235, 235)
BOMB = (255, 220, 80)
STAR = (90, 90, 110)

# Explosion color by explode-tick parity (pinned).
EXPLODE_ODD = (255, 140, 0)
EXPLODE_EVEN = (255, 60, 60)

_STATUS_FG = (220, 220, 220)
_STATUS_BG = (0, 0, 0)

_TOP = "\u2580"  # ▀
_BOTTOM = "\u2584"  # ▄
_RESET = "\x1b[0m"

_PLAYER_MASK = ("111", "010")
_KIND_MASKS = {1: ("101", "111"), 2: ("111", "101"), 3: ("10101", "11111", "01110")}
_KIND_COLORS = {1: K1, 2: K2, 3: K3}
_PROJECTILE_MASK = ("1", "1")

# Per-pixel draw priority: entity > star > empty.
_PRIO_STAR = 1
_PRIO_ENTITY = 2


def render_frame(state) -> str:
    """Render the state as a half-block frame (see docs/galaxian_render.md)."""
    width, height = state.width, state.height
    if height % 2 != 0:
        raise ValueError(f"height must be even, got {height}")
    field = [[None] * width for _ in range(height)]  # pixel -> (color, prio) | None
    _paint_field(field, state)
    lines = [_border_line(width)]
    lines.extend(_half_block_line(field, 2 * i, width) for i in range(height // 2))
    lines.append(_status_line(state, width))
    return "\n".join(lines)


def _paint_field(field, state) -> None:
    for star in state.stars:
        # A star is a single TOP pixel of cell (x, y // 2).
        x, y = star
        _paint(field, x, 2 * (y // 2), STAR, _PRIO_STAR)
    for enemy in state.enemies:
        if enemy.mode == "E":
            mask = _explode_mask(enemy.kind)
            color = EXPLODE_ODD if enemy.explode % 2 else EXPLODE_EVEN
        else:
            mask = _KIND_MASKS[enemy.kind]
            color = _KIND_COLORS[enemy.kind]
        _paint_mask(field, enemy.x, enemy.y, mask, color)
    for x, y in state.bullets:
        _paint_mask(field, x, y, _PROJECTILE_MASK, BULLET)
    for x, y in state.bombs:
        _paint_mask(field, x, y, _PROJECTILE_MASK, BOMB)
    if state.player_alive:
        _paint_mask(field, state.player_x, state.height - 2, _PLAYER_MASK, PLAYER)


def _explode_mask(kind: int) -> tuple:
    side = 5 if kind == 3 else 3
    return ("1" * side,) * 3


def _paint_mask(field, x, y, mask, color) -> None:
    for dy, row in enumerate(mask):
        for dx, on in enumerate(row):
            if on == "1":
                _paint(field, x + dx, y + dy, color, _PRIO_ENTITY)


def _paint(field, x, y, color, prio) -> None:
    if 0 <= x < len(field[0]) and 0 <= y < len(field):  # clip to the field
        current = field[y][x]
        if current is None or current[1] < prio:
            field[y][x] = (color, prio)


def _sgr(fg, bg) -> str:
    return f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"


def _border_line(width: int) -> str:
    return "".join(_sgr(BORDER, BORDER) + " " for _ in range(width)) + _RESET


def _half_block_line(field, top_y: int, width: int) -> str:
    parts = []
    for x in range(width):
        top = field[top_y][x]
        bottom = field[top_y + 1][x]
        fg = top[0] if top is not None else EMPTY
        bg = bottom[0] if bottom is not None else EMPTY
        if top is not None:
            glyph = _TOP  # top-only, or both (fg = top, bg = bottom)
        elif bottom is not None:
            glyph = _BOTTOM
        else:
            glyph = " "
        parts.append(_sgr(fg, bg) + glyph)
    return "".join(parts) + _RESET


def _status_line(state, width: int) -> str:
    text = f"SC {state.score:06d}  LV {state.wave:02d}  LIVES {state.lives}"
    text = text[:width] if len(text) > width else text.ljust(width)
    return _sgr(_STATUS_FG, _STATUS_BG) + text + _RESET
