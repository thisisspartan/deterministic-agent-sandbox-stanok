# smoke

`src/smoke.js` is a harness smoke module, not a product feature. It exports a
single function `add(a, b)` that returns the numeric sum of its two arguments
(`add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`). Its only purpose is
to exercise the full machine pipeline — model turn, Bash tool, both sandbox
layers, and the external verifier — and finish with rc=0 / verifier=PASS.
Covered by `tests/smoke.test.js` (node:test + node:assert/strict).
