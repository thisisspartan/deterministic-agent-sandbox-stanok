# smoke

`src/smoke.js` exports a single function `add(a, b)` that returns the numeric
sum of its two arguments (`add(2, 3) === 5`, `add(-1, 1) === 0`,
`add(0, 0) === 0`). This is a harness smoke module, not a product feature:
it exercises the full machine run (model turn -> Bash -> sandbox layers ->
external verifier) end-to-end. Tests live in `tests/smoke.test.js`
(node:test + node:assert/strict) and are run via
`bash scripts/run.sh test tests/smoke.test.js`.
