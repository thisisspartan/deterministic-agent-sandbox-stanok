"""CC-293 — galaxian_engine reference tests.

The contract (docs/galaxian_engine.md): a pure, seed-deterministic Galaxian
engine. Only pure calls — no subprocess, no PTY, no time.

Synthetic states use a sentinel 'E' enemy (huge explode) where a live enemy
is needed to prevent wave-rebuild: 'E' enemies consume no LCG draws and are
never hit by bullets, so they make the synthetic scenarios deterministic.
"""

import dataclasses

import pytest

import galaxian_engine as g  # noqa: F401  (pythonpath=src)

from src import galaxian_engine as g  # noqa: F401,E111  (namespace-package form)

WIDTH, HEIGHT = 12, 8
SEED = 7


def _sentinel(explode=10**9):
    # A never-dying 'E' enemy: blocks wave-rebuild, consumes no LCG draws,
    # cannot be hit (collisions apply to 'F'/'D' only).
    return g.Enemy(kind=1, mode="E", x=0, y=0, slot=(99, 99), dx=0, explode=explode)


def _no_dive_rng(chance=1, count=1):
    """Deterministically find an rng_state whose next `count` draws are all >= chance."""
    rng = 1
    while True:
        r, ok = rng, True
        for _ in range(count):
            r, draw = g.lcg_draw(r)
            if draw < chance:
                ok = False
                break
        if ok:
            return rng
        rng += 1


def _synthetic(**overrides):
    state = g.new_game(SEED, WIDTH, HEIGHT)
    return dataclasses.replace(state, **overrides)


# 1. Determinism -----------------------------------------------------------------

def test_same_seed_identical_trajectory():
    a = g.new_game(SEED, WIDTH, HEIGHT)
    b = g.new_game(SEED, WIDTH, HEIGHT)
    assert a == b
    for _ in range(30):
        for step in (g.move, g.fire, g.tick):
            a = step(a, 1) if step is g.move else step(a)
            b = step(b, 1) if step is g.move else step(b)
        a, b = g.tick(a), g.tick(b)
    assert a == b


@pytest.mark.parametrize("seed_a,seed_b", [(7, 42), (1, 36)])
def test_different_seeds_diverge_within_200_ticks(seed_a, seed_b):
    a = g.new_game(seed_a, WIDTH, HEIGHT)
    b = g.new_game(seed_b, WIDTH, HEIGHT)
    for _ in range(200):
        a, b = g.tick(a), g.tick(b)
        if a.enemies != b.enemies or a.form_offset != b.form_offset:
            return
    pytest.fail("trajectories did not diverge within 200 ticks")


# 2. Purity ----------------------------------------------------------------------

def test_functions_do_not_mutate_input_and_return_new_objects():
    state = _synthetic(
        enemies=(_sentinel(explode=5), g.Enemy(kind=1, mode="F", x=2, y=4, slot=(0, 2))),
        bullets=(),
        bombs=(),
        rng_state=_no_dive_rng(),
    )
    snapshot = dataclasses.replace(state)  # frozen: an independent equal copy

    moved = g.move(state, 1)
    assert state == snapshot  # input untouched
    assert moved is not state and moved.player_x == state.player_x + 1

    fired = g.fire(state)
    assert state == snapshot
    assert fired is not state and fired.bullets == ((state.player_x, HEIGHT - 3),)

    fired_snapshot = dataclasses.replace(fired)
    ticked = g.tick(fired)
    assert fired == fired_snapshot  # the fired state is untouched by tick either
    assert ticked is not fired

    # Changed enemies are NEW objects, not shared with the input state.
    old_sentinel = next(e for e in fired.enemies if e.slot == (99, 99))
    new_sentinel = next(e for e in ticked.enemies if e.slot == (99, 99))
    assert new_sentinel is not old_sentinel
    assert new_sentinel.explode == old_sentinel.explode - 1
    # The bullet moved: a new tuple, and the fired state's tuple is untouched.
    assert ticked.bullets == ((state.player_x, HEIGHT - 4),)
    assert fired.bullets == ((state.player_x, HEIGHT - 3),)


# 3. Validation -------------------------------------------------------------------

@pytest.mark.parametrize(
    "kwargs",
    [
        dict(seed=1, width=12, height=7),   # odd height
        dict(seed=1, width=12, height=6),   # height < 8
        dict(seed=1, width=11, height=8),   # width < 12
    ],
)
def test_bad_dimensions_raise_value_error(kwargs):
    with pytest.raises(ValueError):
        g.new_game(**kwargs)


def test_minimal_valid_board():
    state = g.new_game(1, 12, 8)
    assert state.width == 12 and state.height == 8


# 4. Move clamping -----------------------------------------------------------------

def test_move_clamps_at_field_edges():
    state = g.new_game(SEED, WIDTH, HEIGHT)
    for _ in range(50):
        state = g.move(state, 1)
    assert state.player_x == WIDTH - 2
    clamped = g.move(state, 1)
    assert clamped == state  # invalid move: equivalent state, no tick_count change
    for _ in range(50):
        state = g.move(state, -1)
    assert state.player_x == 1
    assert g.move(state, -1) == state


# 5. Fire --------------------------------------------------------------------------

def test_fire_makes_exactly_one_bullet():
    state = g.new_game(SEED, WIDTH, HEIGHT)
    fired = g.fire(state)
    assert fired.bullets == ((state.player_x, HEIGHT - 3),)
    again = g.fire(fired)
    assert again.bullets == fired.bullets  # no second bullet
    cooling = _synthetic(cooldown=2)
    assert g.fire(cooling).bullets == ()
    dead = _synthetic(player_alive=False)
    assert g.fire(dead).bullets == ()


# 6. Projectile movement -------------------------------------------------------------

def test_bullet_moves_up_and_exits_top_bomb_moves_down_and_exits_bottom():
    state = _synthetic(enemies=(_sentinel(),), bullets=((6, 3),), bombs=((6, 6),))
    cur = state
    for n in (1, 2, 3):
        cur = g.tick(cur)
        assert cur.bullets == ((6, 3 - n),)
    cur = g.tick(cur)  # y would become -1 -> removed
    assert cur.bullets == ()

    cur = _synthetic(enemies=(_sentinel(),), bombs=((6, 6),))
    cur = g.tick(cur)
    assert cur.bombs == ((6, 7),)
    cur = g.tick(cur)  # y would become 8 >= height -> removed
    assert cur.bombs == ()


# 7. Bullet x enemy ------------------------------------------------------------------

def test_bullet_kills_enemy_explodes_and_scores():
    target = g.Enemy(kind=2, mode="F", x=6, y=4, slot=(4, 2))
    state = _synthetic(
        enemies=(_sentinel(), target),
        bullets=((6, 5),),
        bombs=(),
        rng_state=_no_dive_rng(),
    )
    hit = g.tick(state)
    struck = next(e for e in hit.enemies if e.slot == (4, 2))
    assert struck.mode == "E" and struck.explode == 4
    assert hit.score == g.SCORE_TABLE[2]
    assert hit.bullets == ()
    cur = hit
    for _ in range(4):
        cur = g.tick(cur)
    assert not any(e.slot == (4, 2) for e in cur.enemies)  # removed
    assert cur.score == g.SCORE_TABLE[2]  # score unchanged by the explosion ticks


# 8. Bullet x bomb --------------------------------------------------------------------

def test_bullet_and_bomb_annihilate_each_other():
    # They start two cells apart and meet in the middle after moving.
    state = _synthetic(enemies=(_sentinel(),), bullets=((6, 4),), bombs=((6, 2),))
    hit = g.tick(state)
    assert hit.bullets == () and hit.bombs == ()
    assert hit.score == 0


# 9. Bomb x player ---------------------------------------------------------------------

def _hit_player(state):
    state = dataclasses.replace(state, bombs=((state.player_x, HEIGHT - 3),))
    return g.tick(state)


def test_bomb_hits_player_respawns_and_game_over_freezes_everything():
    state = g.new_game(SEED, WIDTH, HEIGHT)
    assert state.lives == 3

    state = _hit_player(state)
    assert state.lives == 2 and state.player_alive is False and state.cooldown == 4
    for _ in range(4):
        state = g.tick(state)
    assert state.player_alive is True and state.cooldown == 0

    state = _hit_player(state)
    assert state.lives == 1
    for _ in range(4):
        state = g.tick(state)
    state = _hit_player(state)
    assert state.lives == 0 and g.is_game_over(state) is True

    frozen = state
    assert g.move(frozen, 1) == frozen
    assert g.fire(frozen) == frozen
    assert g.tick(frozen) == frozen
    assert g.tick(frozen).tick_count == frozen.tick_count


# 10. Form sway ------------------------------------------------------------------------

def test_form_offset_stays_in_bounds_and_reaches_both_ends():
    width = 32
    sway_max = max((width - 20) // 2, 0)
    assert sway_max > 0
    state = g.new_game(5, width, 8)
    seen_offsets, seen_dirs = set(), set()
    for _ in range(200):
        state = g.tick(state)
        assert 0 <= state.form_offset <= sway_max
        seen_offsets.add(state.form_offset)
        seen_dirs.add(state.form_dir)
    assert 0 in seen_offsets and sway_max in seen_offsets
    assert seen_dirs == {1, -1}  # form_dir flipped at both boundaries


# 11. Dives ------------------------------------------------------------------------------

def test_dives_are_single_rare_and_bounce_off_the_left_wall():
    state = g.new_game(1, WIDTH, HEIGHT)
    ever_dived = False
    bounced_left = False
    for _ in range(1000):
        prev = state
        state = g.tick(state)
        prev_by_slot = {}
        for e in prev.enemies:
            prev_by_slot.setdefault(e.slot, []).append(e.mode)
        new_divers = [
            e
            for e in state.enemies
            if e.mode == "D" and "D" not in prev_by_slot.get(e.slot, [])
        ]
        assert len(new_divers) <= 1  # at most one new 'D' per tick
        for d in new_divers:
            ever_dived = True
            assert "F" in prev_by_slot.get(d.slot, [])  # every new 'D' came from an 'F'
        for e in state.enemies:
            if e.mode == "D" and e.x == 0 and e.dx == 1:
                bounced_left = True
    assert ever_dived
    assert bounced_left


# 12. Wave rebuild -------------------------------------------------------------------------

def test_wave_rebuilds_full_formation_after_last_enemy_dies():
    last = g.Enemy(kind=1, mode="E", x=4, y=4, slot=(2, 2), dx=0, explode=1)
    state = _synthetic(enemies=(last,), bullets=((4, 1),), bombs=((4, 4),), wave=1)
    nxt = g.tick(state)
    assert nxt.wave == 2
    assert len(nxt.enemies) == 16
    assert all(e.mode == "F" for e in nxt.enemies)
    by_row = {}
    for e in nxt.enemies:
        by_row.setdefault(e.y, set()).add(e.kind)
    assert by_row == {2: {3}, 3: {2}, 4: {1}, 5: {1}}
    assert nxt.bullets == () and nxt.bombs == ()


# 13. LCG ----------------------------------------------------------------------------------

def test_lcg_step_matches_the_pinned_formula_and_draw_is_a_percentage():
    for rng in (0, 1, 123456789, 0x7FFFFFFF):
        assert g.lcg_next(rng) == (rng * 1103515245 + 12345) & 0x7FFFFFFF
    for probe in range(0, 20000, 7):
        _, draw = g.lcg_draw(probe)
        assert 0 <= draw <= 99


# 14. Stars ---------------------------------------------------------------------------------

def test_stars_are_regenerated_each_tick_within_bounds():
    base = _synthetic(enemies=(_sentinel(),))
    a = g.tick(dataclasses.replace(base, rng_state=100))
    b = g.tick(dataclasses.replace(base, rng_state=999999))
    assert len(a.stars) == WIDTH // 4 and len(b.stars) == WIDTH // 4
    for x, y in a.stars + b.stars:
        assert 0 <= x < WIDTH and 0 <= y < HEIGHT - 2
    assert a.stars != b.stars  # stars follow the LCG stream, not a constant
    cur = a
    for _ in range(5):
        cur = g.tick(cur)
        assert len(cur.stars) == WIDTH // 4
