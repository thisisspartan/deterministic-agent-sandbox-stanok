# water_engine — module contract (CC-299)

Pure, deterministic water-surface functions. stdlib only (hashlib/math/
dataclasses); no I/O, no `random`, no time, no global mutable state. Every
function is a pure call: equal arguments give equal results, and no call
mutates its arguments or shares a mutable object with another call.

Tests: `bash scripts/run.sh test tests/water_engine_test.py`
(oracle: `tests/water_engine_contract_test.py`).

## Constants (module fields, pinned names)

```
MAX_AMPLITUDE = 0.94   MAX_SLOPE = 0.55      MAX_RIPPLE = 0.04
MIN_WIDTH     = 12     MAX_CYCLE_RATIO = 0.08
FOAM_SLOPE    = 0.25   FOAM_LIGHT = 0.85     GLINT_LIGHT = 0.97
```

## API (names pinned)

```
make_params(seed) -> WaveParams            # seed < 0 -> ValueError
surface_height(params, x, t, width) -> float   # width < 12 -> ValueError
frame_state(params, t, width) -> FrameState    # width < 12 -> ValueError
_cycles_eff(c, width) -> int                   # helper
```

## Data (public frozen dataclasses)

`WaveParams(seed, amplitudes, cycles, omegas, phases, light_cycles)` —
`amplitudes` is exactly `(0.45, 0.30, 0.15)`; `cycles` is 3 ints each in
`{2, 3, 4}`; `omegas` is 3 floats in `[0.04, 0.12)`; `phases` is 3 floats in
`[0, 2π)`; `light_cycles ∈ {2, 3}`.

`FrameState(heights, light, foam, glint)` — all four fields are tuples of
length `width`: `heights`/`light` are floats, `foam`/`glint` are bools.

## E1 — derivation

`d = sha256("water|<seed>").digest()`; then
`cycles[i] = 2 + d[i] % 3`, `light_cycles = 2 + d[3] % 2`,
`omegas[i] = 0.04 + 0.08 * (int.from_bytes(d[4+2i : 6+2i], "big") / 65536)`,
`phases[i] = 2π * (int.from_bytes(d[10+2i : 12+2i], "big") / 65536)`.
Equal seeds give equal params; different seeds differ at least in `phases`.

## E2 — surface

`_cycles_eff(c, W) = max(1, min(c, int(W * 0.08)))` — a cycle count usable
on this width (at most 8% of a cycle per cell; this is what keeps the
neighbour slope under `MAX_SLOPE`).

`x` is reduced `x %= width` FIRST (also before the ripple hash), then

```
h = Σ_i amplitudes[i] * sin(2π * _cycles_eff(cycles[i], W) * x / W
                            + omegas[i] * t + phases[i]) + ripple
ripple = 0.04 * (2u - 1),
u = int.from_bytes(sha256("ripple|<seed>|<x>|<t>").digest()[:8], "big") / 2**64
```

Periodic in x mod width: `h(x + k·W, t) == h(x, t)`. Strictly
`|h| ≤ MAX_AMPLITUDE` (0.90 of sines + 0.04 of ripple).

## E3 — frame

```
heights[x] = surface_height(params, x, t, width)
light[x]   = clamp01(0.5 + 0.3*sin(k_l*x + omegas[0]*t + phases[0])
                         + 0.25*cos(2π*x/7 + 0.7*t)),
             k_l = 2π * _cycles_eff(light_cycles, W) / W
foam[x]    = light[x] > FOAM_LIGHT
             and abs(heights[(x+1) % W] - heights[(x-1) % W]) / 2 > FOAM_SLOPE
glint[x]   = foam[x] and light[x] > GLINT_LIGHT
```

`clamp01(v) = max(0.0, min(1.0, v))`, so `0 ≤ light ≤ 1`. Invariants for all
valid params, `width ≥ 12` and any `t`: `abs(heights[x+1] - heights[x]) ≤
MAX_SLOPE` for every neighbour pair, including the wrap `x = width-1 → x = 0`.

## E4 — immutability

All `FrameState` fields are tuples; `frame_state` is pure (equal arguments →
equal states). Two calls with different widths share no mutable object, and no
call changes `params`.

## E5 — temporal coherence

`|h(x, t+1) - h(x, t)| ≤ 0.50` for every valid x, t: each sine moves at most
`amplitudes[i] * 2·sin(omegas[i]/2) < 0.9 * 0.12` per tick, and two ripple
draws differ by at most `2 * MAX_RIPPLE = 0.08`.
