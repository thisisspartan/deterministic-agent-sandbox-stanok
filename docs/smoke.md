# smoke.js

`src/smoke.js` exports `add(a, b)` and returns the numeric sum `a + b`.
This is a harness smoke module (not a product feature): it exists to verify
the full machine run path — model turn → Bash tool → sandbox → external
verifier — via `scripts/run.sh test tests/smoke.test.js`.
