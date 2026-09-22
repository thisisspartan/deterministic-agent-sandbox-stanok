# smoke — module contract

`src/smoke.js` is a harness smoke module, not a product feature. It exports a
single function `add(a, b)` which returns the numeric sum of its two arguments
(e.g. `add(2, 3) === 5`, `add(-1, 1) === 0`). It exists to exercise the full
machine pipeline (model turn → Bash tool → sandbox layers → external verifier)
and is verified by `tests/smoke.test.js` via `scripts/run.sh test
tests/smoke.test.js` (node:test, js stack).
