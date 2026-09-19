# src/smoke.js — sandbox/env smoke (TASK-STANOK-SMOKE-01)

`src/smoke.js` is a minimal harness smoke module, not a product feature. It exports
a single function `add(a, b)` that returns the numeric sum `a + b` (works for
integers, floats, and negatives). The reference contract is enforced by
`tests/smoke.test.js` (node:test + node:assert/strict), asserting at least
`add(2, 3) === 5`, `add(-1, 1) === 0`, and `add(0, 0) === 0`. Run it with
`bash scripts/run.sh test tests/smoke.test.js` (exit 0 = pass).
