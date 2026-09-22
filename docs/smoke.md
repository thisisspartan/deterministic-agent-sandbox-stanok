# smoke — harness smoke module

`src/smoke.js` exports `add(a, b)`, a pure function that returns the numeric
sum `a + b` of its two arguments; it is deterministic, O(1), and has no side
effects (loading the module is a no-op, so it smoke-runs clean).

- Test: `bash scripts/run.sh test tests/smoke.test.js` (node:test, 3 cases:
  `add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`).
- Smoke: `bash scripts/run.sh smoke src/smoke.js`.
