# smoke

Minimal arithmetic module used to exercise the full machine loop
(test red -> implement -> green -> docs).

- `src/smoke.js` exports `add(a, b)` via CommonJS (`module.exports = { add }`).
- `add(a, b)` returns the numeric sum `a + b`.
- Covered by `tests/smoke.test.js` (`node --test`), e.g. `add(2, 3) === 5`,
  `add(-1, 1) === 0`, `add(0, 0) === 0`.
