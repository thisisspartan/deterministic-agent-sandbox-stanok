# smoke.js

Harness smoke module, not a product feature. `src/smoke.js` exports a single
function `add(a, b)` that returns the numeric sum `a + b`. The reference
contract lives in `tests/smoke.test.js` (node:test + node:assert/strict) and
covers positive, negative, and zero operands. Its purpose is to exercise the
complete machine run — model turn, Bash tool, both sandbox layers, and the
external verifier via `scripts/run.sh` — and end green.
