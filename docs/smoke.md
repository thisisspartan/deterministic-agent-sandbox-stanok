# smoke

Harness smoke module (ticket TASK-STANOK-SMOKE-01). `src/smoke.js` exports a single
function `add(a, b)` that returns the numeric sum of `a` and `b` (e.g. `add(2, 3) === 5`,
`add(-1, 1) === 0`). It exists solely to exercise the full machine pipeline
(model turn → Bash → sandbox layers → external verifier) end-to-end with a green
`bash scripts/run.sh test tests/smoke.test.js` (rc=0); it is not a product feature.
Reference tests live in `tests/smoke.test.js` (node:test + node:assert/strict).
