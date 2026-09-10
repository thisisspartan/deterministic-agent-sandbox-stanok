# `src/roman.js` — Roman numeral converter

CommonJS module, no dependencies. Exports exactly two functions:
`toRoman(n)` and `fromRoman(s)`.

## API

### `toRoman(n)`

- **Param:** `n` — integer in `1..3999`.
- **Returns:** canonical Roman numeral string (uppercase).
- **Throws:**
  - `TypeError` — if `n` is not an integer (floats, strings, `null`,
    `undefined`, booleans, objects).
  - `RangeError` — if `n < 1` or `n > 3999`.

### `fromRoman(s)`

- **Param:** `s` — string.
- **Returns:** integer value of the canonical Roman numeral (`1..3999`).
- **Throws:**
  - `TypeError` — if `s` is not a string.
  - `RangeError` — if `s` is not a valid canonical Roman numeral.

## Canonical form rules (both directions)

- Only symbols `I V X L C D M`, uppercase (lowercase is invalid).
- Subtractive pairs only: `IV, IX, XL, XC, CD, CM`.
- No symbol appears more than 3 times in a row.
- Values never increase left to right, except inside a subtractive pair.
- Empty string is invalid.

## Examples

```js
toRoman(1)       // 'I'
toRoman(14)      // 'XIV'
toRoman(1994)    // 'MCMXCIV'
toRoman(3999)    // 'MMMCMXCIX'

fromRoman('IV')      // 4
fromRoman('MCMXCIV') // 1994
fromRoman('MMMCMXCIX') // 3999
```

Invalid inputs that throw `RangeError`: `''`, `'IIII'`, `'MMMM'`, `'LC'`,
`'XM'`, `'ix'`, `'IVX'`, `'IIV'`, `'VIV'`.

## Tests

`tests/roman.test.js` — run with
`bash scripts/run.sh test tests/roman.test.js`. Covers value conversion,
full 1..3999 round-trip, and all error cases.
