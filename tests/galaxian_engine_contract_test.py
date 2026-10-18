"""Host-authored contract oracle for src/galaxian_engine.py (PLAN-ORACLE-PRACTICE, 2026-10-18).

Independence policy (specs/MEMO-CODE-QUALITY-ORACLES-2026-10-18.md): every
expected value here is a literal transcribed from specs/SPEC-GALAXIAN.md R1 /
docs/galaxian_engine.md — the production module is never used to COMPUTE an
expectation (it is only used to build inputs and as the subject under test).
rng literals were found offline with an independent transcription of the pinned
LCG recurrence (the same one-line formula the spec pins), and their draw values
are written out below as arithmetic comments.

Calibration (RED on mutants / GREEN on the reference tree) — executed 2026-10-18
in /tmp/oracle-lab (each mutant = a copy of the ref tree with ONE line changed
in src/galaxian_engine.py only; every mutant reddened EXACTLY its target test):
  M1  SCORE_TABLE 2:60->61            -> RED test_r1_scores_are_the_pinned_literals_30_60_80
  M2  _DIVE_MAX_PERCENT 4->5          -> RED test_r1_dive_probability_is_min_1_plus_wave_minus_1_capped_at_4
  M3  _BOMB_DROP_BASE 6->5            -> RED test_r1_diver_drops_exactly_one_bomb_at_the_pinned_threshold
  M4  removal '>='->'>'               -> RED test_r1_diver_is_removed_exactly_at_y_gte_height_minus_2
  M5  _build_form x +1                -> RED test_r1_new_game_builds_exact_16_enemy_formation
  M6  State @dataclass(frozen) plain  -> RED test_r1_state_is_frozen_and_public_functions_never_touch_inputs
  M7  respawn line dropped            -> RED test_r1_respawn_happens_exactly_after_4_ticks
  M8  new_game validations neutered   -> RED test_r1_invalid_dimensions_raise_value_error
Reference tree: 11 passed. Full evidence: STATUS.md PLAN-ORACLE-PRACTICE section.
"""

import dataclasses

import pytest

import galaxian_engine as g  # noqa: E402  (pythonpath=src)

# --------------------------------------------------------------------------
# independent transcription of the pinned LCG (SPEC-GALAXIAN R1, verbatim)
# --------------------------------------------------------------------------

def _lcg(rng):
    return (rng * 1103515245 + 12345) & 0x7FFFFFFF


def _draw(rng):
    nxt = _lcg(rng)
    return nxt, (nxt >> 16) % 100


# rng literals (found offline by scanning rng >= 0 with the transcription above;
# each comment states the independent model computation that selects it):
#   0:   _lcg(0)=12345;      (12345>>16)%100 = 0   -> first draw 0
#        2nd draw 68 -> dx = 68%3-1 = +1;           3rd draw 88 (88%4=0)
#   70:  _lcg(70)=2084151815; (>>16)%100 = 1        -> first draw 1
#   24:  _lcg(24)=714574449;  (>>16)%100 = 3        -> first draw 3
#        2nd draw 90 -> dx = 90%3-1 = -1;            3rd draw 5 (5%4=1)
#   110: (…>>16)%100 = 5                             -> first draw 5
#   172: (…>>16)%100 = 4                             -> first draw 4
#   1:   _lcg(1)=1103527590; (>>16)%100 = 38        -> first draw 38 (38%4=2)

_BASE_WIDTH = 16   # sway_max = max((16-20)//2, 0) = 0 -> no sway in hand-built states
_BASE_HEIGHT = 12  # removal line y >= 10; player anchor (player_x, 10); bullet at height-3 = 9


def _base(**overrides):
    state = g.State(
        width=_BASE_WIDTH,
        height=_BASE_HEIGHT,
        tick_count=0,
        rng_state=0,
        player_x=8,
        player_alive=True,
        cooldown=0,
        lives=3,
        score=0,
        wave=1,
        form_offset=0,
        form_dir=1,
        game_over=False,
        bullets=(),
        bombs=(),
        stars=(),
        enemies=(),
    )
    return dataclasses.replace(state, **overrides) if overrides else state


def _form_literal():
    """The 16-enemy build transcribed from SPEC-GALAXIAN R1 / docs §Simulation-8:
    rows y=2 kind3 x4, y=3 kind2 x4, y=4 kind1 x4, y=5 kind1 x4;
    x = 2 + 4*col, col 0..3; slot = (4*col, row_y - 2); mode 'F'."""
    enemies = []
    for row_y, kind in ((2, 3), (3, 2), (4, 1), (5, 1)):
        for col in range(4):
            enemies.append(
                g.Enemy(kind=kind, mode="F", x=2 + 4 * col, y=row_y,
                        slot=(4 * col, row_y - 2), dx=0, explode=0)
            )
    return tuple(enemies)


# --------------------------------------------------------------------------
# 1. Validation (negative contract)
# --------------------------------------------------------------------------

def test_r1_invalid_dimensions_raise_value_error():
    """CLAIM: width >= 12, height >= 8 and even, else ValueError (SPEC R1).
    OBSERVABLE: ValueError raised on 11-wide, 6-tall and odd-height boards;
    12x8 boundary accepted. TIER B. RED-mutant M8 (validation removed):
    no exception raised -> this test fails."""
    with pytest.raises(ValueError):
        g.new_game(42, 11, 12)
    with pytest.raises(ValueError):
        g.new_game(42, 16, 6)
    with pytest.raises(ValueError):
        g.new_game(42, 16, 13)
    ok = g.new_game(42, 12, 8)  # boundary values must be accepted
    assert (ok.width, ok.height) == (12, 8)


# --------------------------------------------------------------------------
# 2. Exact formation literals (x/slot/rows — the gap AUDIT flagged)
# --------------------------------------------------------------------------

def test_r1_new_game_builds_exact_16_enemy_formation():
    """CLAIM: build rows/kinds/x = 2 + 4*col/slots, 3 lives, wave 1,
    form_offset 0, no live projectiles (SPEC R1). OBSERVABLE: exact 16-tuple
    of Enemy values + state fields. TIER B. RED-mutant M5 (build x shifted):
    the expected x literals no longer match -> this test fails."""
    state = g.new_game(7, _BASE_WIDTH, _BASE_HEIGHT)
    assert state.enemies == _form_literal()
    assert (state.lives, state.wave, state.form_offset, state.form_dir) == (3, 1, 0, 1)
    assert (state.tick_count, state.score, state.game_over) == (0, 0, False)
    assert state.bullets == () and state.bombs == ()
    assert 1 <= state.player_x <= _BASE_WIDTH - 2


# --------------------------------------------------------------------------
# 3. SCORE_TABLE literals 30/60/80
# --------------------------------------------------------------------------

def test_r1_scores_are_the_pinned_literals_30_60_80():
    """CLAIM: SCORE_TABLE = {1: 30, 2: 60, 3: 80}; hit turns the enemy to 'E'
    explode=4 (SPEC R1). OBSERVABLE: literal dict equality + literal score
    deltas per kind (expected scores written as integers, not read from the
    module). TIER B. RED-mutant M1 (SCORE_TABLE changed): the literal score
    assertion fails."""
    assert g.SCORE_TABLE == {1: 30, 2: 60, 3: 80}
    expected = {1: 30, 2: 60, 3: 80}
    for kind, expected_score in expected.items():
        # rng 1: first draw 38 (38%4=2) -> threshold 6+2=8; the diver reaches
        # y=6 only -> no bomb this tick. bullet (5,7) -> (5,6) meets anchor (5,6).
        state = _base(
            rng_state=1,
            bullets=((5, 7),),
            enemies=(g.Enemy(kind=kind, mode="D", x=5, y=5, slot=(0, 0), dx=0, explode=0),),
        )
        result = g.tick(state)
        assert result.score == expected_score
        assert result.enemies == (
            g.Enemy(kind=kind, mode="E", x=5, y=6, slot=(0, 0), dx=0, explode=4),
        )
        assert result.bullets == () and result.bombs == ()


# --------------------------------------------------------------------------
# 4. Deep purity: frozen values, inputs untouched, immutable sequences
# --------------------------------------------------------------------------

def test_r1_state_is_frozen_and_public_functions_never_touch_inputs():
    """CLAIM: State/Enemy are frozen; all functions return new States and do
    not mutate the input (SPEC R1 "Все функции НЕ мутируют вход").
    OBSERVABLE: FrozenInstanceError on attribute assignment; input field values
    identical before/after each call; every sequence field of every returned
    State is a tuple. TIER B. RED-mutant M6 (frozen=False / shared mutable
    containers leaked): the raises-assertion fails."""
    state = _base(bullets=((8, 9),), enemies=(_form_literal()[0],))
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.player_x = 7
    with pytest.raises(dataclasses.FrozenInstanceError):
        state.enemies[0].mode = "D"
    before = dataclasses.asdict(state)
    for result in (g.move(state, 1), g.fire(state), g.tick(state)):
        assert dataclasses.asdict(state) == before
        for field in ("bullets", "bombs", "stars", "enemies"):
            assert isinstance(getattr(result, field), tuple)
            for item in getattr(result, field):
                if dataclasses.is_dataclass(item):
                    with pytest.raises(dataclasses.FrozenInstanceError):
                        item.kind = 99


# --------------------------------------------------------------------------
# 5. Dive probability p(wave) = min(1 + (wave-1), 4), boundary-exact
# --------------------------------------------------------------------------

def test_r1_dive_probability_is_min_1_plus_wave_minus_1_capped_at_4():
    """CLAIM: an 'F' enemy dives iff its LCG draw < min(1+(wave-1),4) percent
    (SPEC R1). OBSERVABLE: boundary pairs — draw p-1 dives, draw p never
    dives, pinned at wave 1 (p=1), wave 4 (p=4) and wave 6 (cap: p=4); the
    newly created 'D' continues moving in the same tick (y+1, x+dx from the
    second draw). TIER B. RED-mutants M2: threshold shift (e.g. base 1->2)
    flips the wave-1/draw-1 pair; cap removal (4->5) flips the wave-6/draw-4
    pair -> this test fails."""
    diver = g.Enemy(kind=2, mode="F", x=6, y=2, slot=(4, 0), dx=0, explode=0)

    def dive_case(rng, wave, dx, new_x):
        result = g.tick(_base(rng_state=rng, wave=wave, enemies=(diver,)))
        assert result.enemies == (
            g.Enemy(kind=2, mode="D", x=new_x, y=3, slot=(4, 0), dx=dx, explode=0),
        )
        assert result.bombs == ()  # 3rd draw: rng0 -> 88%4=0 (threshold 6 != 3);
                                   # rng24 -> 5%4=1 (threshold 7 != 3)

    def no_dive_case(rng, wave):
        result = g.tick(_base(rng_state=rng, wave=wave, enemies=(diver,)))
        assert result.enemies == (diver,)
        assert result.bombs == ()

    dive_case(0, 1, dx=1, new_x=7)     # first draw 0  < 1; 2nd draw 68 -> dx +1
    no_dive_case(70, 1)                # first draw 1 !< 1
    dive_case(24, 4, dx=-1, new_x=5)   # first draw 3  < 4; 2nd draw 90 -> dx -1
    no_dive_case(110, 4)               # first draw 5 !< 4
    dive_case(24, 6, dx=-1, new_x=5)   # cap: min(1+5,4) = 4; 3 < 4
    no_dive_case(172, 6)               # first draw 4 !< 4 — pins the cap at 4


# --------------------------------------------------------------------------
# 6. Bomb drop exactly at y == 6 + draw % 4, at (x, y+2)
# --------------------------------------------------------------------------

def test_r1_diver_drops_exactly_one_bomb_at_the_pinned_threshold():
    """CLAIM: a 'D' diver drops one bomb at (x, y+2) when its new y equals
    6 + draw%4, and none otherwise (SPEC R1, docs §Simulation-5).
    OBSERVABLE: exact bombs tuple. TIER B. RED-mutant M3 (threshold base 6->5):
    case A loses its expected bomb and case B gains an unexpected one ->
    this test fails."""
    diver = g.Enemy(kind=1, mode="D", x=4, y=5, slot=(0, 0), dx=0, explode=0)
    # A: rng 0 -> first draw 0 -> threshold 6; new y = 6 -> bomb at (4, 8)
    result = g.tick(_base(rng_state=0, enemies=(diver,)))
    assert result.enemies == (
        g.Enemy(kind=1, mode="D", x=4, y=6, slot=(0, 0), dx=0, explode=0),
    )
    assert result.bombs == ((4, 8),)
    # B: rng 70 -> first draw 1 -> threshold 7; new y = 6 -> no bomb
    result = g.tick(_base(rng_state=70, enemies=(diver,)))
    assert result.bombs == ()
    assert result.enemies == (
        g.Enemy(kind=1, mode="D", x=4, y=6, slot=(0, 0), dx=0, explode=0),
    )


# --------------------------------------------------------------------------
# 7. Diver removal at y >= height - 2
# --------------------------------------------------------------------------

def test_r1_diver_is_removed_exactly_at_y_gte_height_minus_2():
    """CLAIM: y >= height-2 removes the diver (SPEC R1). OBSERVABLE: a diver
    reaching y = height-2 is gone; one at y = height-3 survives at the exact
    literal position; no side effects on the survivor. TIER B. RED-mutant M4
    (>= -> >): the removed diver stays at y=10 -> the exact survivor tuple
    no longer matches -> this test fails."""
    # rng 0: draws 0 and 68 (both %4 == 0 -> threshold 6, never crossed here)
    divers = (
        g.Enemy(kind=1, mode="D", x=3, y=9, slot=(0, 0), dx=0, explode=0),   # -> y 10 -> removed
        g.Enemy(kind=1, mode="D", x=4, y=8, slot=(0, 0), dx=0, explode=0),   # -> y 9  -> survives
    )
    result = g.tick(_base(rng_state=0, enemies=divers))
    assert result.enemies == (
        g.Enemy(kind=1, mode="D", x=4, y=9, slot=(0, 0), dx=0, explode=0),
    )
    assert result.bombs == ()


# --------------------------------------------------------------------------
# 8. Respawn exactly 4 ticks after the hit
# --------------------------------------------------------------------------

def test_r1_respawn_happens_exactly_after_4_ticks():
    """CLAIM: a hit sets lives-1, cooldown=4; respawn only after the 4
    FOLLOWING ticks (docs §Simulation-1). OBSERVABLE: exact
    (cooldown, player_alive) sequence 3/F, 2/F, 1/F, 0/True. TIER B.
    RED-mutant M7 (respawn removed): tick 4 keeps player_alive False ->
    this test fails."""
    state = _base(player_alive=False, cooldown=4, lives=3)
    expected = [(3, False), (2, False), (1, False), (0, True)]
    for cooldown, alive in expected:
        state = g.tick(state)
        assert (state.cooldown, state.player_alive) == (cooldown, alive)
        assert state.lives == 3  # no further life loss was caused here


# --------------------------------------------------------------------------
# 9. Game-over lifecycle: last life -> frozen state
# --------------------------------------------------------------------------

def test_r1_last_life_lost_ends_the_game_and_freezes_all_functions():
    """CLAIM: bomb on the player anchor -> lives-1; lives==0 -> game_over;
    afterwards move/fire/tick are no-ops (SPEC R1). OBSERVABLE: exact field
    values at the hit tick and state equality for post-game calls.
    TIER B. (no assigned mutant — lifecycle claim pinned directly)."""
    state = _base(
        lives=1,
        player_x=6,
        bombs=((6, 9),),  # falls to (6, 10) == anchor (player_x, height-2)
    )
    result = g.tick(state)
    assert (result.lives, result.player_alive, result.cooldown) == (0, False, 4)
    assert result.bombs == ()
    assert result.game_over is True
    assert g.is_game_over(result) is True
    assert g.tick(result) == result
    assert g.move(result, 1) == result
    assert g.fire(result) == result


# --------------------------------------------------------------------------
# 10. Negative branches: clamped move / refused fire are exact equivalents
# --------------------------------------------------------------------------

def test_r1_clamped_moves_and_refused_fire_return_equivalent_states():
    """CLAIM: dx not in {-1,1}, moves clamped to [1, width-2], refused fire
    (bullet exists / cooldown != 0 / player dead) return a state equivalent
    to the input, tick_count included (docs API section). OBSERVABLE: full
    dataclass equality; a legal fire puts the bullet exactly at
    (player_x, height-3) without bumping tick_count. TIER B.
    (no assigned mutant — negative-branch claims pinned directly)."""
    base = _base(tick_count=5, player_x=8)
    for bad_dx in (0, 2, -2):
        assert g.move(base, bad_dx) == base

    at_left = dataclasses.replace(base, player_x=1)
    at_right = dataclasses.replace(base, player_x=_BASE_WIDTH - 2)
    assert g.move(at_left, -1) == at_left
    assert g.move(at_right, 1) == at_right

    fired = _base(bullets=((8, 9),))
    assert g.fire(fired) == fired
    cooling = _base(cooldown=3)
    assert g.fire(cooling) == cooling
    dead = _base(player_alive=False)
    assert g.fire(dead) == dead

    legal = g.fire(base)
    assert legal.bullets == ((8, _BASE_HEIGHT - 3),)
    assert legal.tick_count == base.tick_count


# --------------------------------------------------------------------------
# 11. Pinned LCG stream + new_game determinism
# --------------------------------------------------------------------------

def test_r1_lcg_stream_matches_the_pinned_formula_and_new_game_is_deterministic():
    """CLAIM: rng_state = (rng_state*1103515245 + 12345) & 0x7FFFFFFF,
    draw = (rng_state >> 16) % 100; one seed -> identical trajectory;
    stars: width//4 of them inside the field (SPEC R1). OBSERVABLE: literal
    chain values from the independent transcription; production helpers must
    match them; identical calls to new_game produce equal states; different
    seeds diverge; star count/bounds exact. TIER B. (no assigned mutant —
    the recurrence is pinned here for completeness of the ladder)."""
    # literals from the transcription, hand-checked arithmetic:
    assert _lcg(0) == 12345
    assert _draw(0)[1] == 0
    assert _draw(70)[1] == 1
    assert _draw(24)[1] == 3
    assert _draw(110)[1] == 5
    assert _draw(172)[1] == 4
    for value in (0, 70, 24, 110, 172, 1, 12345):
        assert g.lcg_next(value) == _lcg(value)
        assert g.lcg_draw(value) == _draw(value)

    a = g.new_game(42, _BASE_WIDTH, _BASE_HEIGHT)
    b = g.new_game(42, _BASE_WIDTH, _BASE_HEIGHT)
    assert a == b
    assert a != g.new_game(43, _BASE_WIDTH, _BASE_HEIGHT)
    assert len(a.stars) == _BASE_WIDTH // 4
    for x, y in a.stars:
        assert 0 <= x < _BASE_WIDTH
        assert 0 <= y < _BASE_HEIGHT - 2
