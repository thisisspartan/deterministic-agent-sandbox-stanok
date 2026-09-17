# smoke

`src/smoke.js` exports a single function `add(a, b)` which returns the numeric
sum `a + b`. Both arguments are expected to be numbers and the result is a
number (e.g. `add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`).
This is a minimal harness smoke module exercising the full sandbox and
verification pipeline; it is not a product feature.
