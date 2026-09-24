# smoke

`src/smoke.js` exports a single function `add(a, b)` that returns the numeric
sum of its two arguments (`a + b`). It is a harness smoke module, not a product
feature: it exists to exercise the full machine run (model turn -> Bash tool ->
sandbox layers -> external verifier) end-to-end. The reference contract is
asserted in `tests/smoke.test.js` (node:test + node:assert/strict):
`add(2, 3) === 5`, `add(-1, 1) === 0`, and `add(0, 0) === 0`. Run it with
`bash scripts/run.sh test tests/smoke.test.js` and sanity-load it with
`bash scripts/run.sh smoke src/smoke.js`.
