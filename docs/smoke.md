# smoke

Minimal arithmetic module used to exercise the full machine loop
(test red -> implement -> green -> docs).

## Contract

- `src/smoke.js` exports `add(a, b)` via CommonJS (`module.exports = { add }`).
- `add(a, b)` returns the numeric sum `a + b`.

## Usage

```js
const { add } = require('./src/smoke.js');
add(2, 3); // -> 5
add(-1, 1); // -> 0
```

## Tests

Run with `bash scripts/run.sh test tests/smoke.test.js`.
