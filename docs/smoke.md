# smoke

`src/smoke.js` exports `add(a, b)` — returns the numeric sum of `a` and `b`.
This is a harness smoke module: it exercises the full run pipeline (tests,
sandbox, verifier) with the minimal possible contract. Verified by
`tests/smoke.test.js` (`add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`).
