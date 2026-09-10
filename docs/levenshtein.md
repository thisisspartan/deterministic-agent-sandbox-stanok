# levenshtein

CommonJS module computing the Levenshtein edit distance between two strings.
No dependencies.

## API

```js
const { levenshtein } = require('../src/levenshtein.js');
```

### `levenshtein(a, b)`

- **Params:** `a: string`, `b: string`.
- **Returns:** `number` — the Levenshtein edit distance (non-negative integer).
- **Throws:** `TypeError` if either argument is not a string
  (numbers, `null`, `undefined`, arrays, booleans, ...).

## Definition

The Levenshtein edit distance is the minimum number of single-character
operations needed to transform `a` into `b`, where each operation costs 1:

- **insertion** — insert one character;
- **deletion** — delete one character;
- **substitution** — replace one character with another.

The distance is symmetric: `levenshtein(a, b) === levenshtein(b, a)`.
It equals 0 iff the strings are identical.

## Examples

```js
levenshtein('', '')            // 0
levenshtein('abc', 'abc')      // 0
levenshtein('', 'abc')         // 3  (three insertions)
levenshtein('abc', '')         // 3  (three deletions)
levenshtein('a', 'b')          // 1  (one substitution)
levenshtein('ab', 'ba')        // 2
levenshtein('kitten', 'sitting')   // 3
levenshtein('flaw', 'lawn')         // 2
levenshtein('sunday', 'saturday')   // 3
```

## Implementation notes

Dynamic programming over an `(a.length + 1) x (b.length + 1)` table, keeping
only two rows, so memory is `O(min(len(a), len(b)))` and time is
`O(len(a) * len(b))`.
