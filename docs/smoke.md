# src/smoke.js

Harness smoke module (not a product feature). It exists to exercise the full
machine pipeline — model turn → Bash tool → sandbox layers → external verifier —
and finish with rc=0 / verifier=PASS.

**Contract:** `src/smoke.js` exports `add(a, b)` which returns the numeric sum
`a + b` for numbers (integers and floats, including negative operands).
Reference tests live in `tests/smoke.test.js` and are run via
`bash scripts/run.sh test tests/smoke.test.js`.
