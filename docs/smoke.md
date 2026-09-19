# smoke (src/smoke.js)

A minimal harness smoke module (TASK-STANOK-SMOKE-01), not a product feature.
It exports a single function `add(a, b)` that returns the numeric sum `a + b`;
no other behavior, state, or dependencies are part of the contract. Its tests
(`tests/smoke.test.js`) exercise the full machine pipeline (model turn → Bash
tool → sandbox layers → external verifier) with an expected rc=0 / PASS.
