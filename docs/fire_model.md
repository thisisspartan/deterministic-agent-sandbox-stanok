# fire_model

A 2D fire/heat simulation. Heat is injected stochastically into the bottom
row each step and rises upward, decaying as it propagates.

Row-major layout: `row 0` is the top, `row height-1` is the bottom.

## Exports

- `createModel({ width = 80, height = 24, seed = 1337 })`
  Returns `{ width, height, heat, prng }` where `heat` is a
  `Float64Array(width * height)` initialized to all zeros and
  `prng = seed >>> 0`.

- `step(state)`
  Returns a **new** state (does not mutate the input). One step of the model.

## Step rule

- Bottom row (`row height-1`): each of the `width` cells is one PRNG value in
  `[0, 1)`.
- Each other row `r` from `height-2` down to `0`, for each column `c`:

  ```
  new[r][c] = clamp(((belowLeft + below + belowRight) / 3) * DECAY, 0, 1)
  ```

  where the reads come from the row below (the freshly-computed rows,
  evaluated in-place bottom-up):

  - `below      = heat[(r+1)*width + c]`
  - `belowLeft  = heat[(r+1)*width + max(0, c-1)]`
  - `belowRight = heat[(r+1)*width + min(width-1, c+1)]`

  `DECAY = 0.98`.

- The returned state's `prng` is the PRNG state after consuming `width` values
  this step.

## PRNG

mulberry32 — 32-bit integer state, outputs in `[0, 1)`.

Built-in Node.js modules only.
