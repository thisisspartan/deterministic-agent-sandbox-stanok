# smoke

`src/smoke.js` exports a single function `add(a, b)` that returns the numeric sum
`a + b`. Inputs are expected to be numbers; the result is a number. This is a
harness smoke module — its only purpose is to exercise the run pipeline
(model turn -> Bash -> sandbox -> external verifier). Reference contract (see
`tests/smoke.test.js`): `add(2, 3) === 5`, `add(-1, 1) === 0`, and `add(0, 0) === 0`.
