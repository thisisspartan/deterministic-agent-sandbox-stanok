# smoke

`src/smoke.js` exports `add(a, b)`, which returns the numeric sum of its two
arguments. Contract: `add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`.
This is a harness smoke module used to exercise the full test pipeline.
