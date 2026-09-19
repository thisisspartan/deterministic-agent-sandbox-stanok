# smoke.js

Harness smoke module (TASK-STANOK-SMOKE-01), not a product feature.
Contract: `src/smoke.js` exports `add(a, b)` which returns the numeric sum
`a + b`. Reference tests in `tests/smoke.test.js` (node:test +
node:assert/strict) assert `add(2, 3) === 5`, `add(-1, 1) === 0`, and
`add(0, 0) === 0`. Run via `bash scripts/run.sh test tests/smoke.test.js`.
