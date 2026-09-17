# smoke

`src/smoke.js` exports `add(a, b)` which returns the numeric sum `a + b`. It is a harness smoke module used to verify the full test pipeline (tests -> sandbox -> verifier); the reference contract is covered in `tests/smoke.test.js` (`add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`).
