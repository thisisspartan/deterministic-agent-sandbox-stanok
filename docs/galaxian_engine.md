# galaxian_engine — module contract (CC-293)

A pure, seed-deterministic Galaxian engine. stdlib only; no time, no I/O,
no global mutable state. Every function is non-mutating: it returns a NEW
`State` (or a state equivalent to the input for no-op calls). All game
randomness flows from ONE pinned LCG stream — the same seed yields an
identical trajectory.

Tests: `bash scripts/run.sh test tests/galaxian_engine_test.py`.

## API (names pinned)

```
new_game(seed, width, height) -> State   # width >= 12, height >= 8 and even, else ValueError
move(state, dx) -> State                 # dx in {-1, +1}; clamped to player_x in [1, width-2]
fire(state) -> State                     # one bullet at (player_x, height-3) when allowed
tick(state) -> State                     # one simulation step
is_game_over(state) -> bool
```

A clamped/invalid `move`, a refused `fire`, and any call after `game_over`
return a state equivalent to the input, `tick_count` included. A valid
`move` increments `tick_count`; `fire` does not.

## Data (public frozen dataclasses)

`State(width, height, tick_count, rng_state, player_x, player_alive, cooldown,
lives, score, wave, form_offset, form_dir, game_over, bullets, bombs, stars,
enemies)` — bullets/bombs/stars are tuples of `(x, y)`; at most one bullet.

`Enemy(kind, mode, x, y, slot, dx=0, explode=0)` — kind 1..3, mode
`'F'` formation / `'D'` diving / `'E'` exploding; `(x, y)` is the anchor
cell (top-left of the sprite mask); `slot` is the `(dx, dy)` offset from
the form anchor. Coordinates: y=0 at the top.

Helpers: `lcg_next(rng)`, `lcg_draw(rng) -> (rng', draw)`, `SCORE_TABLE`.

## LCG (pinned verbatim)

Each consumption: `rng_state = (rng_state * 1103515245 + 12345) & 0x7FFFFFFF`;
percent draw = `(rng_state >> 16) % 100` (0..99). Dives, bombs and stars use
only this stream.

## Simulation (per `tick`, in order)

1. `cooldown -= 1` (floor 0); reaching 0 respawns the player. Runs before
   collisions, so a hit sets `cooldown=4` and respawns after 4 further ticks.
2. Existing `'E'` enemies: `explode -= 1`; at 0 the enemy is removed (a
   freshly hit enemy is NOT decremented in the hit tick).
3. Form sway: `form_offset += form_dir`, flipped at `[0, sway_max]`,
   `sway_max = max((width-20)//2, 0)`; `'F'` x = `2 + 4*col + form_offset`.
4. Dives: one LCG draw per `'F'`; transition chance `min(1+(wave-1), 4)`
   percent; at most ONE new `'D'` per tick; the new `'D'` gets `dx ∈ {-1,0,1}`
   from the LCG.
5. `'D'` movement: `y += 1`, `x += dx`, `dx` reflects off the field edges
   (x=0 → +1, x=width-1 → -1); if `y == 6 + draw%4` the diver drops one bomb
   at `(x, y+2)`; at `y >= height-2` the diver is removed.
6. Bullets `y -= 1` (removed above the top); bombs `y += 1` (removed below
   the bottom).
7. Collisions on anchor cells, after movement: bullet × `'F'`/`'D'` enemy →
   enemy becomes `'E'` with `explode=4`, bullet removed,
   `score += SCORE_TABLE[kind]` ({1:30, 2:60, 3:80}); bullet × bomb → both
   removed; bomb × player anchor `(player_x, height-2)` when
   `player_alive and cooldown == 0` → `lives -= 1`, player dead, `cooldown=4`,
   bomb removed.
8. Wave cleared (`enemies` empty) → `wave += 1`, rebuild the 16-enemy form
   (rows y=2 kind3 ×4, y=3 kind2 ×4, y=4 kind1 ×4, y=5 kind1 ×4; base
   x = 2 + 4*col), clear bullets and bombs.
9. `lives == 0` → `game_over=True`; afterwards `move`/`fire`/`tick` are no-ops.
10. Stars: regenerated from the LCG each tick, `width // 4` of them,
    `0 <= x < width`, `0 <= y < height-2`; decorative, never collide.

`new_game` starts with 3 lives, wave 1, the full 16-enemy form at
`form_offset=0`, and initial stars drawn from the seed.
