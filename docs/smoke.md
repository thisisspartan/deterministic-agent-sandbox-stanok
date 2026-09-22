# smoke

`src/smoke.js` exports a single function `add(a, b)` that returns the numeric
sum `a + b`. This is a harness smoke module — it exists to exercise the full
machine loop (test run via `scripts/run.sh test`, module smoke via
`scripts/run.sh smoke`) and is not a product feature. Reference tests:
`tests/smoke.test.js` (node:test), asserting `add(2,3)===5`, `add(-1,1)===0`,
`add(0,0)===0`.
