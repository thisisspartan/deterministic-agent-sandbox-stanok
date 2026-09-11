# fire_model.js

A small deterministic fire/heat simulation. Heat is generated in the bottom row
and rises upward, decaying as it spreads, using a classic "fire" cellular rule.
Uses only built-in Node.js modules (no npm packages).

## Exports

- `createModel({ width = 80, height = 24, seed = 1337 } = {})` →
  `{ width, height, heat, prng }`
  - `heat` is a row-major `Float64Array(width * height)`, initialized to all
    zeros; row 0 is the top row.
  - `prng = seed >>> 0` — the 32-bit integer state of a mulberry32 PRNG.

- `step(state)` → a **new** state object. It does not mutate the input
  `heat` or `prng`.

## Step rule

- **Bottom row** (`row = height - 1`): each of the `width` cells receives one
  fresh PRNG value in `[0, 1)`, drawn sequentially from mulberry32.
- **Every other row** `r` from `height - 2` down to `0`, each column `c`:
  ```
  new[r][c] = clamp(((belowLeft + below + belowRight) / 3) * DECAY, 0, 1)
  ```
  where, read from the **previous** frame:
  - `below      = heat[(r+1)*width + c]`
  - `belowLeft  = heat[(r+1)*width + max(0, c-1)]`
  - `belowRight = heat[(r+1)*width + min(width-1, c+1)]`
- `DECAY = 0.98`.
- The returned state's `prng` is the PRNG state after consuming `width` values.

## PRNG

mulberry32: 32-bit integer state, each draw advances the state and yields a
value in `[0, 1)`. Deterministic for a given seed.
