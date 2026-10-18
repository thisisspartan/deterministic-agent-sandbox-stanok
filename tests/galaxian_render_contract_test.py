"""Host-authored contract oracle for src/galaxian_render.py (PLAN-ORACLE-PRACTICE, 2026-10-18).

Independence policy (specs/MEMO-CODE-QUALITY-ORACLES-2026-10-18.md): every
expected value is a literal transcribed from docs/galaxian_render.md (palette,
masks, half-block rules, status format) or hand-computed pixel plans for a
hand-built state. The renderer module is only the SUBJECT; the engine module is
NOT imported at all (states are local dataclasses, as the render contract says
the renderer itself is duck-typed). The expected-value model in this test is a
spec transcription, not a call into production code.

Calibration (RED on mutants / GREEN on the reference tree) — executed 2026-10-18
in /tmp/oracle-lab (each mutant = a copy of the ref tree with ONE line changed
in src/galaxian_render.py only; every mutant reddened EXACTLY its target test):
  M15 line 17 K1=(0,200,0)->(0,200,1)      -> RED test_r2_palette_constants_and_k1_on_wire_are_the_pinned_literals (assert (0,200,1)==(0,200,0), index 2)
  M16 line 120 return joined(parts)+_RESET dropped -> RED test_r2_hand_computed_scene_encodes_segment_for_segment (lines[1] missing the trailing reset)
Reference tree: 9 passed (rc=0). Full evidence: STATUS.md PLAN-ORACLE-PRACTICE section.

Design note: only the segment-for-segment composition test pins whole exact
lines (including the trailing RESET); every other test inspects parsed
segments/counts so a reset mutation reddens exactly one target test.
"""

import copy
import dataclasses
import re

import pytest

import galaxian_render as r  # noqa: E402  (pythonpath=src)

# ---------------------------------------------------------------------------
# independent transcription of the pinned frame model (docs/galaxian_render.md)
# ---------------------------------------------------------------------------

# palette literals, transcribed from the published contract (not read from r.*)
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
STATUS_FG = (220, 220, 220)
STATUS_BG = (0, 0, 0)

TOP = "\u2580"  # ▀ top half block (docs/galaxian_render.md pins "\u2580")
BOTTOM = "\u2584"  # ▄ bottom half block (docs pin "\u2584")
RESET = "\x1b[0m"

SEG_RE = re.compile(
    "\x1b\\[38;2;(\\d+);(\\d+);(\\d+)m"
    "\x1b\\[48;2;(\\d+);(\\d+);(\\d+)m"
    "(.)",
    re.DOTALL,
)


def _sgr(fg, bg):
    return f"\x1b[38;2;{fg[0]};{fg[1]};{fg[2]}m\x1b[48;2;{bg[0]};{bg[1]};{bg[2]}m"


def _empty_cell():
    return _sgr(EMPTY, EMPTY) + " "


def _row(width, *specs):
    """Build an expected half-block row from a hand-computed cell plan.

    specs: (x, fg, bg, glyph); all other columns are the empty cell."""
    cells = [_empty_cell() for _ in range(width)]
    for x, fg, bg, glyph in specs:
        cells[x] = _sgr(fg, bg) + glyph
    return "".join(cells) + RESET


def _segments(line):
    return [
        ((int(m[0]), int(m[1]), int(m[2])), (int(m[3]), int(m[4]), int(m[5])), m[6])
        for m in SEG_RE.findall(line)
    ]


@dataclasses.dataclass(frozen=True)
class _Enemy:
    kind: int
    mode: str
    x: int
    y: int
    explode: int = 0


@dataclasses.dataclass
class _State:
    width: int
    height: int
    player_x: int
    player_alive: bool
    score: int = 0
    wave: int = 1
    lives: int = 3
    bullets: tuple = ()
    bombs: tuple = ()
    stars: tuple = ()
    enemies: tuple = ()


# hand-built scene S1: width=12, height=8 (6 lines: border + 4 half rows + status)
# painted pixels (computed by hand from the pinned masks BEFORE seeing output):
#   stars first: (5,1)->row0 x5; (9,5)->row4 x9; (6,5)->row4 x6 (overridden by K3)
#   kind3 F at (4,2): row2 x4,6,8; row3 x4..8; row4 x5,6,7
#   kind2 F at (0,4): row4 x0,1,2; row5 x0,2
#   bullet (10,4): row4+5 x10;  bomb (11,0): row0+1 x11
#   player at (6,6): row6 x6,7,8; row7 x7
def _scene_s1():
    return _State(
        width=12,
        height=8,
        player_x=6,
        player_alive=True,
        score=42,
        wave=2,
        lives=3,
        stars=((9, 5), (6, 5), (5, 1)),
        enemies=(_Enemy(3, "F", 4, 2), _Enemy(2, "F", 0, 4)),
        bullets=((10, 4),),
        bombs=((11, 0),),
    )


# ---------------------------------------------------------------------------
# T1 — palette constants AND the kind-1 colour on the wire (M15)
# ---------------------------------------------------------------------------

def test_r2_palette_constants_and_k1_on_wire_are_the_pinned_literals():
    assert r.EMPTY == (10, 10, 16)
    assert r.BORDER == (60, 60, 90)
    assert r.PLAYER == (235, 235, 235)
    assert r.K1 == (0, 200, 0)
    assert r.K2 == (0, 180, 220)
    assert r.K3 == (255, 60, 60)
    assert r.BULLET == (235, 235, 235)
    assert r.BOMB == (255, 220, 80)
    assert r.STAR == (90, 90, 110)
    assert r.EXPLODE_ODD == (255, 140, 0)
    assert r.EXPLODE_EVEN == (255, 60, 60)

    # on-wire: a kind-1 enemy at (4,4): mask "101"/"111" -> row4 x4,x6;
    # row5 x4,x5,x6. Encoded pair (4,5):
    #   x4 both -> ▀ K1/K1;  x5 bottom-only -> ▄ EMPTY/K1;  x6 both -> ▀ K1/K1
    st = _State(width=12, height=8, player_x=6, player_alive=False,
                enemies=(_Enemy(1, "F", 4, 4),))
    frame = r.render_frame(st)
    row = frame.split("\n")[3]
    segs = _segments(row)
    assert segs[4] == (K1, K1, TOP)
    assert segs[5] == (EMPTY, K1, BOTTOM)
    assert segs[6] == (K1, K1, TOP)


# ---------------------------------------------------------------------------
# T2 — the hand-computed scene, segment for segment, whole exact lines (M16)
# ---------------------------------------------------------------------------

def test_r2_hand_computed_scene_encodes_segment_for_segment():
    frame = r.render_frame(_scene_s1())
    lines = frame.split("\n")

    # line 0: the border — width segments, fg == bg == BORDER, glyph " "
    expected_border = "".join(_sgr(BORDER, BORDER) + " " for _ in range(12)) + RESET
    assert lines[0] == expected_border

    # line 1 = pixel pair (0,1): star at row0 x5 (top-only); bomb 1x2 at x11 (both)
    assert lines[1] == _row(
        12,
        (5, STAR, EMPTY, TOP),
        (11, BOMB, BOMB, TOP),
    )

    # line 2 = pair (2,3): kind3 mask rows "10101"/"11111"
    assert lines[2] == _row(
        12,
        (4, K3, K3, TOP),
        (5, EMPTY, K3, BOTTOM),
        (6, K3, K3, TOP),
        (7, EMPTY, K3, BOTTOM),
        (8, K3, K3, TOP),
    )

    # line 3 = pair (4,5): kind2 top+bottom, kind3 row "01110" overwriting a
    # star at x6 (priority), surviving star at x9, bullet both, bomb rows 0/1 only
    assert lines[3] == _row(
        12,
        (0, K2, K2, TOP),
        (1, K2, EMPTY, TOP),
        (2, K2, K2, TOP),
        (5, K3, EMPTY, TOP),
        (6, K3, EMPTY, TOP),
        (7, K3, EMPTY, TOP),
        (9, STAR, EMPTY, TOP),
        (10, BULLET, BULLET, TOP),
    )

    # line 4 = pair (6,7): player mask "111"/"010"
    assert lines[4] == _row(
        12,
        (6, PLAYER, EMPTY, TOP),
        (7, PLAYER, PLAYER, TOP),
        (8, PLAYER, EMPTY, TOP),
    )

    # line 5 = status truncated to width 12, exactly one SGR prefix + one reset
    status_text = "SC 000042  L"  # f"SC 42:06d..." = "SC 000042  LV 02  LIVES 3"[:12]
    assert lines[5] == _sgr(STATUS_FG, STATUS_BG) + status_text + RESET

    # every line of the frame terminates with exactly one RESET
    assert all(line.endswith(RESET) for line in lines)


# ---------------------------------------------------------------------------
# T3 — frame shape: line count, per-line width segments, never home/clear/hide
# ---------------------------------------------------------------------------

def test_r2_frame_has_exact_line_count_width_segments_and_no_home_clear_hide():
    frame = r.render_frame(_scene_s1())
    lines = frame.split("\n")
    assert len(lines) == 8 // 2 + 2  # 6 lines
    assert not frame.endswith("\n")  # joined, no trailing newline
    for line in lines:
        assert "\x1b[H" not in line and "\x1b[2J" not in line and "\x1b[?25" not in line
    for line in lines[0:5]:  # border + half rows are exactly `width` segments
        assert len(_segments(line)) == 12
    # status line: at most one SGR prefix
    status = lines[5]
    assert status.count("\x1b[38;2;") == 1
    assert status.count("\x1b[48;2;") == 1


# ---------------------------------------------------------------------------
# T4 — status line padding: ljust to width when narrower (never truncated)
# ---------------------------------------------------------------------------

def test_r2_status_line_is_padded_to_width_when_text_is_shorter():
    st = _State(width=40, height=8, player_x=20, player_alive=False,
                score=42, wave=2, lives=3)
    status = r.render_frame(st).split("\n")[-1]
    prefix = _sgr(STATUS_FG, STATUS_BG)
    assert status.startswith(prefix)
    expected_text = "SC 000042  LV 02  LIVES 3".ljust(40)
    body = status[len(prefix):].rstrip("\x1b[0m")  # ignore the trailing reset token
    assert body == expected_text
    assert status.count("\x1b[38;2;") == 1  # at most one SGR prefix


# ---------------------------------------------------------------------------
# T5 — explosion rendering: 3x3 / 5x3 all-ones masks, parity colours
# ---------------------------------------------------------------------------

def test_r2_explosion_masks_and_parity_colors_are_pinned():
    st = _State(width=12, height=8, player_x=6, player_alive=False,
                enemies=(_Enemy(1, "E", 2, 3, 1), _Enemy(3, "E", 6, 1, 2)))
    # kind1 'E' at (2,3), explode=1 -> 3x3 all-ones rows 3,4,5 color EXPLODE_ODD
    # kind3 'E' at (6,1), explode=2 -> 5x3 all-ones rows 1,2,3 color EXPLODE_EVEN
    lines = r.render_frame(st).split("\n")
    segs = _segments(lines[2])  # pair (2,3)
    # bottom-only pixels of kind1 explosion at row3 x2,x3,x4
    for x in (2, 3, 4):
        assert segs[x] == (EMPTY, EXPLODE_ODD, BOTTOM)
    # both pixels rows2/3 of kind3 explosion x6..10
    for x in range(6, 11):
        assert segs[x] == (EXPLODE_EVEN, EXPLODE_EVEN, TOP)
    segs3 = _segments(lines[3])  # pair (4,5): top row4 x2..4 of kind1
    for x in (2, 3, 4):
        assert segs3[x] == (EXPLODE_ODD, EXPLODE_ODD, TOP)


# ---------------------------------------------------------------------------
# T6 — odd height is rejected
# ---------------------------------------------------------------------------

def test_r2_odd_height_raises_value_error():
    st = _State(width=12, height=7, player_x=6, player_alive=False)
    with pytest.raises(ValueError):
        r.render_frame(st)


# ---------------------------------------------------------------------------
# T7 — purity: the state is never mutated; identical input -> identical output
# ---------------------------------------------------------------------------

def test_r2_rendering_is_pure_and_deterministic():
    st = _scene_s1()
    before = dataclasses.asdict(st)
    first = r.render_frame(st)
    after = dataclasses.asdict(st)
    assert after == before  # no mutation (enemies/bullets/bombs/stars untouched)
    second = r.render_frame(copy.deepcopy(st))
    assert first == second


# ---------------------------------------------------------------------------
# T8 — masks may extend past the field: clipped, never raises, width preserved
# ---------------------------------------------------------------------------

def test_r2_masks_past_the_field_are_clipped_without_changing_segment_count():
    # kind3 at x=10, width=12: mask columns 12..14 are outside -> clipped
    st = _State(width=12, height=8, player_x=6, player_alive=False,
                enemies=(_Enemy(3, "F", 10, 2),))
    lines = r.render_frame(st).split("\n")
    for line in lines[0:5]:
        assert len(_segments(line)) == 12  # segment count per line never changes


# ---------------------------------------------------------------------------
# T9 — player_alive=False renders no player pixels
# ---------------------------------------------------------------------------

def test_r2_dead_player_is_not_rendered():
    st = _State(width=12, height=8, player_x=6, player_alive=False)
    lines = r.render_frame(_scene_s1()).split("\n")
    with_player = [seg for line in lines[1:5] for seg in _segments(line)]
    # the live scene has PLAYER segments
    assert any(seg[0] == PLAYER for seg in with_player)
    dead = r.render_frame(st).split("\n")
    dead_segs = [seg for line in dead[1:5] for seg in _segments(line)]
    assert not any(seg[0] == PLAYER or seg[1] == PLAYER for seg in dead_segs)
