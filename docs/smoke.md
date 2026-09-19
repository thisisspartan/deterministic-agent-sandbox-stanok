# src/smoke.js — sandbox/env smoke

Harness smoke module (not a product feature). It exists to force a complete
machine run — model turn → Bash tool → both sandbox layers → external verifier.

Contract: the module exports `add(a, b)`, which returns the numeric sum `a + b`.
Reference tests live in `tests/smoke.test.js` (node:test + node:assert/strict)
and assert `add(2, 3) === 5`, `add(-1, 1) === 0`, and `add(0, 0) === 0`.
Run via `bash scripts/run.sh test tests/smoke.test.js`.
