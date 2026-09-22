# smoke

`src/smoke.js` exports `add(a, b)`, which returns the numeric sum of `a` and `b`.
It is a harness smoke module (not a product feature): it exercises the full
machine run — model turn, Bash tool, sandbox, and the external verifier — via
`tests/smoke.test.js` (node:test + node:assert/strict), which asserts
`add(2, 3) === 5`, `add(-1, 1) === 0`, and `add(0, 0) === 0`.
