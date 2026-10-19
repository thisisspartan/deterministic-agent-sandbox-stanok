# water_render — module contract (CC-300)

A pure terminal renderer: a water frame state -> one ANSI-truecolor frame
string. stdlib only (`math`); `src.water_engine` is NOT imported — the state
is read duck-typed (R0: `heights`, `light`, `foam`, `glint`, one value per
column). No I/O, no global mutable state: `render_frame` is a pure function
`state -> str`; identical input -> byte-identical output, and the state is
never mutated.

Tests: `bash scripts/run.sh test tests/water_render_test.py`
(oracle: `tests/water_render_contract_test.py`).

## API (names pinned)

```
P0 P1 P2 P3 P4 P5 FOAM GLINT   # palette stops, rgb tuples (module fields)
depth_color(r) -> tuple        # water color at depth r below the surface
water_color(l) -> tuple        # surface color at light level l
render_frame(state, width, height) -> str   # width < 12 or height < 4 -> ValueError
```

## R1 — palette

Exactly eight stops, in this order, built from these hex literals:

```
P0 #03121e  P1 #07294a  P2 #0d4f70  P3 #16799c
P4 #27a3c0  P5 #7fd4e0  FOAM #e9f6fa  GLINT #ffffff
```

WCAG sRGB relative luminance strictly increases along
`P0 -> P1 -> P2 -> P3 -> P4 -> P5 -> FOAM -> GLINT`.

## R2 — depth colors

```
r    = min(r, 8)
DEEP = [P4, P3, P2, P1, P0]
s    = min(3, int(r / 8 * 4));  u = r / 8 * 4 - s
mix(a, b, u) = per channel: floor(a_c + (b_c - a_c) * u + 0.5)   # half-up
depth_color(r) = mix(DEEP[s], DEEP[s + 1], u)
```

`r = 0` is the cell directly under the surface (P4); deeper rows darken to
P0, which `r >= 8` clamps to. Neighbouring depths differ by at most 32 per
channel (anti-banding).

## R3 — the frame

`water_color(l) = mix(P4, P5, clamp01(l))`, `clamp01(v) = max(0.0, min(1.0, v))`.

- **Row 0 — sky:** glyph `" "`, fg = bg = P0.
- **Row 1 — waterline:** `f = frac(heights[x] + 1.0)` (i.e.
  `h+1 - floor(h+1)`); `f >= 0.5` -> glyph `▀`, fg = `water_color(light[x])`,
  bg = `depth_color(1)`; otherwise glyph `▄`, fg = `water_color(light[x])`,
  bg = P0. Then the foreground overrides: FOAM if `foam[x]`, GLINT if
  `glint[x]` — GLINT is stronger than FOAM. The overrides never change the
  background or the glyph.
- **Rows >= 2:** glyph `" "`, fg = bg = `depth_color(row - 1)`.

Smoothness: neighbouring `water_color` values differ by at most 40 per
channel on a flat surface without foam/glint (FOAM/GLINT flashes are point
exceptions, not neighbour pairs).

## R4 — wire format

Exactly `height` lines joined by `"\n"`, no trailing `"\n"`. Each line is a
concatenation of exactly `width` cells

```
"\x1b[38;2;R;G;Bm" + "\x1b[48;2;R;G;Bm" + glyph
```

(fg and bg SGR codes back to back, no spaces inside the codes), terminated
by exactly one `"\x1b[0m"`; no other `"\x1b[0m"` inside a line.

`width < 12` or `height < 4` -> `ValueError`.

## R5 — determinism

Equal inputs give byte-for-byte equal output; nothing is shared or mutated
between calls.
