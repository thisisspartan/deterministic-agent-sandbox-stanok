# smoke

Minimal arithmetic module used to exercise the full machine loop
(test red -> implement -> green -> docs).

## Contract

- `src/smoke.js` is a CommonJS module exporting `{ add }`.
- `add(a, b)` returns the numeric sum `a + b` (number in, number out).
- Examples: `add(2, 3) === 5`, `add(-1, 1) === 0`, `add(0, 0) === 0`.

## Run

- Test: `bash scripts/run.sh test tests/smoke.test.js`
- Module smoke: `bash scripts/run.sh smoke src/smoke.js`
