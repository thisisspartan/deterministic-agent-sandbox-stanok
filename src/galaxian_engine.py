"""galaxian_engine — a pure, seed-deterministic Galaxian engine (CC-293).

stdlib only; no time, no I/O, no global mutable state. Every pinned function
(new_game/move/fire/tick/is_game_over) is non-mutating: it returns a NEW
State (or an equivalent one for no-op calls). All game randomness (dives,
bombs, stars) flows from a single pinned LCG stream. See docs/galaxian_engine.md.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

SCORE_TABLE = {1: 30, 2: 60, 3: 80}

_LCG_MULTIPLIER = 1103515245
_LCG_INCREMENT = 12345
_LCG_MASK = 0x7FFFFFFF

_MIN_WIDTH = 12
_MIN_HEIGHT = 8
_INITIAL_LIVES = 3
_FORM_ANCHOR_X = 2
_FORM_COLS = 4
_FORM_ROWS = ((2, 3), (3, 2), (4, 1), (5, 1))  # (y, kind)
_DIVE_BASE_PERCENT = 1
_DIVE_MAX_PERCENT = 4
_MAX_SWAY_BASE = 20
_PLAYER_TOP_MARGIN = 2
_BULLET_TOP_MARGIN = 3
_BOMB_DROP_BASE = 6
_BOMB_DROP_SPREAD = 4
_BOMB_DROP_Y_OFFSET = 2
_EXPLODE_TICKS = 4
_RESPAWN_COOLDOWN = 4


def lcg_next(rng_state: int) -> int:
    """One pinned LCG step: rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF."""
    return (rng_state * _LCG_MULTIPLIER + _LCG_INCREMENT) & _LCG_MASK


def lcg_draw(rng_state: int) -> tuple[int, int]:
    """Consume one LCG step; return (new_rng_state, percent draw in 0..99)."""
    nxt = lcg_next(rng_state)
    return nxt, (nxt >> 16) % 100


@dataclass(frozen=True)
class Enemy:
    kind: int
    mode: str  # 'F' formation | 'D' diving | 'E' exploding
    x: int  # anchor cell: top-left of the sprite mask
    y: int
    slot: tuple  # (dx, dy) offset from the form anchor
    dx: int = 0  # horizontal drift, 'D' only
    explode: int = 0  # remaining explosion ticks, 'E' only


@dataclass(frozen=True)
class State:
    width: int
    height: int
    tick_count: int
    rng_state: int
    player_x: int
    player_alive: bool
    cooldown: int
    lives: int
    score: int
    wave: int
    form_offset: int
    form_dir: int
    game_over: bool
    bullets: tuple = ()  # (x, y), at most one
    bombs: tuple = ()  # (x, y)
    stars: tuple = ()  # (x, y), decorative
    enemies: tuple = ()  # Enemy


def _sway_max(width: int) -> int:
    return max((width - _MAX_SWAY_BASE) // 2, 0)


def _build_form(form_offset: int) -> tuple:
    enemies = []
    for row_y, kind in _FORM_ROWS:
        for col in range(_FORM_COLS):
            enemies.append(
                Enemy(
                    kind=kind,
                    mode="F",
                    x=_FORM_ANCHOR_X + _FORM_COLS * col + form_offset,
                    y=row_y,
                    slot=(_FORM_COLS * col, row_y - 2),
                    dx=0,
                    explode=0,
                )
            )
    return tuple(enemies)


def _gen_stars(rng_state: int, width: int, height: int) -> tuple:
    stars = []
    for _ in range(width // 4):
        rng_state, x_draw = lcg_draw(rng_state)
        rng_state, y_draw = lcg_draw(rng_state)
        stars.append((x_draw % width, y_draw % (height - _PLAYER_TOP_MARGIN)))
    return tuple(stars), rng_state


def new_game(seed: int, width: int, height: int) -> State:
    if width < _MIN_WIDTH:
        raise ValueError(f"width must be >= {_MIN_WIDTH}, got {width}")
    if height < _MIN_HEIGHT:
        raise ValueError(f"height must be >= {_MIN_HEIGHT}, got {height}")
    if height % 2 != 0:
        raise ValueError(f"height must be even, got {height}")
    rng_state = seed & _LCG_MASK
    stars, rng_state = _gen_stars(rng_state, width, height)
    return State(
        width=width,
        height=height,
        tick_count=0,
        rng_state=rng_state,
        player_x=width // 2,
        player_alive=True,
        cooldown=0,
        lives=_INITIAL_LIVES,
        score=0,
        wave=1,
        form_offset=0,
        form_dir=1,
        game_over=False,
        bullets=(),
        bombs=(),
        stars=stars,
        enemies=_build_form(0),
    )


def move(state: State, dx: int) -> State:
    """Shift the player by dx in {-1, +1}; clamped to [1, width-2].

    A clamped (invalid) move or a move after game_over returns a state
    equivalent to the input, tick_count included.
    """
    if state.game_over or dx not in (-1, 1):
        return state
    new_x = state.player_x + dx
    if new_x < 1 or new_x > state.width - _PLAYER_TOP_MARGIN:
        return state
    return replace(state, player_x=new_x, tick_count=state.tick_count + 1)


def fire(state: State) -> State:
    """Create one bullet at (player_x, height-3) when the gun is allowed to fire."""
    if state.game_over or state.bullets or state.cooldown != 0 or not state.player_alive:
        return state
    return replace(state, bullets=((state.player_x, state.height - _BULLET_TOP_MARGIN),))


def tick(state: State) -> State:  # noqa: C901 — one linear simulation pass
    """Advance the simulation by one tick. No-op (equivalent state) after game_over."""
    if state.game_over:
        return state

    rng_state = state.rng_state

    # Respawn countdown runs before collisions: a hit sets cooldown=4 and is
    # decremented only by the FOLLOWING ticks (respawn after 4 ticks).
    cooldown = max(0, state.cooldown - 1)
    player_alive = True if cooldown == 0 else state.player_alive

    # 'E' enemies tick down (a freshly hit enemy is NOT decremented this tick).
    enemies = []
    for enemy in state.enemies:
        if enemy.mode == "E":
            explode = enemy.explode - 1
            if explode <= 0:
                continue
            enemy = replace(enemy, explode=explode)
        enemies.append(enemy)

    # Formation sway: form_offset += form_dir, flipped at [0, sway_max].
    sway_max = _sway_max(state.width)
    form_offset, form_dir = state.form_offset, state.form_dir
    if sway_max > 0:
        new_offset = form_offset + form_dir
        if new_offset > sway_max or new_offset < 0:
            form_dir = -form_dir
            new_offset = form_offset + form_dir
        form_offset = new_offset
    enemies = [
        replace(e, x=_FORM_ANCHOR_X + form_offset + e.slot[0]) if e.mode == "F" else e
        for e in enemies
    ]

    # Dives: one LCG draw per 'F' enemy; at most one new 'D' per tick.
    # Then 'D' movement: y += 1, x += dx, bounce off the field edges,
    # bomb drop, and exit at y >= height-2.
    dive_chance = min(_DIVE_BASE_PERCENT + (state.wave - 1), _DIVE_MAX_PERCENT)
    d_created = False
    updated = []
    dropped_bombs = []
    for enemy in enemies:
        if enemy.mode == "F":
            rng_state, draw = lcg_draw(rng_state)
            if not d_created and draw < dive_chance:
                rng_state, dx_draw = lcg_draw(rng_state)
                enemy = replace(enemy, mode="D", dx=dx_draw % 3 - 1)
                d_created = True
        if enemy.mode == "D":
            x = enemy.x + enemy.dx
            y = enemy.y + 1
            dx = enemy.dx
            if x <= 0:
                x, dx = 0, 1
            elif x >= state.width - 1:
                x, dx = state.width - 1, -1
            rng_state, draw = lcg_draw(rng_state)
            if y == _BOMB_DROP_BASE + draw % _BOMB_DROP_SPREAD:
                dropped_bombs.append((x, y + _BOMB_DROP_Y_OFFSET))
            if y >= state.height - _PLAYER_TOP_MARGIN:
                continue
            enemy = replace(enemy, x=x, y=y, dx=dx)
        updated.append(enemy)
    enemies = updated

    # Projectile movement.
    bullets = []
    for bullet in state.bullets:
        x, y = bullet
        if y - 1 >= 0:
            bullets.append((x, y - 1))
    bombs = []
    for bomb in state.bombs:
        x, y = bomb
        if y + 1 < state.height:
            bombs.append((x, y + 1))
    bombs.extend(dropped_bombs)

    # Collisions on anchor cells, after movement.
    score = state.score
    if bullets:
        bullet = bullets[0]
        hit = False
        struck = []
        for enemy in enemies:
            if not hit and enemy.mode in ("F", "D") and (enemy.x, enemy.y) == bullet:
                enemy = replace(enemy, mode="E", explode=_EXPLODE_TICKS)
                score += SCORE_TABLE[enemy.kind]
                hit = True
                bullets = []
            struck.append(enemy)
        enemies = struck
        if bullets:  # the bullet survived the enemies — try the bombs
            remaining = [b for b in bombs if b != bullet]
            if len(remaining) != len(bombs):
                bullets = []
            bombs = remaining

    lives = state.lives
    if player_alive and cooldown == 0:
        remaining = []
        hit_player = False
        for bomb in bombs:
            if not hit_player and bomb == (state.player_x, state.height - _PLAYER_TOP_MARGIN):
                hit_player = True
                continue
            remaining.append(bomb)
        if hit_player:
            lives -= 1
            player_alive = False
            cooldown = _RESPAWN_COOLDOWN
        bombs = remaining

    # Wave cleared -> next wave: rebuild the form, clear projectiles.
    wave = state.wave
    if not enemies:
        wave += 1
        enemies = list(_build_form(form_offset))
        bullets = []
        bombs = []

    # Stars: decorative, regenerated from the same LCG stream each tick.
    stars, rng_state = _gen_stars(rng_state, state.width, state.height)

    return replace(
        state,
        tick_count=state.tick_count + 1,
        rng_state=rng_state,
        player_alive=player_alive,
        cooldown=cooldown,
        lives=lives,
        score=score,
        wave=wave,
        form_offset=form_offset,
        form_dir=form_dir,
        game_over=lives == 0,
        bullets=tuple(bullets),
        bombs=tuple(bombs),
        stars=stars,
        enemies=tuple(enemies),
    )


def is_game_over(state: State) -> bool:
    return state.game_over
