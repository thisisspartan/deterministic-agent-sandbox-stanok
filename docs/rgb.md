# rgb.js

Dependency-free RGB color utilities for Node.js (CommonJS). Exports exactly three
functions:

- `hexToRgb(hex)` — converts a strict 7-character hex string (`#` + 6 hex digits,
  case-insensitive) to `{r, g, b}` with integer channels 0–255; anything else
  throws `Error`.
- `rgbToHex({r, g, b})` — converts an RGB object (each channel an integer 0–255)
  to a lowercase, zero-padded `#rrggbb` string; invalid objects throw `Error`.
- `mix(a, b, t)` — linearly interpolates between two RGB objects (integer
  channels, out-of-range values allowed so interpolation stays linear) with
  `t` in `[0, 1]` (`Math.round` per channel), returning a new object; invalid
  inputs throw `Error`.

For any valid color `c`, `hexToRgb(rgbToHex(c))` deep-equals `c` (round-trip).
The module is import-safe: no side effects on `require`.
