"""CC-294 — galaxian_render reference tests (contract: docs/galaxian_render.md).

render_frame(state) -> str: a pure half-block terminal frame of the engine
state. The renderer must NOT import the engine — these tests build
duck-typed states locally (plain dataclasses), never importing
src.galaxian_engine.

Geometry (pinned formula): exactly `state.height // 2 + 2` lines —
line 0 border, lines 1..height//2 half-block rows encoding pixel pairs
(2i, 2i+1) of the height x width field, last line status. The formula is
the contract; the field covers ALL height pixel rows (the player lives at
y = height-2 and must be renderable).
"""

import copy
import dataclasses
import re
import sys

import pytest

import galaxian_render as bare  # noqa: F401  (pythonpath=src form)
from src import galaxian_render as r  # namespaced form

WIDTH, HEIGHT = 12, 8

RESET = "\x1b[0m"
TOP = "\u2580"  # ▀
BOTTOM = "\u2584"  # ▄
STATUS_PREFIX = "\x1b[38;2;220;220;220m\x1b[48;2;0;0;0m"

# Palette pinned by the contract (docs/galaxian_render.md).
EMPTY = (10, 10, 16)
BORDER = (60, 60, 90)
PLAYER = (235, 235, 235)
K1 = (0, 200, 0)
K2 = (0, 180, 220)
K3 = (255, 60, 60)
BULLET = (235, 235, 235)
BOMB = (255, 220, 80)
STAR = (90, 90, 110)
EXPLODE_ODD = (255, 140, 0)
EXPLODE_EVEN = (255, 60, 60)


@dataclasses.dataclass
class FakeEnemy:
    kind: int
    mode: str  # 'F' | 'D' | 'E'
    x: int
    y: int
    explode: int = 0


@dataclasses.dataclass
class FakeState:
    width: int = WIDTH
    height: int = HEIGHT
    score: int = 0
    wave: int = 1
    lives: int = 3
    player_x: int = WIDTH // 2
    player_alive: bool = False  # neutral default; sprite tests opt in
    game_over: bool = False
    enemies: tuple = ()
    bullets: tuple = ()
    bombs: tuple = ()
    stars: tuple = ()


def _state(**over):
    return FakeState(**over)


def _enemy(kind, mode, x, y, explode=0):
    return FakeEnemy(kind=kind, mode=mode, x=x, y=y, explode=explode)


_SEG_RE = re.compile(r"\x1b\[38;2;(\d+);(\d+);(\d+)m\x1b\[48;2;(\d+);(\d+);(\d+)m(.)")


def _cells(line):
    """Strict parse of one styled line into (fg, bg, glyph) segments.

    The line must end with exactly one RESET; the body must be a complete
    concatenation of truecolor SGR segments — any stray byte fails the match.
    """
    assert line.count(RESET) == 1 and line.endswith(RESET), "exactly one reset, at the end"
    body = line[: -len(RESET)]
    cells = []
    pos = 0
    while pos < len(body):
        m = _SEG_RE.match(body, pos)
        assert m is not None, f"malformed segment at {pos}: {body[pos:pos + 24]!r}"
        cells.append(
            (
                (int(m.group(1)), int(m.group(2)), int(m.group(3))),
                (int(m.group(4)), int(m.group(5)), int(m.group(6))),
                m.group(7),
            )
        )
        pos = m.end()
    return cells


def _lines(frame):
    assert isinstance(frame, str)
    assert not frame.endswith("\n")
    return frame.split("\n")


def _row(frame, i):
    return _cells(_lines(frame)[i])


def _field_grid(frame):
    """Half-block rows only: lines 1..height//2 (border and status excluded)."""
    return [_cells(line) for line in _lines(frame)[1:-1]]


def _colors(cells):
    out = set()
    for fg, bg, _ in cells:
        out.add(fg)
        out.add(bg)
    return out


def _empty_row(width=WIDTH):
    return [(EMPTY, EMPTY, " ")] * width


# 1. Geometry ------------------------------------------------------------------

def test_empty_field_frame_geometry():
    st = _state()
    frame = r.render_frame(st)
    ls = _lines(frame)
    # Pinned formula: height // 2 + 2 lines (6 for height=8).
    assert len(ls) == st.height // 2 + 2
    # Line 0: the border — width segments, fg == bg == BORDER.
    assert _row(frame, 0) == [(BORDER, BORDER, " ")] * WIDTH
    # Half-block lines 1..height//2: width EMPTY segments, glyph " ".
    for i in range(1, st.height // 2 + 1):
        assert _row(frame, i) == _empty_row()
    # Last line: status, text truncated exactly to width.
    assert ls[-1] == STATUS_PREFIX + "SC 000000  LV 01  LIVES 3"[:WIDTH] + RESET


# 2. Status line ---------------------------------------------------------------

def test_status_truncated_to_width_with_single_sgr():
    st = _state(width=20, score=1234567, wave=99, lives=9)
    status = _lines(r.render_frame(st))[-1]
    text = "SC 1234567  LV 99  LIVES 9"  # 25 chars > width 20
    assert status == STATUS_PREFIX + text[:20] + RESET
    assert status.count("\x1b[38;2;") == 1  # at most one SGR prefix
    assert status.count("\x1b[48;2;") == 1
    assert status.count(RESET) == 1


def test_status_padded_with_spaces_to_width():
    st = _state(width=30, score=1234567, wave=99, lives=9)
    status = _lines(r.render_frame(st))[-1]
    text = "SC 1234567  LV 99  LIVES 9"  # 26 chars < width 30
    assert status == STATUS_PREFIX + text + " " * (30 - len(text)) + RESET


# 3. Palette -------------------------------------------------------------------

def test_palette_constants_pinned():
    assert r.EMPTY == EMPTY
    assert r.BORDER == BORDER
    assert r.PLAYER == PLAYER
    assert r.K1 == K1
    assert r.K2 == K2
    assert r.K3 == K3
    assert r.BULLET == BULLET
    assert r.BOMB == BOMB
    assert r.STAR == STAR


def test_border_row_is_exactly_border_rgb():
    frame = r.render_frame(_state(width=14, height=8))
    cells = _row(frame, 0)
    assert len(cells) == 14
    assert _colors(cells) == {BORDER}


@pytest.mark.parametrize(
    "over,color",
    [
        (dict(enemies=(_enemy(1, "F", 1, 2),)), K1),
        (dict(enemies=(_enemy(2, "F", 6, 2),)), K2),
        (dict(enemies=(_enemy(3, "F", 1, 4),)), K3),
        (dict(player_x=6, player_alive=True), PLAYER),
        (dict(bullets=((1, 6),)), BULLET),
        (dict(bombs=((6, 4),)), BOMB),
        (dict(stars=((10, 1),)), STAR),
    ],
)
def test_each_entity_uses_only_its_own_color(over, color):
    frame = r.render_frame(_state(**over))
    used = set()
    for cells in _field_grid(frame):
        used |= _colors(cells)
    assert color in used
    assert used <= {EMPTY, BORDER, color}  # no foreign palette color


def test_dead_player_is_not_drawn():
    frame = r.render_frame(_state(player_alive=False))
    used = set()
    for cells in _field_grid(frame):
        used |= _colors(cells)
    assert used == {EMPTY}  # field lines only; no entity color anywhere


# 4. Masks exact ---------------------------------------------------------------

def _row_with(width, overrides):
    row = _empty_row(width)
    for x, cell in overrides.items():
        row[x] = cell
    return row


@pytest.mark.parametrize("mode", ["F", "D"])
def test_kind1_mask_101_111(mode):
    # kind1 3x2 "101"/"111" at (3,4) -> pixel pair (4,5) -> half-block line 2.
    frame = r.render_frame(_state(enemies=(_enemy(1, mode, 3, 4),)))
    grid = _field_grid(frame)
    assert grid[2] == _row_with(
        WIDTH,
        {3: (K1, K1, TOP), 4: (EMPTY, K1, BOTTOM), 5: (K1, K1, TOP)},
    )
    # every other half-block line stays empty
    for i in (0, 1, 3):
        assert grid[i] == _empty_row()


def test_kind2_mask_111_101():
    # kind2 3x2 "111"/"101" at (6,2) -> pair (2,3) -> line 1:
    # top row all three, bottom row only the outer two.
    frame = r.render_frame(_state(enemies=(_enemy(2, "F", 6, 2),)))
    grid = _field_grid(frame)
    assert grid[1] == _row_with(
        WIDTH,
        {6: (K2, K2, TOP), 7: (K2, EMPTY, TOP), 8: (K2, K2, TOP)},
    )


def test_kind3_mask_5x3():
    # kind3 5x3 "10101"/"11111"/"01110" at (2,3) -> rows 3,4,5 -> lines 1 and 2.
    frame = r.render_frame(_state(enemies=(_enemy(3, "F", 2, 3),)))
    grid = _field_grid(frame)
    assert grid[1] == _row_with(
        WIDTH,
        {2: (EMPTY, K3, BOTTOM), 4: (EMPTY, K3, BOTTOM), 6: (EMPTY, K3, BOTTOM)},
    )
    assert grid[2] == _row_with(
        WIDTH,
        {
            2: (K3, EMPTY, TOP),
            3: (K3, K3, TOP),
            4: (K3, K3, TOP),
            5: (K3, K3, TOP),
            6: (K3, EMPTY, TOP),
        },
    )


def test_player_mask_111_010():
    # PLAYER 3x2 "111"/"010" at (5,6) -> pair (6,7) -> line 3.
    frame = r.render_frame(_state(player_x=5, player_alive=True))
    grid = _field_grid(frame)
    assert grid[3] == _row_with(
        WIDTH,
        {5: (PLAYER, EMPTY, TOP), 6: (PLAYER, PLAYER, TOP), 7: (PLAYER, EMPTY, TOP)},
    )


def test_bullet_and_bomb_masks_1x2():
    frame = r.render_frame(_state(bullets=((4, 6),), bombs=((8, 4),)))
    grid = _field_grid(frame)
    assert grid[3][4] == (BULLET, BULLET, TOP)  # bullet 1x2 "1"/"1"
    assert grid[2][8] == (BOMB, BOMB, TOP)  # bomb 1x2 "1"/"1"


def test_sprite_clipped_at_right_edge_keeps_segment_count():
    # kind1 3 wide at x = width-1: only the in-field column is drawn.
    frame = r.render_frame(_state(enemies=(_enemy(1, "F", WIDTH - 1, 4),)))
    grid = _field_grid(frame)
    assert grid[2] == _row_with(WIDTH, {WIDTH - 1: (K1, K1, TOP)})
    assert len(grid) == HEIGHT // 2  # clipping never changes the geometry


def test_sprite_clipped_at_bottom_edge_keeps_segment_count():
    # kind3 3 tall at y = height-2: the mask row below the field is dropped.
    frame = r.render_frame(_state(enemies=(_enemy(3, "F", 0, HEIGHT - 2),)))
    grid = _field_grid(frame)
    assert len(grid) == HEIGHT // 2
    assert grid[3] == _row_with(
        WIDTH,
        {
            0: (K3, K3, TOP),
            1: (EMPTY, K3, BOTTOM),
            2: (K3, K3, TOP),
            3: (EMPTY, K3, BOTTOM),
            4: (K3, K3, TOP),
        },
    )


# 5. Priority ------------------------------------------------------------------

def test_star_under_enemy_loses():
    # star at (3,2) and a kind1 anchored at (3,2): the enemy pixel wins.
    frame = r.render_frame(_state(stars=((3, 2),), enemies=(_enemy(1, "F", 3, 2),)))
    grid = _field_grid(frame)
    assert grid[1][3] == (K1, K1, TOP)
    assert STAR not in _colors(grid[1])


def test_star_alone_is_a_single_top_pixel():
    # star: a single TOP pixel of STAR color — at even or odd y alike
    # (the star occupies the top pixel of cell (x, y // 2)).
    for star_y in (2, 3):
        grid = _field_grid(r.render_frame(_state(stars=((3, star_y),))))
        assert grid[1][3] == (STAR, EMPTY, TOP)
        assert grid[1].count((EMPTY, EMPTY, " ")) == WIDTH - 1


# 6. Explosions ----------------------------------------------------------------

def test_explosion_color_by_parity_and_3x3_mask():
    st_odd = _state(enemies=(_enemy(1, "E", 3, 4, explode=3),))
    grid = _field_grid(r.render_frame(st_odd))
    # 3x3 all-ones at (3,4): rows 4,5,6 -> lines 2 and 3, color (255,140,0).
    assert grid[2] == _row_with(
        WIDTH, {3: (EXPLODE_ODD,) * 2 + (TOP,), 4: (EXPLODE_ODD,) * 2 + (TOP,), 5: (EXPLODE_ODD,) * 2 + (TOP,)}
    )
    assert grid[3] == _row_with(
        WIDTH, {3: (EXPLODE_ODD, EMPTY, TOP), 4: (EXPLODE_ODD, EMPTY, TOP), 5: (EXPLODE_ODD, EMPTY, TOP)}
    )

    st_even = _state(enemies=(_enemy(1, "E", 3, 4, explode=2),))
    grid = _field_grid(r.render_frame(st_even))
    assert grid[2][3] == (EXPLODE_EVEN, EXPLODE_EVEN, TOP)  # even -> (255,60,60)
    assert grid[2][4] == (EXPLODE_EVEN, EXPLODE_EVEN, TOP)
    assert grid[2][5] == (EXPLODE_EVEN, EXPLODE_EVEN, TOP)


def test_kind3_explosion_uses_5x3_mask():
    st = _state(enemies=(_enemy(3, "E", 2, 3, explode=4),))
    grid = _field_grid(r.render_frame(st))
    # 5x3 all-ones at (2,3): rows 3,4,5 -> lines 1 and 2, even explode -> red.
    assert grid[1] == _row_with(
        WIDTH,
        {x: (EMPTY, EXPLODE_EVEN, BOTTOM) for x in range(2, 7)},
    )
    assert grid[2] == _row_with(
        WIDTH,
        {x: (EXPLODE_EVEN, EXPLODE_EVEN, TOP) for x in range(2, 7)},
    )


# 7. No home/cursor control -----------------------------------------------------

def test_frame_has_no_home_clear_or_cursor_codes():
    st = _state(
        enemies=(_enemy(1, "F", 3, 4), _enemy(3, "E", 6, 2, explode=3)),
        bullets=((1, 6),),
        bombs=((8, 5),),
        stars=((0, 0), (11, 7)),
    )
    frame = r.render_frame(st)
    assert "\x1b[H" not in frame
    assert "\x1b[2J" not in frame
    assert "\x1b[?25" not in frame


# 8. Purity / determinism --------------------------------------------------------

def test_render_is_deterministic_and_does_not_mutate_state():
    st = _state(
        enemies=(_enemy(1, "F", 3, 4), _enemy(3, "E", 6, 2, explode=3)),
        bullets=((1, 6),),
        bombs=((8, 5),),
        stars=((0, 0), (11, 7)),
        score=999,
        wave=2,
        lives=2,
    )
    assert r.render_frame(st) == r.render_frame(st)
    snapshot = copy.deepcopy(st)
    r.render_frame(st)
    assert st == snapshot


def test_odd_height_raises_value_error():
    with pytest.raises(ValueError):
        r.render_frame(_state(height=7))


# 9. The renderer never imports the engine ---------------------------------------

def test_renderer_does_not_import_engine():
    # Drop any engine module a sibling test file may have imported, then
    # re-execute the renderer module: a renderer that imported the engine
    # would put it back into sys.modules.
    for name in ("galaxian_engine", "src.galaxian_engine"):
        sys.modules.pop(name, None)
    import importlib

    importlib.reload(r)
    assert "galaxian_engine" not in sys.modules
    assert "src.galaxian_engine" not in sys.modules
