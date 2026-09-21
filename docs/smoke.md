# smoke.js

`src/smoke.js` exports a single function `add(a, b)` that returns the numeric sum
`a + b`. It is a harness smoke module (not a product feature): its reference test
`tests/smoke.test.js` asserts `add(2, 3) === 5`, `add(-1, 1) === 0`, and
`add(0, 0) === 0`, verifying the full machine run path (model -> Bash -> sandbox ->
verifier) end-to-end with rc=0.
