# wordfreq — word frequency over a text (TASK-STANOK-CC-245)

`src/wordfreq.py` — pure-text module, stdlib only (`re`, `collections.Counter`),
no file or socket I/O.

## Contract

### `tokenize(text) -> list[str]`

The lowercased word tokens of `text`, in order of appearance.

- A token is a maximal run of alphanumeric-or-underscore characters
  (`re \w+`); every other character — whitespace, punctuation, symbols — is a
  separator and is dropped.
- Digits and underscores stay **inside** a token: `"x_1"` is one token, not
  `"x"` and `"1"`.
- Tokens are lowercased, so `"Foo FOO foo"` -> `["foo", "foo", "foo"]`.
- Empty tokens never appear: adjacent, leading and trailing separators produce
  nothing. `""` and whitespace-only text give `[]`.

### `count_words(text) -> dict[str, int]`

`{token: occurrences}` — exactly the tally of `tokenize(text)`.
`""` gives `{}`. Keys are lowercased tokens; values are `int` counts.

### `top_words(text, n) -> list[tuple[str, int]]`

Up to `n` `(word, count)` pairs, most frequent first.

- Sort key: count **descending**, then word **ascending** (lexicographic) for
  ties — so `"delta charlie bravo alpha"` with `n=4` returns
  `alpha, bravo, charlie, delta`. Note this is plain string order: digits sort
  before letters (`"42" < "end"`).
- `n` is clamped to `[0, len(result)]`: `n <= 0` returns `[]`, and an `n`
  larger than the vocabulary returns the whole vocabulary.

## Examples

```python
>>> count_words("a,b;c\nd")
{'a': 1, 'b': 1, 'c': 1, 'd': 1}
>>> top_words("x x x y y z", 2)
[('x', 3), ('y', 2)]
>>> top_words("b b a a c c c", 3)
[('c', 3), ('a', 2), ('b', 2)]
>>> top_words("a b a", 100)          # n clamped to the vocabulary
[('a', 2), ('b', 1)]
```

## Tests

`tests/wordfreq_test.py` (pytest, run with `bash scripts/run.sh test
tests/wordfreq_test.py`): case folding, punctuation/boundary splitting,
digits/underscores kept, empty text, tie-break order, `n` clamping, and exact
counts on a pinned text.
