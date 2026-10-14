# doomfire — component contract

The classic DOOM fire effect for the terminal. Later tickets append their
sections (palette, terminal controller, CLI); this page documents the core
simulation module only.

## src/doomfire_core.py — core model (pure math, no I/O)

### Field representation

A heat field is `list[list[int]]`: rows top→bottom, `field[-1]` is the
bottom (source) row, every cell an `int` in `[0, 255]`. Heat never leaves
that range. Degenerate sizes are valid: `W=1` (offsets clamp to 0), `H=1`
(a step only reseeds the bottom row).

### API

- `create_field(width: int, height: int) -> list[list[int]]`
  All-zero field. Raises `ValueError` if `width < 1` or `height < 1`.
- `seed_bottom(field, rng) -> None`
  Mutates the bottom row in place: for x left→right,
  `field[-1][x] = rng.randint(128, 255)`.
- `step(field, rng) -> list[list[int]]`
  ONE frame advance, double-buffered: returns a NEW field, never mutates
  the input. For each row `y` in `0..height-2` top→bottom, for each `x`
  left→right:
  `off = rng.choice([-1, 0, 1])`, `decay = rng.randint(1, 3)`,
  `src_x = clamp(x + off, 0, width-1)`,
  `new[y][x] = max(0, field[y+1][src_x] - decay)`.
  After all rows: `seed_bottom(new, rng)`.
- `simulate(width, height, steps, seed) -> list[list[int]]`
  Convenience driver: `rng = random.Random(seed)`, `create_field`,
  `seed_bottom`, then `steps × step`; returns the final field.
  `steps >= 0` (0 → the seeded field).

### RNG-order contract

All randomness flows through the passed `rng` object; no module-level RNG
state. The call order is part of the contract and makes a run
reproducible for a given `rng`: rows top→bottom, columns left→right,
`off` before `decay`, bottom-row reseeding last.

### Invariants

- Every cell stays in `[0, 255]`; after any `step`, the bottom row is all
  in `[128, 255]`.
- Decay: for `y < height-1`, `max(new[y]) <= max(old[y+1])` — a row can
  only inherit heat from the row below it, minus decay.
- Purity: the module imports only `random`; no `sys`/`os`/`time`, no
  file/socket/print anywhere.
