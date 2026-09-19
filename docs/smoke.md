# smoke — harness smoke module

`src/smoke.js` exports a single function `add(a, b)` which returns the numeric
sum of its two arguments. This is a sandbox/env smoke module, not a product
feature: it exists to exercise the full machine pipeline (model turn → Bash
tool → sandbox layers → external verifier) with a minimal, deterministic
contract, verified by `tests/smoke.test.js` (`node --test`).
